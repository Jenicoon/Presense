"""Verify one real local ten-second window through HTTP /infer; no LLM calls."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


def verify(video: Path, ffmpeg: str, start_ms: int):
    if os.getenv("PRESENSE_MODEL_VARIANT") != "concept-v2":
        raise ValueError("Explicitly select concept-v2")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from fastapi.testclient import TestClient

    from ai.concept_registry import PROPOSED_CONCEPTS_V2
    from server import app as module

    frames = []
    capture = cv2.VideoCapture(str(video))
    for ms in np.linspace(start_ms, start_ms + 9999, 16):
        capture.set(cv2.CAP_PROP_POS_MSEC, float(ms))
        ok, frame = capture.read()
        if not ok:
            raise ValueError("Missing real frame")
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            raise ValueError("Frame encode failed")
        frames.append(("frames", ("frame.jpg", encoded.tobytes(), "image/jpeg")))
    capture.release()
    audio = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-ss",
            str(start_ms / 1000),
            "-i",
            str(video),
            "-t",
            "10",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "f32le",
            "pipe:1",
        ],
        capture_output=True,
        check=True,
    ).stdout
    assert len(audio) == 160000 * 4
    module.app.dependency_overrides[module.require_authenticated_user] = lambda: {
        "sub": "local-live-test"
    }
    try:
        with TestClient(module.app) as client:
            response = client.post(
                "/infer",
                files=frames
                + [("audio", ("capture.f32", audio, "application/octet-stream"))],
                data={"task": "Speaking"},
            )
            assert response.status_code == 200, response.text
            result = response.json()
        assert result["modelVersion"].startswith("exact7-v2-")
        assert result["metricDefinitionVersion"] == "session-analysis-v5-exact7"
        assert list(result["concepts"]) == [
            c.model_name_ko for c in PROPOSED_CONCEPTS_V2
        ]
        assert len(result["audioFeatures"]) == 4
        assert all(
            k in result["videoFeatures"]
            for k in ("brow_down", "eye_squint", "jaw_open")
        )
        assert result["gateWeights"] is None
        return {
            "capture": {
                "audioSamples": 160000,
                "frames": 16,
                "startMs": start_ms,
                "endMs": start_ms + 10000,
            },
            "response": result,
        }
    finally:
        module.app.dependency_overrides.pop(module.require_authenticated_user, None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--start-ms", default=20000, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.video, args.ffmpeg, args.start_ms)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
