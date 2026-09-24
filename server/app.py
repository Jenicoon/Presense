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
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image
from pydantic import BaseModel, Field

from inference import get_engine, health, predict

app = FastAPI(title="PreSense Multimodal Inference Server")
logger = logging.getLogger("presense.auth")
allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
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


class AgentReport(BaseModel):
    startBaseline: float
    averageStress: float
    peakValue: int
    peakPhase: str
    mostStressfulPhase: str
    confidence: float
    noticeable: bool


class AgentHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class AgentChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1200)
    language: Literal["ko", "en"] = "ko"
    report: AgentReport
    history: list[AgentHistoryMessage] = Field(default_factory=list, max_length=8)


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
    return {"status": "ok" if status["checkpointLoaded"] else "degraded", **status}


@app.post("/agent/chat")
def chat_with_agent(
    body: AgentChatRequest,
    _user: dict = Depends(require_authenticated_user),
) -> dict:
    if not luxia_api_key:
        raise HTTPException(status_code=503, detail="AI Agent is not configured on the inference server.")

    if body.language == "ko":
        system_prompt = (
            "당신은 발표 연습을 돕는 AI 코치입니다. 한국어로 2~4문장으로 답하세요. "
            "아래 세션 분석 수치만 근거로 삼고, 긴장 원인을 단정하거나 의학적 진단을 하지 마세요. "
            "관찰된 결과를 설명하고 사용자가 바로 해볼 수 있는 구체적인 연습 방법을 제안하세요. "
            "점수만으로 성격이나 감정을 단정하지 마세요.\n\n"
        )
        report_context = (
            f"세션 요약: 시작 기준 스트레스 {body.report.startBaseline:.0%}, "
            f"평균 {body.report.averageStress:.0%}, 최고 {body.report.peakValue}%, "
            f"최고 구간 {body.report.peakPhase}, 가장 높은 평균 구간 {body.report.mostStressfulPhase}, "
            f"모델 confidence {body.report.confidence:.0%}, "
            f"눈에 띄는 압박 여부 {('예' if body.report.noticeable else '아니요')}."
        )
    else:
        system_prompt = (
            "You are an AI coach for presentation practice. Reply in English in 2 to 4 concise sentences. "
            "Use only the session metrics below; do not diagnose or claim to know the cause of stress. "
            "Explain the observed result and suggest a concrete practice step. Do not infer personality or emotions from scores alone.\n\n"
        )
        report_context = (
            f"Session summary: starting stress baseline {body.report.startBaseline:.0%}, "
            f"average {body.report.averageStress:.0%}, peak {body.report.peakValue}%, "
            f"peak phase {body.report.peakPhase}, highest-average phase {body.report.mostStressfulPhase}, "
            f"model confidence {body.report.confidence:.0%}, "
            f"noticeable pressure: {'yes' if body.report.noticeable else 'no'}."
        )

    messages = [{"role": "system", "content": system_prompt + report_context}]
    messages.extend(message.model_dump() for message in body.history[-8:])
    messages.append({"role": "user", "content": body.message})

    try:
        response = requests.post(
            "https://bridge.luxiacloud.com/luxia/v1/chat",
            headers={"apikey": luxia_api_key, "Content-Type": "application/json"},
            json={
                "model": "luxia3-llm-32b-0731",
                "messages": messages,
                "max_tokens": 300,
            },
            timeout=35,
        )
        response.raise_for_status()
        reply = response.json()["choices"][0]["message"]["content"].strip()
    except requests.RequestException as error:
        logger.error("Luxia chat request failed (%s)", type(error).__name__)
        raise HTTPException(status_code=502, detail="AI Agent service is unavailable.") from error
    except (KeyError, IndexError, TypeError, ValueError) as error:
        logger.error("Luxia returned an unexpected chat response (%s)", type(error).__name__)
        raise HTTPException(status_code=502, detail="AI Agent returned an invalid response.") from error

    if not reply:
        raise HTTPException(status_code=502, detail="AI Agent returned an empty response.")
    return {"reply": reply}


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
        return predict(np.stack(decoded_frames), audio_samples, task)
    except Exception as error:
        raise HTTPException(500, str(error)) from error
