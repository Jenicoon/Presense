"""Calibration evidence, immutable session scores and durable local reuse."""
import tempfile
import unittest
from pathlib import Path
from agent.coach_ai import build_context
from agent.coaching import CoachRequest, new_document
from agent.report_agent import generate_report
from agent.report_schema import ReviewRequest
from server.local_calibration_store import LocalCalibrationStore
from server.tests.test_agent_report import segment


class BaselineTests(unittest.TestCase):
    def request(self, version="v1"):
        return ReviewRequest(sessionId="measured",durationMs=30000,
            segments=[segment(str(i),i*10000,(i+1)*10000,value) for i,value in enumerate((.5,.7,.6))],
            personalBaseline=.4,baselineSampleCount=3,baselineModelVersion=version)

    def test_reference_is_used_in_summary_and_agent_context_but_never_subtracted_from_raw_scores(self):
        req=self.request()
        report=generate_report(req,model_version="v1",agent_mode=True)
        self.assertEqual(report["analysis"]["averageStress"],.6)
        self.assertEqual([r["stressScore"] for r in report["rawSegments"]],[.5,.7,.6])
        reference=report["observationReport"]["personalBaseline"]
        self.assertEqual(reference["observedMs"],30000)
        self.assertEqual(reference["averageDifference"],.2)
        self.assertIn("30초",report["presenterSummary"]["ko"])
        self.assertIn("20점",report["summaryText"])
        ctx=build_context(new_document(req,report,"v1"),CoachRequest(sessionId="measured",message="초기값과 비교해줘"))
        self.assertIn("current.baseline",ctx["facts"])
        self.assertIn("40.00/100",ctx["facts"]["current.baseline"]["en"])
        self.assertEqual(ctx["sessionSummaries"]["current"]["analysis"]["personalBaseline"]["score"],.4)

    def test_missing_or_other_model_reference_does_not_fabricate_a_comparison(self):
        changed=generate_report(self.request("old"),model_version="new",agent_mode=True)
        self.assertEqual(changed["baselineComparison"]["status"],"model_mismatch")
        self.assertNotIn("personalBaseline",changed["observationReport"])
        req=ReviewRequest(sessionId="missing",durationMs=10000,segments=[segment("one",0,10000,.5)])
        missing=generate_report(req,model_version="v1",agent_mode=True)
        self.assertEqual(missing["baselineComparison"]["status"],"missing")
        self.assertNotIn("초기 측정",missing["summaryText"])

    def test_saved_reference_survives_reload_and_prompt_does_not_replace_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"reference.json"
            row={"user_id":"local-test","baseline_score":.4,"sample_count":3,"model_version":"v1","calibrated_at":"2026-11-03T00:00:00Z"}
            LocalCalibrationStore(path,"local-test").write(row)
            restored=LocalCalibrationStore(path,"local-test")
            self.assertEqual(restored.read()["baseline_score"],.4)
            restored.prompted("2026-11-03T01:00:00Z")
            self.assertEqual(restored.read()["baseline_score"],.4)
            self.assertEqual(restored.read()["sample_count"],3)
            for bad in ({**row,"sample_count":2},{**row,"baseline_score":float("nan")},{**row,"user_id":"someone-else"}):
                with self.assertRaises(ValueError):restored.write(bad)
