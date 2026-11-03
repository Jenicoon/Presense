"""Loopback-only preview of saved local inference; dataset AI egress is blocked.

Auth and storage are local demo substitutes. Production app never imports this
module. Dataset media and measurements stay local. External coaching is disabled for dataset examples.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path

if os.getenv("PRESENSE_LOCAL_PREVIEW") != "1":
    raise RuntimeError("Enable PRESENSE_LOCAL_PREVIEW=1 and bind to 127.0.0.1 only")

import jwt
from dotenv import load_dotenv
from fastapi import HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
# Optional local configuration file is read on the server, never served to UI.
if os.getenv("PRESENSE_SERVER_ENV"):
    load_dotenv(os.environ["PRESENSE_SERVER_ENV"])
from server import app as module
from agent.finding_evidence import complete_document_evidence

app = module.app
manifest_path = Path(
    os.getenv(
        "PRESENSE_PREVIEW_MANIFEST", "/private/tmp/presense-stressid/manifest.json"
    )
)
manifest = json.loads(manifest_path.read_text())
manifest["document"] = complete_document_evidence(manifest["document"])
if manifest["provenance"]["inference"] != "real":
    raise RuntimeError("This preview requires real model observations")
media = Path(manifest["mediaPath"])
storage = manifest_path.parent
state_file = storage / "coaching-state.json"
lock = threading.RLock()
base = manifest["document"]["state"]["sessionId"]
documents = (
    json.loads(state_file.read_text())
    if state_file.exists()
    else {base: manifest["document"]}
)
documents = {k: complete_document_evidence(v) for k, v in documents.items()}
if documents.get(base, {}).get("snapshot", {}).get("provenance") != manifest[
    "document"
]["snapshot"].get("provenance"):
    raise RuntimeError(
        "Use a new preview output directory when the source video or model changes"
    )
metadata_file = storage / "record-metadata.json"
record_metadata = (
    json.loads(metadata_file.read_text()) if metadata_file.exists() else {}
)
USER = {
    "id": "11111111-1111-4111-8111-111111111111",
    "aud": "authenticated",
    "role": "authenticated",
    "email": "coach@example.test",
    "app_metadata": {},
    "user_metadata": {"full_name": "PreSense Preview"},
    "created_at": "2026-10-28T00:00:00Z",
}
TOKEN = jwt.encode(
    {"sub": USER["id"], "aud": "authenticated", "exp": int(time.time()) + 86400},
    "local-preview-not-a-production-secret-2026",
    algorithm="HS256",
)
app.dependency_overrides[module.require_authenticated_user] = lambda: {
    "sub": USER["id"]
}
module.load_recent_memory = lambda *_: None
# Participant data is never eligible for external AI in this preview. The
# standalone synthetic verifier is the authorized path for provider tests.
if manifest["document"]["snapshot"].get("dataOrigin") != "synthetic":
    module.luxia_api_key = ""
    for document in documents.values():
        document["snapshot"]["report"]["coachingAvailable"] = False
        document["snapshot"]["report"]["coachingDisabledReason"] = "dataset_privacy"

if os.getenv("PRESENSE_PREVIEW_RAG_DIR"):
    from agent.rag_db import PaperRAG
    module._report_rag = lambda: PaperRAG(db_path=os.environ["PRESENSE_PREVIEW_RAG_DIR"],sync=False)
else:
    module._report_rag = lambda: None
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3015", "http://127.0.0.1:3015", "http://localhost:3016", "http://127.0.0.1:3016"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def loopback_only(request: Request, call_next):
    if request.client and request.client.host not in {"127.0.0.1", "::1", "localhost"}:
        return Response(status_code=403)
    return await call_next(request)


class Store:
    def get(self, identity):
        with lock:
            return deepcopy(documents.get(identity))

    def previous(self, identity):
        with lock:
            return [deepcopy(d) for k, d in documents.items() if k != identity]

    def _persist(self):
        temporary = state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(documents, ensure_ascii=False, allow_nan=False))
        temporary.replace(state_file)

    def create(self, identity, doc):
        with lock:
            documents.setdefault(identity, deepcopy(doc))
            self._persist()
            return deepcopy(documents[identity])

    def save(self, identity, doc, revision):
        with lock:
            if documents[identity]["revision"] != revision:
                raise HTTPException(409, "Revision conflict")
            documents[identity] = deepcopy(doc)
            self._persist()


module._coach_store = lambda *_: Store()

from server.local_calibration_store import LocalCalibrationStore
calibration_store = LocalCalibrationStore(storage / "user-calibration.json", USER["id"])


def records():
    result = []
    for identity, doc in documents.items():
        report = doc["snapshot"]["report"]
        metadata = record_metadata.get(identity, {})
        result.append(
            {
                "id": identity,
                "title": metadata.get("title")
                or (
                    "StressID · Speaking" if identity == base else "Practice recording"
                ),
                "session_date": doc["snapshot"].get(
                    "recordedAt", "2026-10-28T00:00:00Z"
                ),
                "duration_seconds": doc["snapshot"]["request"]["durationMs"] / 1000,
                "result": "Analysis complete",
                "stress_average": report["analysis"]["averageStress"],
                "diagnosis": report["summaryText"],
                "next_action": "Review with coach",
                "scene_label": "Live Camera",
                "timeline": [],
                "video_path": "preview/stressid-speaking.mp4"
                if identity == base
                else metadata.get("video_path"),
                "agent_report": report,
            }
        )
    return sorted(result, key=lambda r: r["session_date"], reverse=True)


@app.post("/auth/v1/token")
def login():
    return {
        "access_token": TOKEN,
        "refresh_token": "local-preview-refresh",
        "expires_in": 86400,
        "expires_at": int(time.time()) + 86400,
        "token_type": "bearer",
        "user": USER,
    }


@app.get("/auth/v1/user")
def user():
    return USER


@app.api_route("/rest/v1/{table}", methods=["GET", "POST", "PATCH"])
async def rest(table: str, request: Request):
    if table == "user_calibrations":
        if request.query_params.get("user_id", "eq." + USER["id"]) != "eq." + USER["id"]:
            raise HTTPException(403, "Calibration belongs to another user")
        with lock:
            if request.method == "GET":
                return calibration_store.read()
            body = await request.json()
            try:
                if request.method == "POST":
                    calibration_store.write(body)
                else:
                    calibration_store.prompted(body["last_prompted_at"])
            except (ValueError, KeyError, TypeError) as error:
                raise HTTPException(422, str(error)) from error
        return Response(status_code=204)
    if request.method != "GET":
        if table == "presentation_records":
            body = await request.json()
            identity = body.get("id")
            if identity not in documents:
                raise HTTPException(422, "A saved analysis snapshot is required")
            with lock:
                record_metadata[identity] = {
                    k: body.get(k) for k in ("title", "video_path")
                }
                metadata_file.write_text(
                    json.dumps(record_metadata, ensure_ascii=False)
                )
        return []
    if table == "presentation_records":
        return records()
    return Response(
        "null" if table == "user_settings" else "[]", media_type="application/json"
    )


@app.post("/storage/v1/object/sign/{bucket}/{path:path}")
def sign(bucket: str, path: str):
    return {"signedURL": f"/object/sign/{bucket}/{path}?token=preview"}


@app.get("/storage/v1/object/sign/{bucket}/{path:path}")
def video(bucket: str, path: str):
    if path == "preview/stressid-speaking.mp4":
        return FileResponse(media, media_type="video/mp4")
    target = storage / "uploads" / Path(path).name
    if not target.is_file():
        raise HTTPException(404, "No saved video")
    return FileResponse(target, media_type="video/webm")


@app.post("/storage/v1/object/{bucket}/{path:path}")
async def upload(bucket: str, path: str, request: Request):
    target = storage / "uploads" / Path(path).name
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(await request.body())
    return {"Key": path}
