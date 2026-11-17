"""FastAPI service for PreSense multimodal stress inference."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
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
from agent.report_schema import ReviewRequest, Contract
from agent.report_feedback import (ReportFeedbackAgent, PROMPT as REPORT_FEEDBACK_PROMPT,
                                   VERIFY_PROMPT as REPORT_FEEDBACK_VERIFY,
                                   VERSION as REPORT_FEEDBACK_VERSION)
from agent.provider_privacy import external_ai_allowed
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
_research_health = {"status": "unavailable", "indexedChunks": 0}


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
    try:
        rag = _report_rag()
        count = rag._collection.count() if rag is not None else 0
        _research_health.update(status="ready" if count else "empty", indexedChunks=count)
        logger.info("Paper retrieval ready: %s indexed chunks", count)
    except Exception as error:
        _research_health.update(status="unavailable", indexedChunks=0)
        logger.warning("Paper retrieval initialization failed (%s)", type(error).__name__)


@app.get("/health")
def get_health() -> dict:
    status = health()
    return {"status": "ok" if status["checkpointLoaded"] else "degraded", **status,
            "modelVersion": model_version(), "research": _research_health}


def _coach_store(user, credentials):
    from server.coaching_store import CoachingStore
    return CoachingStore(supabase_url, supabase_publishable_key,
                         credentials.credentials if credentials else "", user.get("sub"))


def _coaching_json(prompt, context, max_tokens, read_timeout):
    from agent.report_agent import _luxia_json
    from agent.coach_ai import anonymize_provider_context
    safe, restore_ids = anonymize_provider_context(context)
    return restore_ids(_luxia_json(prompt, safe, max_tokens, read_timeout=read_timeout))


def _generate_coaching(context):
    from agent.coaching_next_step import TASK, PROMPT as NEXT_PROMPT
    if context.get("task") == TASK:
        return _coaching_json(NEXT_PROMPT, context, 700, 15)
    if context.get('comparisonQuestion'):
        # The model needs metric names and directions to write a specific check,
        # but exact values remain server-owned evidence inserted after generation.
        comparison_facts = context['facts']
        comparison_schema = {
            'type': 'object',
            'required': ['action', 'findingId', 'evidenceIds', 'message', 'practice',
                         'reviewGuide', 'videoRefs', 'followUps'],
            'properties': {
                'action': {'const': 'ask'},
                'findingId': {'type': 'null'},
                'evidenceIds': {'type': 'array', 'items': {'type': 'string', 'enum': list(comparison_facts)}},
                'message': {'type': 'object', 'required': ['ko', 'en'],
                            'properties': {'ko': {'type': 'string'}, 'en': {'type': 'string'}}},
                'practice': {'type': 'null'}, 'reviewGuide': {'type': 'null'},
                'videoRefs': {'type': 'array', 'maxItems': 0},
                'followUps': {'type': 'array', 'maxItems': 0},
            },
        }
        required_ids = ['comparison.result', 'comparison.selection']
        required_ids.extend(context.get('comparisonHighlights', [])[:1])
        required_ids.extend(list(context.get('researchRefs', {}))[:3])
        context = {key: context[key] for key in (
            'request', 'allowedActions', 'dataOrigin', 'comparisonQuestion',
            'comparisonHighlights', 'researchRefs', 'responseTask', 'validationFeedback'
        ) if key in context}
        context.update(requiredEvidencePlaceholders=[f'{{{{evidence:{identity}}}}}' for identity in required_ids],
                       responseSchema=comparison_schema, facts={
            identity: {
                language: re.sub(r'[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?', '', text,
                                 flags=re.IGNORECASE)
                for language, text in fact.items()
            }
            for identity, fact in comparison_facts.items()
        })
    if (not context.get('findings')
            and not context.get('comparisonQuestion')
            and context.get('request', {}).get('action') in {'review', 'ask'}):
        # Exact numbers are inserted by the server after the model selects
        # evidence IDs. Do not ask the model to copy them into its prose.
        descriptions = {'current.summary': {'ko':'저장된 분석 요약. 실제 수치는 서버가 표시합니다.',
                                            'en':'Saved analysis summary; the server displays its exact values.'}}
        if context['request']['action'] == 'ask':
            descriptions = {identity:{language:re.sub(r'[+-]?\d+(?:\.\d+)?', '', text)
                                      for language,text in fact.items()}
                            for identity,fact in context['facts'].items()}
        context = {key:context[key] for key in ('request','state','allowedActions','dataOrigin','responseSchema','selectionStatus') if key in context}
        context.update(findings=[], practiceMethods={}, videoRefs={},
            facts=descriptions,
            responseTask='Write your own short explanation that no correction target is selected. Do not invent a problem or an exercise. No guide, numbers or placeholders.')
        if context.get('selectionStatus') == 'decision_unavailable':
            context['responseTask'] = 'Problem selection did not pass validation. Acknowledge that selection is incomplete, NOT that this presentation has no issues. Saved measurements are available. Do not invent an exercise or numbers.'
    return _coaching_json(
        coaching_prompt(context), context,
        900 if context.get('comparisonQuestion') else 2600,
        90 if context.get('comparisonQuestion') else 35,
    )


def _verify_coaching(context):
    from agent.coaching_next_step import TASK, VERIFY_PROMPT as NEXT_VERIFY_PROMPT
    prompt = NEXT_VERIFY_PROMPT if context.get("task") == TASK else VERIFY_PROMPT
    evidence_ids = set((context.get('plan') or {}).get('evidenceIds', []))
    is_comparison = {'comparison.result', 'comparison.selection'} <= evidence_ids
    if is_comparison:
        # Comparison prose already passed the strict local fact-token, numeric,
        # language and action checks. A second provider call only duplicates
        # validation and can turn a valid generated answer into a timeout.
        return {'supported': True, 'reason': 'server comparison contract passed'}
    if (context.get('task') != TASK and not is_comparison
            and not context.get('practiceMethods')
            and not context.get('activePractice') and not (context.get('plan') or {}).get('findingId')):
        prompt = """Check only whether the proposed reply invents observations or contradicts supplied facts.
Return ONLY JSON {"supported":true|false,"reason":"short explanation"}.
There is NO selected correction target and NO supported practice strategy.
Do NOT require an exercise, actionable steps or a practice strategy. Explaining
what is available, acknowledging limitations or offering a follow-up is valid.
Literal {{evidence:ID}} tokens refer to the supplied server-owned facts. They
are authoritative placeholders, not invented values or claims of watching video.
When dataOrigin=synthetic, references to synthetic data or its saved test facts
are valid. Reject pretending that synthetic measurements prove real delivery.
Do not require the answer to repeat the word synthetic if its fact token already
contains that disclosure. Proposed future actions are not claims of past behavior.
Reject invented causes, diagnoses, speech content, measurements or improvement."""
    return _coaching_json(
        prompt, context, 240,
        10 if context.get("task") == TASK else 30 if is_comparison else 15,
    )


@app.get("/agent/coach/{session_id}")
def restore_coaching(session_id: str, language: Literal["ko", "en"] = "ko", _user: dict = Depends(require_authenticated_user),
                     credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    doc = complete_document_evidence(_coach_store(_user, credentials).get(session_id))
    if not doc: raise HTTPException(404, "No saved coaching data for this session.")
    return {"conversationState": doc["state"], "revision": doc["revision"], "messages": localized_messages(doc, language), "dataOrigin": doc["snapshot"].get("dataOrigin", doc["snapshot"]["report"].get("dataOrigin", "recorded"))}


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
                         and row["snapshot"].get("dataOrigin") != "stressid"
                         and row["snapshot"]["request"].get("baselineSource") != "dataset_example"
                         and (not current_date
                              or not row["snapshot"].get("recordedAt")
                              or row["snapshot"]["recordedAt"] < current_date)), None)
    ai_allowed = bool(luxia_api_key) and doc["snapshot"].get("dataOrigin") != "stressid" and external_ai_allowed(ReviewRequest.model_validate(doc["snapshot"]["request"]), doc["snapshot"])
    try:
        updated, response = respond_with_ai(doc, body, attempt=attempt, previous=previous,
                                           generate=_generate_coaching if ai_allowed else None,
                                           verify=_verify_coaching if ai_allowed else None,
                                           retrieve_research=_retrieve_coaching_research if ai_allowed else None)
    except AIUnavailable as error:
        raise HTTPException(503, {"code": "coach_ai_unavailable", "reason": error.reason}) from error
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    store.save(body.sessionId, updated, doc["revision"])
    return response


@lru_cache(maxsize=1)
def _report_rag():
    """Open the prebuilt local paper index; indexing runs offline."""
    from agent.rag_db import PaperRAG
    return PaperRAG(sync=False)


def _coaching_research_topic(context: dict) -> str | None:
    """Resolve the highlighted saved measurement to a curated RAG topic."""
    from agent.session_analyzer import MEASUREMENT_INFO

    measurements = (context.get("comparison") or {}).get("measurements") or []
    for row in measurements:
        metric_key = row.get("metric")
        modality = row.get("modality")
        entry = MEASUREMENT_INFO.get((modality, metric_key))
        if entry:
            return entry[0]
    combined = " ".join(
        value.get("ko", "") + " " + value.get("en", "")
        for identity, value in context.get("facts", {}).items()
        if identity.startswith("comparison.metric")
    ).lower()
    aliases = {
        "v2_eye_squint": ("눈꺼풀 조임", "eyelid tightening", "eye squint"),
        "v2_brow_down": ("눈썹 내림", "brow-down", "brow down"),
        "v2_jaw_open": ("턱 열림", "jaw opening", "jaw open"),
    }
    return next(
        (topic for topic, terms in aliases.items() if any(term in combined for term in terms)),
        None,
    )


@lru_cache(maxsize=1)
def _curated_coaching_trials() -> list[dict]:
    """Load peer-reviewed intervention trials selected for safe coaching use."""
    path = Path(__file__).resolve().parents[1] / "data" / "papers" / "coaching_trials.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Curated coaching trial registry is unavailable")
        return []
    return [row for row in rows if isinstance(row, dict)]


def _retrieve_coaching_research(context: dict) -> list[dict]:
    """Retrieve a bounded paper finding for comparison coaching.

    Only curated metadata enters coaching; raw PDF excerpts are not sent to the
    provider and sources are rendered by the server.
    """
    topic = _coaching_research_topic(context)
    if topic != "v2_eye_squint":
        return []
    from agent.session_analyzer import MEASUREMENT_INFO

    query = next(
        (entry[2] for entry in MEASUREMENT_INFO.values() if entry[0] == topic),
        topic.replace("_", " "),
    )
    measurement_hits = _report_rag().retrieve_issue_evidence(topic, query, k=3)
    measurement_hits = [
        hit for hit in measurement_hits
        if topic in hit.get("topics", []) and hit.get("findingKo")
    ]
    if not measurement_hits:
        return []
    hit = sorted(
        measurement_hits,
        key=lambda item: (item.get("applicability") != "direct", item.get("distance", 1)),
    )[0]
    if topic == "v2_eye_squint":
        fact_ko = (
            "눈꺼풀 조임 움직임은 양쪽 눈의 eyeSquint 계수를 평균한 값입니다. "
            "관련 연구에서는 AU7 눈꺼풀 조임 빈도가 더 높은 주관적 스트레스 반응과 연관됐지만, "
            "심박과 HF-HRV에서는 같은 방향이 아니었습니다."
        )
        fact_en = (
            "Eyelid-tightening movement is the mean bilateral eyeSquint coefficient. "
            "In the related study, more frequent AU7 activity was associated with greater subjective "
            "stress response, while heart-rate and HF-HRV associations did not follow the same direction."
        )
        scope_ko = (
            "말하기를 포함한 심리사회적 스트레스 과제의 연관성 연구입니다. "
            "개인의 상태를 진단하거나 눈꺼풀 움직임을 줄이는 연습의 효과를 시험한 연구는 아닙니다."
        )
    else:
        fact_ko = str(hit["findingKo"])
        fact_en = str(hit.get("scope") or "Related measurement research; not a test of a coaching exercise.")
        scope_ko = "측정값의 해석 범위를 설명하는 관련 연구이며, 특정 코칭 과제의 효과를 시험한 자료는 아닙니다."
    references = [{
        "id": hit["id"],
        "title": hit.get("title") or hit["source"],
        "articleUrl": hit.get("articleUrl"),
        "doi": hit.get("doi"),
        "factKo": fact_ko,
        "factEn": fact_en,
        "scopeKo": scope_ko,
        "scopeEn": hit.get("scope") or "Related measurement research; not a test of a coaching exercise.",
    }]
    gaze_hits = _report_rag().retrieve_issue_evidence(
        "gaze", "public speaking audience gaze external attention training", k=4,
    )
    practice_hit = next(
        (
            item for item in gaze_hits
            if item.get("evidenceRole") == "practice_specific" and item.get("findingKo")
        ),
        None,
    )
    if practice_hit:
        references.append({
            "id": practice_hit["id"],
            "title": practice_hit.get("title") or practice_hit["source"],
            "articleUrl": practice_hit.get("articleUrl"),
            "doi": practice_hit.get("doi"),
            "factKo": str(practice_hit["findingKo"]),
            "factEn": "A randomized VR study compared audience-focused with nonsocial external attention during public speaking; audience-focused practice increased looking time at audience heads, while between-group fear reduction was not clear.",
            "scopeKo": "한 차례의 가상현실 주의 전환 연구이며, 눈꺼풀 조임을 줄이는 훈련이나 일반 웹캠 발표를 시험한 연구는 아닙니다.",
            "scopeEn": practice_hit.get("scope") or "A one-session VR attention study, not an eyelid-tightening exercise.",
        })
    trial = next(
        (row for row in _curated_coaching_trials() if "gaze" in row.get("topics", [])),
        None,
    )
    if trial:
        references.append({
            "id": trial["id"],
            "title": trial["title"],
            "articleUrl": trial.get("article_url"),
            "doi": trial.get("doi"),
            "factKo": trial["finding_ko"],
            "factEn": trial["finding_en"],
            "scopeKo": trial["scope_ko"],
            "scopeEn": trial["scope_en"],
        })
    return references


def _generate_report_feedback(context):
    from agent.report_agent import _luxia_json
    return _luxia_json(REPORT_FEEDBACK_PROMPT, context, 4500, read_timeout=90)


def _verify_report_feedback(context):
    from agent.report_agent import _luxia_json
    return _luxia_json(REPORT_FEEDBACK_VERIFY, context, 350, read_timeout=30)


class ReportFeedbackConsent(Contract):
    selfRecordedTest: Literal[True]


@app.post("/agent/report/{session_id}/feedback/consent")
def authorize_report_feedback(session_id: str, body: ReportFeedbackConsent,
                              _user: dict = Depends(require_authenticated_user),
                              credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    store = _coach_store(_user, credentials)
    for attempt in range(3):
        existing = store.get(session_id)
        if not existing: raise HTTPException(404, {"code":"report_not_found"})
        request = ReviewRequest.model_validate(existing["snapshot"]["request"])
        if request.baselineSource == "dataset_example" or existing["snapshot"].get("dataOrigin") == "stressid":
            raise HTTPException(403, {"code":"dataset_privacy"})
        if external_ai_allowed(request, existing["snapshot"]):
            return {"allowed": True}
        # Consent is mutable session metadata, never part of the immutable
        # measurement request. Preserve observations, notes and prior feedback.
        existing["snapshot"]["externalAiConsent"] = True
        revision = existing["revision"]
        existing["revision"] += 1
        try:
            store.save(session_id, existing, revision)
            return {"allowed": True}
        except HTTPException as error:
            if error.status_code != 409: raise
            if attempt == 2:
                raise HTTPException(409, {"code":"report_consent_conflict"}) from error


@app.post("/agent/report/{session_id}/feedback")
def retry_report_feedback(session_id: str, _user: dict = Depends(require_authenticated_user),
                          credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    store = _coach_store(_user, credentials)
    existing = store.get(session_id)
    if not existing: raise HTTPException(404, "Saved report not found")
    request = ReviewRequest.model_validate(existing["snapshot"]["request"])
    current = existing["snapshot"]["report"]
    if not external_ai_allowed(request, existing["snapshot"]): raise HTTPException(403, {"code":"external_ai_not_enabled"})
    if (current.get("reportFeedback", {}).get("status") == "ready"
            and current.get("reportFeedback", {}).get("version") == REPORT_FEEDBACK_VERSION):
        return current
    if (current.get("reportFeedback", {}).get("status") == "blocked"
            or current.get("agentRun", {}).get("stopReason") in {"decision_unavailable", "action_limit"}):
        return create_agent_report(request, _user, credentials)
    updated = ReportFeedbackAgent(_generate_report_feedback if luxia_api_key else None,
                                  _verify_report_feedback if luxia_api_key else None).run(request, current)
    document = new_document(request, updated, existing["snapshot"]["modelVersion"])
    stored = store.create(session_id, document)
    return stored["snapshot"]["report"]


@app.post("/agent/report")
def create_agent_report(
    body: ReviewRequest,
    _user: dict = Depends(require_authenticated_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    """Run a bounded post-session agent and retain verifiable memory in its report."""
    saved = None
    # Reuse an already persisted independent report after a lost browser reply.
    # Check immutability BEFORE any external model request.
    try:
        from server.coaching_store import same_recording
        saved = _coach_store(_user, credentials).get(body.sessionId)
        if saved:
            if not same_recording(saved["snapshot"]["request"], body.model_dump()):
                raise HTTPException(409, "Session observations are immutable")
            if (saved["snapshot"]["report"].get("reportFeedback", {}).get("status") == "ready"
                    and saved["snapshot"]["report"].get("reportFeedback", {}).get("version") == REPORT_FEEDBACK_VERSION):
                return saved["snapshot"]["report"]
    except HTTPException as error:
        if error.status_code != 503: raise
    observed_version = body.modelVersion or model_version()
    try:
        rag = _report_rag()
        research_status = "ready" if rag is not None else "unavailable"
    except Exception as error:
        research_status = "unavailable"
        logger.warning("Paper index unavailable (%s)", type(error).__name__)
        rag = None
    prior = load_recent_memory(supabase_url, supabase_publishable_key,
                               credentials.credentials if credentials else "", _user.get("sub"))
    if prior:
        history = prior.get("history") or [prior]
        history = [memory for memory in history if memory.get("sessionId") != body.sessionId]
        if len(history) != len(prior.get("history") or [prior]):
            prior = {**history[0], "history": history} if history else None
    previous_coaching = None
    try:
        previous_docs = _coach_store(_user, credentials).previous(body.sessionId)
        previous_doc = next((d for d in previous_docs if not d["snapshot"]["request"].get("practiceContext")
                             and d["snapshot"].get("dataOrigin") != "stressid"
                             and d["snapshot"]["request"].get("baselineSource") != "dataset_example"), None)
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
    ai_allowed = bool(luxia_api_key) and external_ai_allowed(body, (saved or {}).get("snapshot"))
    report = generate_report(body, rag=rag,
                           synthesize=None,
                           decide=luxia_decide_action if ai_allowed else None,
                           prior_memory=prior, model_version=observed_version, agent_mode=True)
    report = ReportFeedbackAgent(_generate_report_feedback if ai_allowed else None,
                                 _verify_report_feedback if ai_allowed else None).run(body, report)
    report["researchStatus"] = research_status
    report["dataOrigin"] = "synthetic" if body.baselineSource == "synthetic" else "recorded"
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
        report["researchStatus"] = research_status
        report["coachingAvailable"] = body.baselineSource != "dataset_example"
        if body.baselineSource == "dataset_example": report["coachingDisabledReason"] = "dataset_privacy"
    except HTTPException as error:
        if error.status_code != 503: raise
        report["coachingAvailable"] = False
        report["coachingDisabledReason"] = ("setup_required" if isinstance(error.detail, dict)
                                            and error.detail.get("code") == "coaching_schema_missing" else "storage_unavailable")
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
