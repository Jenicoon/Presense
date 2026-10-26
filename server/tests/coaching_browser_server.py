"""Loopback browser-test harness: synthetic inference and in-memory persistence.
Never used by server/app.py. Run with the test environment, without real secrets.
"""

import importlib.util, sys, types, time, os

if os.environ.get("PRESENSE_BROWSER_TEST") != "1":
    raise RuntimeError(
        "This synthetic harness requires PRESENSE_BROWSER_TEST=1 and loopback binding."
    )
from copy import deepcopy
from pathlib import Path
import jwt
from fastapi import Request
from fastapi.responses import Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from server.tests.test_coaching import document
from agent.coaching import new_document
from agent.report_schema import ReviewRequest

ROOT = Path(__file__).resolve().parents[2]
inference = types.ModuleType("inference")
inference.get_engine = lambda: None
inference.health = lambda: {"checkpointLoaded": True}
inference.predict = lambda *_: {}
sys.modules["inference"] = inference
sys.modules["cv2"] = types.ModuleType("cv2")
spec = importlib.util.spec_from_file_location(
    "coaching_browser_app", ROOT / "server/app.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
app = module.app
USER = {
    "id": "11111111-1111-4111-8111-111111111111",
    "aud": "authenticated",
    "role": "authenticated",
    "email": "coach@example.test",
    "app_metadata": {},
    "user_metadata": {"full_name": "Coach Test"},
    "created_at": "2026-10-27T00:00:00Z",
}
TOKEN = jwt.encode(
    {"sub": USER["id"], "aud": "authenticated", "exp": int(time.time()) + 86400},
    "test-secret-not-a-production-key-12345",
    algorithm="HS256",
)
app.dependency_overrides[module.require_authenticated_user] = lambda: {
    "sub": USER["id"]
}
module._report_rag = lambda: None
module.load_recent_memory = lambda *_: None
module.model_version = lambda: "test-model"
module.luxia_api_key = ""
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3015", "http://127.0.0.1:3015"],
    allow_methods=["*"],
    allow_headers=["*"],
)
BASE = "22222222-2222-4222-8222-222222222222"
OLDER = "33333333-3333-4333-8333-333333333333"
DOCS = {}
RECORDS = []
VIDEOS = {}
INFER_CALLS = []
for identity, date, changed in (
    (OLDER, "2026-10-25T00:00:00Z", False),
    (BASE, "2026-10-26T00:00:00Z", True),
):
    doc = document(identity, changed=changed)
    doc["snapshot"]["recordedAt"] = date
    doc["snapshot"]["request"]["sceneLabel"] = "Live Camera"
    DOCS[identity] = doc
    report = doc["snapshot"]["report"]
    RECORDS.insert(
        0,
        {
            "id": identity,
            "title": "Browser coaching baseline"
            if changed
            else "Earlier stable session",
            "session_date": date,
            "duration_seconds": 60,
            "result": "AI report complete",
            "stress_average": report["analysis"]["averageStress"],
            "diagnosis": report["summaryText"],
            "next_action": "Review selected interval",
            "scene_label": "Camera",
            "timeline": [],
            "video_path": "test/baseline.webm",
            "agent_report": report,
        },
    )


class Store:
    def get(self, identity):
        return deepcopy(DOCS.get(identity))

    def previous(self, identity):
        return [deepcopy(d) for k, d in DOCS.items() if k != identity]

    def create(self, identity, doc):
        DOCS.setdefault(identity, deepcopy(doc))
        return doc

    def save(self, identity, doc, revision):
        from fastapi import HTTPException

        if DOCS[identity]["revision"] != revision:
            raise HTTPException(409, "Revision conflict")
        DOCS[identity] = deepcopy(doc)


module._coach_store = lambda *_: Store()


@app.post("/auth/v1/token")
def login():
    return {
        "access_token": TOKEN,
        "refresh_token": "test-refresh",
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
    if request.method != "GET":
        if table == "presentation_records":
            RECORDS.insert(0, await request.json())
        return []
    if table == "presentation_records":
        return RECORDS
    if table == "user_settings":
        return Response("null", media_type="application/json")
    return []


@app.post("/storage/v1/object/sign/{bucket}/{path:path}")
def sign(bucket: str, path: str):
    return {"signedURL": f"/object/sign/{bucket}/{path}?token=test"}


@app.api_route("/storage/v1/object/{bucket}/{path:path}", methods=["POST"])
async def upload(bucket: str, path: str, request: Request):
    if request.method == "POST":
        VIDEOS[path] = await request.body()
        return {"Key": path}
    return Response(VIDEOS.get(path, b""), media_type="video/webm")


@app.get("/storage/v1/object/sign/{bucket}/{path:path}")
def video(bucket: str, path: str):
    if path in VIDEOS:
        return Response(VIDEOS[path], media_type="video/webm")
    return FileResponse("/private/tmp/coach-baseline.webm", media_type="video/webm")


app.router.routes[:] = [
    r for r in app.router.routes if getattr(r, "path", None) != "/infer"
]


@app.post("/infer")
async def infer(request: Request):
    form = await request.form()
    frames = form.getlist("frames")
    audio = await form["audio"].read()
    assert len(frames) == 16 and len(audio) == 640000
    INFER_CALLS.append(
        {"frames": len(frames), "audioBytes": len(audio), "at": time.time()}
    )
    index = len(INFER_CALLS)
    return {
        "stressScore": 0.35 + (index % 3) * 0.1,
        "confidence": 0.8,
        "concepts": {"voice": 0.42},
        "audioFeatures": {"f0_mean": 130 + (index % 2) * 2, "f0_std": 20},
        "videoFeatures": {"brow_tension": 0.2},
        "quality": {"audioValid": True, "faceDetected": True},
    }


@app.get("/test/state")
def state():
    return {"documents": DOCS, "records": RECORDS, "inferCalls": INFER_CALLS}
