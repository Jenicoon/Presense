"""Exercise the report HTTP boundary without loading model weights."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class ReportEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2 = types.ModuleType("cv2")
        inference = types.ModuleType("inference")
        inference.get_engine = lambda: None
        inference.health = lambda: {"checkpointLoaded": False}
        inference.predict = lambda *_: {}
        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location("report_endpoint_app", root / "server" / "app.py")
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"cv2": cv2, "inference": inference}):
            spec.loader.exec_module(cls.module)
        cls.module._report_rag = lambda: None
        cls.client = TestClient(cls.module.app)
        cls.payload = {"sessionId": "s1", "durationMs": 10000, "language": "ko", "source": "live",
                       "segments": [{"segmentId": "one", "startMs": 0, "endMs": 10000,
                                     "stressScore": .8, "concepts": {}, "audioFeatures": {},
                                     "videoFeatures": {}, "quality": {"audioValid": True, "faceDetected": False}}]}

    def test_auth_required(self):
        response = self.client.post("/agent/report", json=self.payload)
        self.assertEqual(response.status_code, 401)

    def test_authenticated_report_and_invalid_interval(self):
        self.module.app.dependency_overrides[self.module.require_authenticated_user] = lambda: {"sub": "test"}
        try:
            response = self.client.post("/agent/report", json=self.payload)
            self.assertEqual(response.status_code, 200)
            report = response.json()
            self.assertEqual(report["analysis"]["observedMs"], 10000)
            self.assertNotIn("stages", report)
            bad = {**self.payload, "segments": [{**self.payload["segments"][0], "endMs": 11000}]}
            self.assertEqual(self.client.post("/agent/report", json=bad).status_code, 422)
        finally:
            self.module.app.dependency_overrides.clear()

    def test_authenticated_report_passes_previous_memory_to_agent(self):
        self.module.app.dependency_overrides[self.module.require_authenticated_user] = lambda: {"sub": "user-1"}
        prior = {"sessionId": "previous", "modelVersion": "same-model"}
        try:
            with patch.object(self.module, "load_recent_memory", return_value=prior) as load, \
                    patch.object(self.module, "generate_report", return_value={"sessionId": "s1"}) as generate:
                response = self.client.post("/agent/report", json=self.payload,
                                            headers={"Authorization": "Bearer user-token"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(load.call_args.args[-1], "user-1")
            self.assertEqual(generate.call_args.kwargs["prior_memory"], prior)
            self.assertTrue(generate.call_args.kwargs["agent_mode"])
        finally:
            self.module.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
