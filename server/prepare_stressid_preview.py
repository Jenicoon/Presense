"""Analyze one local StressID Speaking video with the real deployed model.

No dataset media or generated fixture is committed or uploaded. Use the produced
manifest with server.local_coaching_preview for the loopback-only UI preview.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

import cv2
import numpy as np

from agent.coaching import new_document
from agent.report_agent import generate_report
from agent.report_schema import ReviewRequest
from server.agent_memory import model_version
from server.inference import get_engine, predict

BASE = "22222222-2222-4222-8222-222222222222"


def prepare(video: Path, output: Path, ffmpeg: str, recorded_at: str | None = None, session_id: str = BASE, calibration_seconds: int = 0):
    output.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError("Cannot open the selected StressID video")
    fps = capture.get(cv2.CAP_PROP_FPS)
    duration_ms = round(capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps * 1000)
    decoded = subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-i",
            str(video),
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
    )
    samples = np.frombuffer(decoded.stdout, dtype="<f4")
    duration_ms = min(duration_ms, len(samples) * 1000 // 16000)
    if calibration_seconds not in (0, 30):
        raise ValueError("Initial measurement must be three separate ten-second windows")
    offset_ms = calibration_seconds * 1000
    if duration_ms - offset_ms < 20000:
        raise ValueError("Keep at least twenty seconds of separate presentation data")
    get_engine()
    rows = []
    baseline_rows = []
    end_times = list(range(10000, offset_ms + 1, 10000)) + list(range(offset_ms + 10000, duration_ms + 1, 5000))
    for end_ms in end_times:
        start_ms = end_ms - 10000
        frames = []
        for frame_no in np.linspace(
            start_ms * fps / 1000, end_ms * fps / 1000 - 1, 16
        ).astype(int):
            capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame_no))
            success, frame = capture.read()
            if not success:
                raise ValueError(
                    "A real frame could not be decoded; no placeholder is substituted"
                )
            frames.append(frame)
        audio = samples[start_ms * 16 : end_ms * 16].copy()
        if len(audio) != 160000:
            raise ValueError("A complete ten-second audio window is required")
        result = predict(np.stack(frames), audio, "Speaking")
        target = baseline_rows if end_ms <= offset_ms else rows
        shift = 0 if end_ms <= offset_ms else offset_ms
        target.append(
            {
                "modelVersion": result["modelVersion"],
                "metricDefinitionVersion": result["metricDefinitionVersion"],
                "conceptDefinitionVersion": result["conceptDefinitionVersion"],
                "segmentId": f"stressid-{start_ms}-{end_ms}",
                "startMs": start_ms - shift,
                "endMs": end_ms - shift,
                "stressScore": result["stressScore"],
                "predictionConfidence": result["confidence"],
                "concepts": result["concepts"],
                "audioFeatures": result["audioFeatures"],
                "videoFeatures": result["videoFeatures"],
                "quality": result["quality"],
            }
        )
        print(
            json.dumps(
                {
                    "startMs": start_ms,
                    "endMs": end_ms,
                    "stressScore": result["stressScore"],
                    "quality": result["quality"],
                }
            ),
            flush=True,
        )
    capture.release()
    calibration = {}
    if offset_ms:
        if len(baseline_rows) != 3 or not all(row["quality"]["audioValid"] and row["quality"]["faceDetected"] for row in baseline_rows):
            raise ValueError("The initial measurement needs three usable independent windows")
        if {row["modelVersion"] for row in baseline_rows + rows} != {model_version()}:
            raise ValueError("Initial measurement and presentation must use the same model")
        calibration = {"personalBaseline": median(row["stressScore"] for row in baseline_rows),
                       "baselineSampleCount": 3, "baselineModelVersion": model_version(),
                       "baselineSource": "dataset_example"}
    request = ReviewRequest(
        sessionId=session_id, durationMs=duration_ms - offset_ms, sceneLabel="Live Camera", segments=rows,
        **calibration,
    )
    report = generate_report(request, agent_mode=True, model_version=model_version())
    report.update(dataOrigin="stressid", coachingAvailable=True)
    doc = new_document(request, report, model_version())
    doc["snapshot"].update(
        recordedAt=recorded_at or datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 compatibility
        dataOrigin="stressid",
    )
    doc["snapshot"]["calibrationEvidence"] = {"segments": baseline_rows, "observedMs": offset_ms, "source": "dataset_example"} if offset_ms else None
    provenance = {
        "dataset": "StressID",
        "sessionOffsetMs": offset_ms,
        "calibrationObservedMs": offset_ms,
        "task": "Speaking",
        "sourceFile": video.name,
        "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "windowMs": 10000,
        "strideMs": 5000,
        "frameCount": 16,
        "audioSampleRate": 16000,
        "inference": "real",
        "modelVersion": model_version(),
    }
    doc["snapshot"]["provenance"] = provenance
    media = output / "stressid-speaking.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-ss",
            str(offset_ms / 1000),
            "-i",
            str(video),
            "-t",
            str((duration_ms - offset_ms) / 1000),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(media),
        ],
        check=True,
    )
    manifest = {"document": doc, "mediaPath": str(media), "provenance": provenance}
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, allow_nan=False)
    )
    print(
        json.dumps(
            {
                "manifest": str(output / "manifest.json"),
                "windowCount": len(rows),
                "distinctScores": len({r["stressScore"] for r in rows}),
                "analysis": report["analysis"],
                "findings": [f["id"] for f in report["priorities"]],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("/private/tmp/presense-stressid")
    )
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--recorded-at", default=None)
    parser.add_argument("--session-id", default=BASE)
    parser.add_argument("--calibration-seconds", type=int, choices=(0, 30), default=0)
    args = parser.parse_args()
    prepare(args.video, args.output, args.ffmpeg, args.recorded_at, args.session_id, args.calibration_seconds)
