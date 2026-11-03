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

    def test_coaching_requires_authentication(self):
        self.assertEqual(self.client.post("/agent/coach",json={"sessionId":"s1","action":"review"}).status_code,401)
        self.assertEqual(self.client.get("/agent/coach/s1").status_code,401)

    def test_coaching_restores_and_rejects_stale_actions_and_invented_ids(self):
        from server.tests.test_coaching import document
        from copy import deepcopy
        doc=document("s1")
        class Store:
            def get(self,identity): return deepcopy(doc) if identity=="s1" else None
            def previous(self,_):return []
            def save(self,identity,new,revision):doc.clear();doc.update(new)
        self.module.app.dependency_overrides[self.module.require_authenticated_user]=lambda:{"sub":"user-1"}
        try:
            from server.tests.test_coach_ai import grounded_plan
            with patch.object(self.module,"_coach_store",return_value=Store()), patch.object(self.module,"luxia_api_key","test-configured"), patch.object(self.module,"_generate_coaching", side_effect=grounded_plan), patch.object(self.module,"_verify_coaching",return_value={"supported":True}):
                restored=self.client.get("/agent/coach/s1");self.assertEqual(restored.status_code,200)
                self.assertEqual(restored.json()["revision"],0)
                self.assertEqual(self.client.get("/agent/coach/another-user").status_code,404)
                result=self.client.post("/agent/coach",json={"sessionId":"s1","action":"review","revision":0})
                self.assertEqual(result.status_code,200);self.assertTrue(result.json()["components"])
                english = self.client.get("/agent/coach/s1?language=en")
                self.assertEqual(english.status_code, 200)
                self.assertNotRegex(str(english.json()["messages"]), r"[가-힣]")
                self.assertEqual(english.json()["revision"], 1)
                self.assertEqual(self.client.get("/agent/coach/s1?language=xx").status_code, 422)
                self.assertEqual(self.client.post("/agent/coach",json={"sessionId":"s1","action":"review","revision":0}).status_code,409)
                self.assertEqual(self.client.post("/agent/chat",json={"sessionId":"s1","action":"create_practice","findingId":"made-up"}).status_code,422)
                self.assertEqual(self.client.post("/agent/coach",json={"sessionId":"s1","action":"render_html"}).status_code,422)
        finally:self.module.app.dependency_overrides.clear()

    def test_ai_coaching_failure_preserves_state_and_reports_unavailability(self):
        from server.tests.test_coaching import document
        from copy import deepcopy
        doc = document("ai-failure")
        original = deepcopy(doc)
        class Store:
            def get(self, identity): return deepcopy(doc)
            def previous(self, identity): return []
            def save(self, *args): raise AssertionError("Failed AI reply must not be saved")
        self.module.app.dependency_overrides[self.module.require_authenticated_user] = lambda: {"sub": "user-1"}
        try:
            with patch.object(self.module, "_coach_store", return_value=Store()), patch.object(self.module, "luxia_api_key", ""):
                response = self.client.post("/agent/coach", json={"sessionId": "ai-failure", "action": "review"})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["detail"]["code"], "coach_ai_unavailable")
            self.assertEqual(doc, original)
        finally:
            self.module.app.dependency_overrides.clear()

    def test_new_report_receives_the_previously_selected_goal_and_outcome(self):
        from server.tests.test_coaching import document
        previous=document("previous");previous["state"]["nextGoalId"]="pitch_change"
        previous["practices"]=[{"comparison":{"outcome":"partial"}}]
        class Store:
            def previous(self,_):return [previous]
            def create(self,_,doc):return doc
        self.module.app.dependency_overrides[self.module.require_authenticated_user]=lambda:{"sub":"user-1"}
        try:
            with patch.object(self.module,"_coach_store",return_value=Store()), patch.object(self.module,"model_version",return_value="test-model"),patch.object(self.module,"luxia_api_key",""):
                response=self.client.post("/agent/report",json=self.payload)
                self.assertEqual(response.status_code,200)
                report=response.json();self.assertEqual(report["previousCoaching"]["goalLabel"],previous["snapshot"]["report"]["priorities"][0]["label"])
                self.assertEqual(report["previousCoaching"]["lastOutcome"],"partial")
        finally:self.module.app.dependency_overrides.clear()

    def test_dataset_initial_measurement_never_uses_external_ai(self):
        self.module.app.dependency_overrides[self.module.require_authenticated_user] = lambda: {"sub": "test"}
        payload = {**self.payload, "personalBaseline": .3, "baselineSampleCount": 3,
                   "baselineModelVersion": "test-model", "baselineSource": "dataset_example"}
        try:
            with patch.object(self.module, "luxia_api_key", "configured"), patch.object(self.module, "generate_report", wraps=self.module.generate_report) as generate:
                response = self.client.post("/agent/report", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(generate.call_args.kwargs["synthesize"])
            self.assertIsNone(generate.call_args.kwargs["decide"])
        finally:
            self.module.app.dependency_overrides.clear()

    def test_authenticated_report_accepts_personal_baseline_fields(self):
        self.module.app.dependency_overrides[self.module.require_authenticated_user] = lambda: {"sub": "test"}
        payload = {**self.payload, "personalBaseline": .3, "baselineSampleCount": 3,
                   "baselineModelVersion": "test-model"}
        try:
            with patch.object(self.module, "model_version", return_value="test-model"):
                response = self.client.post("/agent/report", json=payload)
            self.assertEqual(response.status_code, 200)
            baseline = response.json()["observationReport"]["personalBaseline"]
            self.assertEqual(baseline["sampleCount"], 3)
            self.assertEqual(baseline["peakDifference"], .5)
        finally:
            self.module.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
