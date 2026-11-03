"""FastAPI service for PreSense multimodal stress inference."""

from __future__ import annotations

import io
import logging
import os
import threading
import time
from functools import lru_cache
from typing import Literal

import cv2
import jwt
import numpy as np
import requests
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from inference import get_engine, health, predict
from agent.report_schema import ReviewRequest
from agent.coaching import localized_messages, CoachRequest, new_document
from agent.coach_ai import AIUnavailable, VERIFY_PROMPT, coaching_prompt, respond_with_ai
from agent.finding_evidence import complete_document_evidence
from datetime import datetime, timezone
from agent.report_agent import generate_report, luxia_decide_action, luxia_synthesize
from server.agent_memory import load_recent_memory, model_version

app = FastAPI(title="PreSense Multimodal Inference Server")
logger = logging.getLogger("presense.auth")
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3011",
    "http://127.0.0.1:3011",
    "https://hyupresense.netlify.app",
]
allowed_origins.extend(
    origin.strip().rstrip("/")
    for origin in os.getenv("PRESENSE_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer_scheme = HTTPBearer(auto_error=False)
supabase_url = (os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")).rstrip("/")
supabase_publishable_key = (
    os.getenv("SUPABASE_PUBLISHABLE_KEY")
    or os.getenv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "")
)
_jwks_url = f"{supabase_url}/auth/v1/.well-known/jwks.json" if supabase_url else ""
_issuer = f"{supabase_url}/auth/v1" if supabase_url else ""
_legacy_token_cache: dict[str, float] = {}
_legacy_token_cache_lock = threading.Lock()
luxia_api_key = os.getenv("LUXIA_API_KEY", "").strip()


@lru_cache(maxsize=1)
def _get_jwks_client():
    if not _jwks_url:
        return None
    return jwt.PyJWKClient(_jwks_url, cache_keys=True)


def _verify_legacy_token(token: str) -> bool:
    """Validate legacy HS256 tokens with Supabase Auth and briefly cache success."""
    if not supabase_url or not supabase_publishable_key:
        raise HTTPException(status_code=503, detail="Supabase auth is not configured on the inference server.")

    try:
        unverified_claims = jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False},
        )
        token_expiry = float(unverified_claims["exp"])
        if token_expiry <= time.time():
            logger.warning("Legacy Supabase access token is expired")
            raise HTTPException(status_code=401, detail="Invalid or expired Supabase session.")
    except HTTPException:
        raise
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
        logger.warning("Legacy Supabase token rejected (%s): %s", type(error).__name__, error)
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase session.") from error

    now = time.monotonic()
    with _legacy_token_cache_lock:
        expiry = _legacy_token_cache.get(token)
        if expiry and expiry > now:
            return True
        if expiry:
            _legacy_token_cache.pop(token, None)

    try:
        response = requests.get(
            f"{supabase_url}/auth/v1/user",
            headers={"apikey": supabase_publishable_key, "Authorization": f"Bearer {token}"},
            timeout=5,
        )
    except requests.RequestException as error:
        raise HTTPException(status_code=503, detail="Could not verify the Supabase session.") from error

    if response.status_code != 200:
        logger.warning("Supabase Auth rejected legacy token (HTTP %s)", response.status_code)
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase session.")

    with _legacy_token_cache_lock:
        if len(_legacy_token_cache) >= 1024:
            _legacy_token_cache.clear()
        _legacy_token_cache[token] = now + min(30, token_expiry - time.time())
    return True


def require_authenticated_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="A Supabase bearer token is required.")
    if not supabase_url:
        raise HTTPException(status_code=503, detail="SUPABASE_URL is not configured on the inference server.")

    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        algorithm = header.get("alg")
        if algorithm == "HS256":
            _verify_legacy_token(token)
            return {"authenticated": True}
        if algorithm not in {"ES256", "ES384", "ES512", "RS256", "RS384", "RS512", "EdDSA"}:
            raise HTTPException(status_code=401, detail="Unsupported Supabase token algorithm.")

        jwks_client = _get_jwks_client()
        if jwks_client is None:
            raise HTTPException(status_code=503, detail="Supabase signing keys are not configured.")
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[algorithm],
            audience="authenticated",
            issuer=_issuer,
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
        return claims
    except HTTPException:
        raise
    except (jwt.PyJWTError, requests.RequestException, ValueError) as error:
        logger.warning("Supabase token verification failed (%s): %s", type(error).__name__, error)
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase session.") from error


@app.on_event("startup")
def warmup() -> None:
    try:
        get_engine()
    except Exception as error:
        # Keep /health available with the initialization diagnostic.
        print(f"[inference] startup failed: {error}")


@app.get("/health")
def get_health() -> dict:
    status = health()
    return {"status": "ok" if status["checkpointLoaded"] else "degraded", **status,
            "modelVersion": model_version()}


def _coach_store(user, credentials):
    from server.coaching_store import CoachingStore
    return CoachingStore(supabase_url, supabase_publishable_key,
                         credentials.credentials if credentials else "", user.get("sub"))


def _generate_coaching(context):
    from agent.report_agent import _luxia_json
    return _luxia_json(coaching_prompt(context), context, 2600, read_timeout=35)


def _verify_coaching(context):
    from agent.report_agent import _luxia_json
    return _luxia_json(VERIFY_PROMPT, context, 160, read_timeout=15)


@app.get("/agent/coach/{session_id}")
def restore_coaching(session_id: str, language: Literal["ko", "en"] = "ko", _user: dict = Depends(require_authenticated_user),
                     credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    doc = complete_document_evidence(_coach_store(_user, credentials).get(session_id))
    if not doc: raise HTTPException(404, "No saved coaching data for this session.")
    return {"conversationState": doc["state"], "revision": doc["revision"], "messages": localized_messages(doc, language)}


@app.post("/agent/chat")
@app.post("/agent/coach")
def coach_action(body: CoachRequest, _user: dict = Depends(require_authenticated_user),
                 credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    store = _coach_store(_user, credentials)
    doc = complete_document_evidence(store.get(body.sessionId))
    if not doc: raise HTTPException(404, "No saved observations for this session. Generate a report first.")
    if body.revision is not None and body.revision != doc["revision"]:
        raise HTTPException(409, "Coaching changed. Reload and retry.")
    attempt_id = body.attemptSessionId or doc["state"].get("attemptSessionId")
    attempt = store.get(attempt_id) if attempt_id else None
    previous = None
    current_date = doc["snapshot"].get("recordedAt", "")
    if body.action in {"compare_previous_session", "ask"}:
        previous = next((row for row in store.previous(body.sessionId)
                         if not row["snapshot"]["request"].get("practiceContext")
                         and row["snapshot"].get("recordedAt", "") < current_date), None)
    ai_allowed = bool(luxia_api_key) and doc["snapshot"].get("dataOrigin") != "stressid"
    try:
        updated, response = respond_with_ai(doc, body, attempt=attempt, previous=previous,
                                           generate=_generate_coaching if ai_allowed else None,
                                           verify=_verify_coaching if ai_allowed else None)
    except AIUnavailable as error:
        raise HTTPException(503, {"code": "coach_ai_unavailable"}) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    store.save(body.sessionId, updated, doc["revision"])
    return response


@lru_cache(maxsize=1)
def _report_rag():
    """Open the prebuilt local paper index; indexing runs offline."""
    from agent.rag_db import PaperRAG
    return PaperRAG(sync=False)


@app.post("/agent/report")
def create_agent_report(
    body: ReviewRequest,
    _user: dict = Depends(require_authenticated_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Run a bounded post-session agent and retain verifiable memory in its report."""
    observed_version = body.modelVersion or model_version()
    try:
        rag = _report_rag()
    except Exception as error:
        logger.warning("Paper index unavailable (%s)", type(error).__name__)
        rag = None
    prior = load_recent_memory(supabase_url, supabase_publishable_key,
                               credentials.credentials if credentials else "", _user.get("sub"))
    previous_coaching = None
    try:
        previous_docs = _coach_store(_user, credentials).previous(body.sessionId)
        previous_doc = next((d for d in previous_docs if not d["snapshot"]["request"].get("practiceContext")), None)
        if previous_doc:
            memory = previous_doc["snapshot"]["report"].get("agentMemory")
            goal_id = previous_doc["state"].get("nextGoalId") or previous_doc["state"].get("selectedFindingId")
            goal = next((f for f in previous_doc["snapshot"]["report"]["priorities"] if f["id"] == goal_id), None)
            if memory and goal:
                prior = {**memory, "focusGoal": {"candidateId": goal_id, "metric": goal["metric"]}}
                previous_coaching = {"previousSessionId": memory["sessionId"], "goalLabel": goal["label"],
                                     "comparable": memory["modelVersion"] == observed_version and memory.get("metricDefinitionVersion") == body.metricDefinitionVersion and memory.get("sceneLabel") == body.sceneLabel,
                                     "lastOutcome": next((p["comparison"]["outcome"] for p in reversed(previous_doc["practices"]) if p.get("comparison")), None)}
    except HTTPException:
        pass
    ai_allowed = bool(luxia_api_key) and body.baselineSource != "dataset_example"
    report = generate_report(body, rag=rag,
                           synthesize=luxia_synthesize if ai_allowed else None,
                           decide=luxia_decide_action if ai_allowed else None,
                           prior_memory=prior, model_version=observed_version, agent_mode=True)
    if body.baselineSource == "dataset_example": report["dataOrigin"] = "stressid"
    if previous_coaching: report["previousCoaching"] = previous_coaching
    try:
        store = _coach_store(_user, credentials)
        doc = new_document(body, report, observed_version)
        doc["snapshot"]["recordedAt"] = datetime.now(timezone.utc).isoformat()
        if body.baselineSource == "dataset_example": doc["snapshot"]["dataOrigin"] = "stressid"
        if body.practiceContext:
            parent = store.get(body.practiceContext.sessionId)
            if not parent or parent["state"].get("activePracticeId") != body.practiceContext.practiceId or parent["state"]["stage"] not in {"recording","evaluating"}:
                raise HTTPException(422, "No active practice matches this recording.")
        stored = store.create(body.sessionId, doc)
        report = stored["snapshot"]["report"]
        report["coachingAvailable"] = body.baselineSource != "dataset_example"
        if body.baselineSource == "dataset_example": report["coachingDisabledReason"] = "dataset_privacy"
    except HTTPException as error:
        if error.status_code != 503: raise
        report["coachingAvailable"] = False
        logger.warning("Coaching storage unavailable; session report remains available")
    return report


@app.post("/infer")
async def infer(
    frames: list[UploadFile] = File(...),
    audio: UploadFile = File(...),
    task: str = Form("Speaking"),
    _user: dict = Depends(require_authenticated_user),
) -> dict:
    if len(frames) != 16:
        raise HTTPException(422, "Exactly 16 JPEG/PNG frames are required.")

    decoded_frames: list[np.ndarray] = []
    for frame in frames:
        payload = await frame.read()
        image = np.asarray(Image.open(io.BytesIO(payload)).convert("RGB"))
        decoded_frames.append(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

    audio_samples = np.frombuffer(await audio.read(), dtype=np.float32)
    if audio_samples.size == 0:
        raise HTTPException(422, "Audio samples are required.")
    # The browser sends 16 kHz Float32 PCM. Pad short warm-up windows for the model.
    target_samples = 160_000
    if audio_samples.size < target_samples:
        audio_samples = np.pad(audio_samples, (target_samples - audio_samples.size, 0))
    else:
        audio_samples = audio_samples[-target_samples:]

    try:
        return {**predict(np.stack(decoded_frames), audio_samples, task), "modelVersion": model_version()}
    except Exception as error:
        raise HTTPException(500, str(error)) from error
