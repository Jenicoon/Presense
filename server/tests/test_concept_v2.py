"""Exact measure identity, state compatibility and conservative coaching contracts."""

import os
import unittest
from copy import deepcopy
from pathlib import Path

from pydantic import ValidationError

from agent.coach_ai import build_context, validate_plan
from agent.coaching import CoachRequest, compare_snapshots, new_document
from agent.coaching_methods import METHODS, profile
from agent.model_contract import (
    CONCEPT_VERSION,
    METRIC_VERSION,
    RAW_METRICS,
    bundle_version,
    load_bundle,
)
from agent.presentation_guidance import guidance
from agent.report_agent import _eligible_evidence, generate_report
from agent.report_schema import Evidence, ReviewRequest
from agent.session_analyzer import analyze_session
from ai.concept_registry import PROPOSED_CONCEPTS_V2
from server.tests.test_coach_ai import grounded_plan

ROOT = Path(__file__).resolve().parents[2]


def request():
    windows = []
    for n in range(6):
        audio = {
            key: (20 if key == "egemap_f0_semitone" else 0.02)
            for mod, key, _, _ in RAW_METRICS
            if mod == "audio"
        }
        video = {
            key: (0.1 if n < 2 else 0.3)
            for mod, key, _, _ in RAW_METRICS
            if mod == "video"
        }
        windows.append(
            {
                "segmentId": str(n),
                "startMs": n * 10000,
                "endMs": (n + 1) * 10000,
                "stressScore": 0.5,
                "predictionConfidence": 0.8,
                "audioFeatures": audio,
                "videoFeatures": video,
                "concepts": {c.model_name_ko: 0.4 for c in PROPOSED_CONCEPTS_V2},
                "quality": {"audioValid": True, "faceDetected": True},
                "modelVersion": "exact7-v2-test",
                "metricDefinitionVersion": METRIC_VERSION,
                "conceptDefinitionVersion": CONCEPT_VERSION,
            }
        )
    return ReviewRequest(
        sessionId="v2", durationMs=60000, sceneLabel="camera", segments=windows
    )


class ConceptV2Contracts(unittest.TestCase):
    def test_versions_flow_from_windows_and_cannot_be_mixed_or_relabelled(self):
        req = request()
        self.assertEqual(req.metricDefinitionVersion, METRIC_VERSION)
        self.assertEqual(req.modelVersion, "exact7-v2-test")
        for mutate in ("old_model", "missing_version", "old_names", "old_definition"):
            data = req.model_dump()
            if mutate == "old_model":
                data["segments"][0]["modelVersion"] = "old"
            elif mutate == "missing_version":
                data["segments"][0]["modelVersion"] = None
            elif mutate == "old_names":
                data["segments"][0]["concepts"] = {"입술 긴장도": 0.4}
            else:
                data["metricDefinitionVersion"] = "session-analysis-v4"
            with self.subTest(mutate=mutate), self.assertRaises(ValidationError):
                ReviewRequest.model_validate(data)

    def test_candidates_use_seven_actual_measurements_not_auxiliary_predictions(self):
        req = request()
        summary, candidates = analyze_session(req)
        self.assertEqual({c["id"] for c in candidates}, {r[2] for r in RAW_METRICS})
        self.assertTrue(all(c["modality"] != "concept" for c in candidates))
        self.assertEqual(summary["observedMs"], 60000)
        report = generate_report(req, model_version=req.modelVersion, agent_mode=True)
        self.assertEqual(report["metricDefinitionVersion"], METRIC_VERSION)
        self.assertEqual(report["conceptDefinitionVersion"], CONCEPT_VERSION)
        self.assertTrue({f["id"] for f in report["priorities"]}.issubset({c[2] for c in RAW_METRICS}))

    def test_stable_v2_session_does_not_invent_a_problem(self):
        data = request().model_dump()
        for row in data["segments"]:
            row["videoFeatures"] = {
                key: 0.1 for mod, key, _, _ in RAW_METRICS if mod == "video"
            }
        req = ReviewRequest.model_validate(data)
        report = generate_report(req, model_version=req.modelVersion, agent_mode=True)
        self.assertEqual(report["priorities"], [])

    def test_one_provider_json_fence_can_discard_rationale_but_not_a_second_object(
        self,
    ):
        from agent.report_agent import _parse_json_object

        self.assertEqual(
            _parse_json_object(
                '```json\n{"supported":true}\n```\nExplanation: supported by supplied facts.'
            ),
            {"supported": True},
        )
        with self.assertRaises(ValueError):
            _parse_json_object('```json\n{"supported":true}\n```\n{"supported":false}')

    def test_provider_verifier_uses_fresh_synthetic_data_and_refuses_private_payloads(
        self,
    ):
        import json
        from tempfile import TemporaryDirectory

        from server.verify_concept_v2_ai import SyntheticAudit, synthetic_request

        first, second = synthetic_request(), synthetic_request()
        self.assertNotEqual(first.sessionId, second.sessionId)
        self.assertEqual(first.sceneLabel, "synthetic_test")
        for row in first.segments:
            self.assertEqual(len(row.audioFeatures) + len(row.videoFeatures), 7)
            self.assertEqual(row.concepts, {})
        with TemporaryDirectory() as parent:
            audit = SyntheticAudit(Path(parent) / "audit", [first.sessionId])

            def payload(context):
                return {
                    "messages": [{"content": "test"}, {"content": json.dumps(context)}]
                }

            audit.validate(
                payload({"dataOrigin": "synthetic", "sessionId": first.sessionId})
            )
            for extra in (
                {"dataOrigin": "stressid"},
                {"sessionId": "existing-session"},
                {"email": "private@example.test"},
                {"mediaPath": "/tmp/video.mp4"},
                {"source": "participant.pdf"},
            ):
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    audit.validate(payload({"dataOrigin": "synthetic", **extra}))

    def test_old_and_new_definitions_cannot_produce_a_comparison_score(self):
        req = request()
        report = generate_report(req, model_version=req.modelVersion, agent_mode=True)
        current = new_document(req, report, req.modelVersion)["snapshot"]
        old = deepcopy(current)
        old["modelVersion"] = "legacy"
        old["metricDefinitionVersion"] = "session-analysis-v4"
        old["conceptDefinitionVersion"] = "legacy-seven-v1"
        result = compare_snapshots(old, current)
        self.assertFalse(result["compatible"])
        self.assertIsNone(result["modelScoreChange"])
        self.assertEqual(result["measurements"], [])
        matched = compare_snapshots(current, deepcopy(current))
        self.assertTrue(matched["compatible"])
        self.assertEqual(matched["modelScoreChange"], 0)

    def test_jaw_practice_is_phrasing_and_eyes_use_a_comfortable_reset(self):
        self.assertEqual(
            profile({"id": "v2_jaw_open"})["strategies"], ["phrasing", "two_versions"]
        )
        self.assertEqual(profile({"id": "v2_eye_squint"})["strategies"], ["face_reset"])
        for identity in (
            "v2_jaw_open",
            "v2_eye_squint",
            "v2_jitter",
            "v2_shimmer",
            "v2_hnr",
        ):
            view = guidance(
                {
                    "id": identity,
                    "referenceValue": 0.1,
                    "observations": [{"startMs": 20000, "endMs": 30000, "value": 0.2}],
                },
                True,
            )
            self.assertNotIn("구간 차이", view["observation"])
            self.assertNotIn("의도한 강조", view["question"])
        self.assertIn(
            "문장의 경계",
            guidance({"id": "v2_jaw_open", "observations": []}, True)["question"],
        )

    def test_every_v2_concept_has_a_safe_practice_path(self):
        for concept in PROPOSED_CONCEPTS_V2:
            strategies = profile({"id": concept.research_topic})["strategies"]
            self.assertTrue(strategies, concept.research_topic)
            self.assertTrue(all(strategy in METHODS for strategy in strategies))
        eye_text = str(METHODS["face_reset"]) + str(
            guidance({"id": "v2_eye_squint", "observations": []}, True)
        )
        self.assertNotRegex(eye_text, r"깜박|깜빡|blink")
        self.assertIn("렌즈", eye_text)

    def test_model_plan_rejects_cause_claims_and_prescribed_jaw_reduction(self):
        req = request()
        report = generate_report(req, model_version=req.modelVersion, agent_mode=True)
        doc = new_document(req, report, req.modelVersion)
        finding = (
            next(f for f in report["priorities"] if f["id"] == "v2_jaw_open")
            if any(f["id"] == "v2_jaw_open" for f in report["priorities"])
            else deepcopy(report["priorities"][0])
        )
        finding.update(id="v2_jaw_open", metric="jaw_open", modality="video")
        doc["snapshot"]["report"]["priorities"] = [finding]
        ctx = build_context(
            doc,
            CoachRequest(
                sessionId="v2", action="explain_finding", findingId="v2_jaw_open"
            ),
        )
        for ko in (
            "턱 움직임 때문에 스트레스 점수가 높습니다.",
            "턱을 덜 열고 말해 보세요.",
        ):
            plan = grounded_plan(ctx)
            plan["message"]["ko"] = "{{evidence:finding.v2_jaw_open}} " + ko
            with self.assertRaises(ValueError):
                validate_plan(plan, ctx)

    def test_v2_practice_renders_checked_task_fields_and_rejects_forced_eye_reduction(
        self,
    ):
        req = request()
        report = generate_report(req, model_version=req.modelVersion, agent_mode=True)
        finding = deepcopy(report["priorities"][0])
        finding.update(id="v2_eye_squint", metric="eye_squint", modality="video")
        report["priorities"] = [finding]
        doc = new_document(req, report, req.modelVersion)
        ctx = build_context(
            doc,
            CoachRequest(
                sessionId="v2", action="create_practice", findingId="v2_eye_squint"
            ),
        )
        plan = grounded_plan(ctx)
        plan["message"] = {
            "ko": "불필요한 관측 설명",
            "en": "Unnecessary observation prose",
        }
        checked = validate_plan(plan, ctx)
        self.assertIn(checked.practice.label.ko, checked.message.ko)
        self.assertNotIn("불필요한", checked.message.ko)
        plan["practice"]["successCheck"]["ko"] = "눈꺼풀 움직임을 줄이세요."
        with self.assertRaises(ValueError):
            validate_plan(plan, ctx)

    def test_video_research_topics_keep_exact_movement_evidence(self):
        for topic, text in [
            ("v2_brow_down", "browDown AU4"),
            ("v2_eye_squint", "eyeSquint AU7 eyelid tightener"),
            ("v2_jaw_open", "jawOpen AU26 jaw opening"),
        ]:
            hit = Evidence(
                id="paper",
                source="paper.pdf",
                page=1,
                chunk=0,
                text=text,
                distance=0.1,
                topics=[topic],
                applicability="related",
            )
            self.assertTrue(_eligible_evidence(topic, hit))
            self.assertFalse(_eligible_evidence("pitch_change", hit))

    def test_packaged_identity_contains_both_weights_and_training_bounds(self):
        manifest = load_bundle(ROOT / "weights/concept_v2")
        self.assertEqual(
            manifest["conceptNames"], [c.model_name_ko for c in PROPOSED_CONCEPTS_V2]
        )
        self.assertEqual(len(manifest["scaling"]["p2"]), 7)
        other = deepcopy(manifest)
        other["files"]["head.pt"] = "other-head"
        self.assertNotEqual(bundle_version(manifest), bundle_version(other))
        other = deepcopy(manifest)
        other["files"]["student.pt"] = "other-student"
        self.assertNotEqual(bundle_version(manifest), bundle_version(other))


@unittest.skipUnless(
    os.getenv("PRESENSE_V2_SOURCE_ROOT"),
    "Set PRESENSE_V2_SOURCE_ROOT to run frozen participant integration",
)
class FrozenConceptV2Runtime(unittest.TestCase):
    def test_full_runtime_reproduces_frozen_97_of_121_and_all_seven_r2(self):
        from server.verify_concept_v2 import verify

        result = verify(
            Path(os.environ["PRESENSE_V2_SOURCE_ROOT"]), ROOT / "weights/concept_v2"
        )
        self.assertEqual(result["correct"], 97)
        self.assertEqual(result["total"], 121)
        self.assertAlmostEqual(result["meanConceptR2"], 0.804670, places=5)
        self.assertLess(result["maxBaseLogitError"], 1e-5)

    def test_candidate_formula_and_strict_student_structure(self):
        import torch

        from agent.concept_v2 import ConceptModelV2, ResidualConceptHeadV2

        model = ResidualConceptHeadV2().eval()
        with torch.no_grad():
            for p in model.parameters():
                p.zero_()
            model.concept_classifier[-1].bias.copy_(torch.tensor([2.0, -2.0]))
            logits, _ = model(torch.zeros(1, 320), torch.tensor([[1.0, -1.0]]))
        torch.testing.assert_close(logits, torch.tensor([[1.06, -1.06]]))
        student = torch.load(
            ROOT / "weights/concept_v2/student.pt",
            map_location="cpu",
            weights_only=False,
        )["model_state_dict"]
        head = torch.load(
            ROOT / "weights/concept_v2/head.pt", map_location="cpu", weights_only=False
        )["state_dict"]
        student["geo_gru.attn_score.weight"] = student.pop("geo_gru.pool.score.weight")
        with self.assertRaises(RuntimeError):
            ConceptModelV2(student, head)
