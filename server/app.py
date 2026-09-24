"""FastAPI service for PreSense multimodal stress inference."""

from __future__ import annotations

import io
import os
import threading
import time
from functools import lru_cache

import cv2
import jwt
import numpy as np
import requests
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from PIL import Image

from inference import get_engine, health, predict

app = FastAPI(title="PreSense Multimodal Inference Server")
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
            raise HTTPException(status_code=401, detail="Invalid or expired Supabase session.")
    except HTTPException:
        raise
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
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
