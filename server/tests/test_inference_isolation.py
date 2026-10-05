"""Check web request isolation without loading or downloading model weights."""

import importlib.util
import sys
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import numpy as np

from agent.decision_agent import run_agent
from agent.report_schema import ReviewRequest
from agent.session_analyzer import analyze_session


class FakeEngine:
    model = object()

    def __init__(self):
        self.task = None
        self.session_log = []
        self.fail_next = False
        self.outputs = []

    def set_task(self, task):
        self.task = task

    def predict(self, video, audio, *, record_session=True):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Failed inference")
        time.sleep(0.005)
        if record_session:
            self.session_log.append(video.copy())
        return self.outputs.pop(0) if self.outputs else (0.4, [0.5, 0.5], self.task, {}, {}, {})


class InferenceIsolationTests(unittest.TestCase):
    def setUp(self):
        stub = types.ModuleType("model_wrapper")
        stub.StressInferenceEngine = FakeEngine
        spec = importlib.util.spec_from_file_location(
            "isolated_inference", Path(__file__).resolve().parents[1] / "inference.py"
        )
        self.api = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"model_wrapper": stub}):
            spec.loader.exec_module(self.api)
        self.engine = FakeEngine()
        self.api._engine = self.engine
        self.video = np.zeros((16, 2, 2, 3), dtype=np.uint8)
        self.audio = np.zeros(160, dtype=np.float32)

    def test_repeated_sessions_do_not_retain_frames(self):
        for task in ["Speaking", "Interview"] * 10:
            result = self.api.predict(self.video, self.audio, task)
            self.assertEqual(result["dominantModality"], task)
        self.assertEqual(self.engine.session_log, [])

    def test_concurrent_requests_keep_their_own_task(self):
        tasks = [f"task-{i}" for i in range(24)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda task: self.api.predict(self.video, self.audio, task), tasks
            ))
        self.assertEqual([r["dominantModality"] for r in results], tasks)
        self.assertEqual(self.engine.session_log, [])

    def test_failed_request_releases_lock_for_next_session(self):
        self.engine.fail_next = True
        with self.assertRaises(RuntimeError):
            self.api.predict(self.video, self.audio, "failed")
        result = self.api.predict(self.video, self.audio, "next")
        self.assertEqual(result["dominantModality"], "next")
        self.assertEqual(self.engine.session_log, [])

    def test_model_adapter_output_reaches_agent_candidate_schema(self):
        scores = [.30, .32, .34, .82, .84]
        pitches = [120, 122, 124, 169, 165]
        self.engine.outputs = [
            (score, [.5, .5], "Speaking",
             {"f0_mean": pitch, "f0_std": 24, "voiced_ratio": .72},
             {"face_detected": True, "brow_tension": .1, "lip_tension": .3,
              "eye_contact_score": .8},
             {"음성 피치": .2 if index < 3 else .6})
            for index, (score, pitch) in enumerate(zip(scores, pitches))]
        segments = []
        for index in range(5):
            frame = self.api.predict(self.video, np.ones(160000, dtype=np.float32) * .01)
            segments.append({
                "segmentId": f"capture-{index}", "startMs": index * 10000,
                "endMs": (index + 1) * 10000,
                "stressScore": frame["stressScore"],
                "predictionConfidence": frame["confidence"],
                "concepts": frame["concepts"],
                "audioFeatures": frame["audioFeatures"],
                "videoFeatures": frame["videoFeatures"],
                "quality": frame["quality"],
            })
        request = ReviewRequest(sessionId="adapter-session", durationMs=50000,
                                sceneLabel="camera", segments=segments)
        summary, candidates = analyze_session(request)
        pitch = next(item for item in candidates if item["id"] == "pitch_change")
        self.assertEqual(pitch["metric"], "f0_mean")
        self.assertEqual(pitch["measurementQuality"], 1)
        # The catalogue exposes all five windows; the Agent chooses an interval later.
        self.assertEqual(pitch["independentObservations"], 5)
        def decide(view):
            return ({"action": "analyze_segment", "candidateId": "pitch_change"}
                    if not view["toolResults"] else
                    {"action": "finish", "priorityCandidateIds": []})
        state = run_agent(request, summary, candidates, decide=decide)
        self.assertEqual(state.actions[0]["result"]["observedValue"], 165.0)


if __name__ == "__main__":
    unittest.main()
