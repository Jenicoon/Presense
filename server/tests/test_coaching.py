import unittest
from copy import deepcopy
from pydantic import ValidationError
from agent.coaching import (
    CoachRequest,
    new_document,
    respond,
    compare_snapshots,
    validate_response,
    localized_messages,
)
from agent.report_agent import generate_report
from agent.report_schema import ReviewRequest


def window(n, score=0.3, pitch=100, start=None, **quality):
    start = n * 10000 if start is None else start
    return {
        "segmentId": f"s{n}",
        "startMs": start,
        "endMs": start + 10000,
        "stressScore": score,
        "predictionConfidence": 0.85,
        "concepts": {"voice": pitch / 300},
        "audioFeatures": {"f0_mean": pitch, "f0_std": 20},
        "videoFeatures": {"brow_tension": 0.2},
        "quality": {"audioValid": True, "faceDetected": True, **quality},
    }


def document(identity="baseline", changed=True, context=None):
    request = ReviewRequest(
        sessionId=identity,
        durationMs=60000,
        sceneLabel="Camera",
        practiceContext=context,
        segments=[
            window(0),
            window(1),
            window(2, 0.8, 200 if changed else 100, start=25000),
            window(3, 0.7, 210 if changed else 100, start=35000),
            window(4, 0.6, 205 if changed else 100, start=45000),
        ],
    )
    report = generate_report(request, agent_mode=True, model_version="test-model")
    return new_document(request, report, "test-model")


class CoachingTests(unittest.TestCase):
    def step(self, doc, action, **kwargs):
        return respond(
            doc,
            CoachRequest(sessionId=doc["state"]["sessionId"], action=action, **kwargs),
        )

    def ready(self):
        doc = document()
        self.assertTrue(doc["snapshot"]["report"]["priorities"])
        doc, _ = self.step(doc, "create_practice")
        return doc

    def retry(self, doc):
        p = doc["practices"][-1]
        attempt = document(
            "attempt", context={"sessionId": "baseline", "practiceId": p["id"]}
        )
        # Matching metric moves toward the reference without manufacturing performance labels.
        attempt["snapshot"]["request"]["segments"] = [
            window(n, 0.4, 130) for n in range(3)
        ]
        attempt["snapshot"]["request"]["durationMs"] = 30000
        return attempt

    def test_language_switch_restores_the_same_practice_without_an_extra_transition(self):
        doc = document()
        doc, response = self.step(doc, "create_practice", language="ko")
        original = deepcopy(doc)
        english = localized_messages(doc, "en")
        translated = english[-1]["response"]
        self.assertEqual(translated["conversationState"], response["conversationState"])
        self.assertEqual(translated["revision"], 1)
        self.assertEqual(len(doc["practices"]), 1)
        self.assertEqual(doc, original)
        card = next(c for c in translated["components"] if c["type"] == "practice")
        self.assertEqual(card["practiceId"], doc["state"]["activePracticeId"])
        import re
        self.assertIsNone(re.search(r"[가-힣]", str(english)))
        validate_response(translated, doc)
        bad = deepcopy(translated)
        next(c for c in bad["components"] if c["type"] == "practice")["instruction"] = "Invented exercise"
        with self.assertRaises(ValueError):
            validate_response(bad, doc)
        korean = localized_messages(doc, "ko")
        self.assertIn("연습", korean[-1]["text"])

    def test_english_review_of_korean_report_and_single_routing_call(self):
        doc = document()
        calls = []
        def route(context):
            calls.append(context)
            return {"action": "explain_finding"}
        doc, response = respond(doc, CoachRequest(sessionId="baseline", action="ask", message="Why?", language="en"), route=route)
        self.assertEqual(len(calls), 1)
        import re
        self.assertIsNone(re.search(r"[가-힣]", str(response)))
        self.assertIn("your voice moved higher", response["message"])
        self.assertNotIn("Hz", response["message"])
        self.assertEqual(doc["revision"], 1)

    def test_intentional_expression_is_kept_without_a_corrective_goal(self):
        doc, response = self.step(document(), "explain_finding")
        self.assertIn("문장", response["message"])
        choices = next(c["choices"] for c in response["components"] if c["type"] == "action_choices")
        self.assertIn("confirm_intent", [c["action"] for c in choices])
        doc, response = self.step(doc, "confirm_intent")
        self.assertEqual(doc["state"]["reviewFeedback"], "intentional")
        self.assertEqual(doc["practices"], [])
        doc, _ = self.step(doc, "finish_coaching")
        self.assertIsNone(doc["state"]["nextGoalId"])

    def test_lower_measurements_do_not_automatically_earn_delivery_success(self):
        doc = self.ready()
        task = doc["practices"][-1]
        self.assertIn("1.", task["instruction"])
        self.assertIn("2.", task["instruction"])
        self.assertIn("3.", task["instruction"])
        attempt = self.retry(doc)
        result = compare_snapshots(doc["snapshot"], attempt["snapshot"], task)
        self.assertLess(result["modelScoreChange"], 0)
        self.assertEqual(result["outcome"], "review_required")
        self.assertEqual(result["formula"], "")
        self.assertEqual(result["assessmentSource"], "none")
        with self.assertRaises(ValueError):
            respond(doc, CoachRequest(sessionId="baseline", action="assess_delivery_achieved"), attempt=attempt)

    def test_partial_delivery_review_offers_a_specific_adjustment_and_rejects_another_attempt(self):
        doc = self.ready()
        doc, _ = self.step(doc, "start_recording")
        attempt = self.retry(doc)
        doc, _ = respond(doc, CoachRequest(sessionId="baseline", action="finish_recording"), attempt=attempt)
        other = deepcopy(attempt)
        other["snapshot"]["request"]["sessionId"] = "unrelated"
        with self.assertRaisesRegex(ValueError, "saved practice attempt"):
            respond(doc, CoachRequest(sessionId="baseline", action="assess_delivery_partial"), attempt=other)
        doc, response = respond(doc, CoachRequest(sessionId="baseline", action="assess_delivery_partial"), attempt=attempt)
        self.assertIn("핵심 문장", response["message"])
        self.assertIn("멈추고", response["message"])
        self.assertNotIn("Hz", response["message"])
        result = response["components"][0]["comparison"]
        self.assertEqual(result["outcome"], "partial")
        self.assertEqual(result["assessmentSource"], "presenter")
        doc, _ = self.step(doc, "retry_practice")
        self.assertNotIn("deliveryAssessment", doc["practices"][-1])

    def test_chat_explains_the_score_and_accepts_the_presenters_intention(self):
        doc, response = self.step(document(), "ask", message="이 점수가 왜 필요해?")
        self.assertIn("54 / 100", response["message"])
        self.assertIn("실제 스트레스 70%를 뜻하지", response["message"])
        doc, response = self.step(doc, "ask", message="무엇을 들어야 할지 모르겠어요")
        self.assertEqual(doc["state"]["reviewFeedback"], "unsure")
        doc, response = self.step(doc, "ask", message="That was intentional", language="en")
        self.assertEqual(doc["state"]["reviewFeedback"], "intentional")
        self.assertEqual(doc["practices"], [])

    def test_stable_session_has_no_forced_practice_or_findings(self):
        doc = document(changed=False)
        self.assertEqual(doc["snapshot"]["report"]["priorities"], [])
        doc, response = self.step(doc, "review")
        self.assertIn("반복적으로 확인된 주요 문제", response["message"])
        doc, response = self.step(doc, "create_practice")
        self.assertEqual(doc["practices"], [])

    def test_full_practice_loop_and_restored_state(self):
        doc = document()
        self.assertEqual(doc["messages"], [])
        self.assertNotIn("Hz", doc["snapshot"]["report"]["presenterSummary"]["ko"])
        doc, response = self.step(doc, "review")
        finding = next(
            c["findingId"] for c in response["components"] if c["type"] == "finding"
        )
        doc, response = self.step(doc, "explain_finding", findingId=finding)
        self.assertEqual(doc["state"]["stage"], "finding_selected")
        self.assertTrue(
            any(c["type"] == "video_segment" for c in response["components"])
        )
        doc, response = self.step(doc, "create_practice")
        self.assertEqual(doc["state"]["stage"], "practice_created")
        doc, _ = self.step(doc, "start_recording")
        self.assertEqual(doc["state"]["stage"], "recording")
        doc, _ = self.step(doc, "finish_recording")
        self.assertEqual(doc["state"]["stage"], "evaluating")
        attempt = self.retry(doc)
        doc, response = respond(
            deepcopy(doc),
            CoachRequest(sessionId="baseline", action="finish_recording"),
            attempt=attempt,
        )
        self.assertEqual(doc["state"]["stage"], "comparison_ready")
        self.assertEqual(response["components"][0]["comparison"]["outcome"], "review_required")
        doc, response = respond(doc, CoachRequest(sessionId="baseline", action="assess_delivery_achieved"), attempt=attempt)
        self.assertEqual(response["components"][0]["comparison"]["outcome"], "achieved")
        self.assertEqual(response["components"][0]["comparison"]["assessmentSource"], "presenter")
        doc, _ = self.step(doc, "choose_next_goal", findingId=finding)
        doc, _ = self.step(doc, "finish_coaching")
        self.assertEqual(doc["state"]["nextGoalId"], finding)
        self.assertEqual(doc["state"]["stage"], "completed")
        self.assertTrue(
            doc["messages"][-1]["response"]["conversationState"]["nextGoalId"]
        )

    def test_retry_preserves_original_attempt_and_changes_practice_identity(self):
        doc = self.ready()
        doc, _ = self.step(doc, "start_recording")
        attempt = self.retry(doc)
        doc, _ = respond(
            doc,
            CoachRequest(sessionId="baseline", action="finish_recording"),
            attempt=attempt,
        )
        first = doc["state"]["activePracticeId"]
        doc, _ = self.step(doc, "retry_practice")
        self.assertNotEqual(first, doc["state"]["activePracticeId"])
        self.assertEqual(doc["practices"][0]["attemptSessionId"], "attempt")
        self.assertNotIn("comparison", doc["practices"][1])

    def test_comparison_requires_matched_exercise(self):
        doc = self.ready()
        doc, _ = self.step(doc, "start_recording")
        with self.assertRaisesRegex(ValueError, "belong"):
            respond(
                doc,
                CoachRequest(sessionId="baseline", action="finish_recording"),
                attempt=document("other"),
            )

    def test_unknown_finding_and_action_rejected(self):
        with self.assertRaises(ValueError):
            self.step(document(), "create_practice", findingId="fiction")
        with self.assertRaises(ValidationError):
            CoachRequest(sessionId="x", action="render_html")

    def test_server_validates_component_ranges_and_measurements(self):
        doc = self.ready()
        doc, response = self.step(doc, "explain_finding")
        forged = deepcopy(response)
        card = next(c for c in forged["components"] if c["type"] == "video_segment")
        card["startMs"] = 1234
        with self.assertRaisesRegex(ValueError, "not observed"):
            validate_response(forged, doc)
        doc, _ = self.step(doc, "start_recording")
        attempt = self.retry(doc)
        doc, response = respond(
            doc,
            CoachRequest(sessionId="baseline", action="finish_recording"),
            attempt=attempt,
        )
        response["components"][0]["comparison"]["measurements"][0]["after"] = 999
        with self.assertRaisesRegex(ValueError, "unsupported"):
            validate_response(response, doc, attempt=attempt)

    def test_no_score_for_missing_quality_or_single_independent_window(self):
        doc = self.ready()
        attempt = self.retry(doc)
        p = doc["practices"][-1]
        attempt["snapshot"]["request"]["segments"] = [
            window(n, 0.4, 130, start=n * 1000) for n in range(6)
        ]
        self.assertEqual(
            compare_snapshots(doc["snapshot"], attempt["snapshot"], p)["outcome"],
            "insufficient_data",
        )
        attempt["snapshot"]["request"]["segments"] = [
            window(n, 0.4, 130, audioValid=False, faceDetected=False) for n in range(3)
        ]
        result = compare_snapshots(doc["snapshot"], attempt["snapshot"], p)
        self.assertEqual(result["outcome"], "insufficient_data")
        self.assertIsNone(result["modelScoreChange"])

    def test_version_and_scene_mismatch_never_claim_improvement(self):
        doc = self.ready()
        attempt = self.retry(doc)
        p = doc["practices"][-1]
        for key in ("modelVersion", "metricDefinitionVersion"):
            other = deepcopy(attempt)
            other["snapshot"][key] = "different"
            result = compare_snapshots(doc["snapshot"], other["snapshot"], p)
            self.assertFalse(result["compatible"])
            self.assertEqual(result["measurements"], [])

    def test_overlap_average_preserves_missing_time_and_all_originals(self):
        r = ReviewRequest(
            sessionId="overlap",
            durationMs=30000,
            segments=[
                window(0, 0.2, start=0),
                window(1, 0.8, start=5000),
                window(2, 0.6, start=20000),
            ],
        )
        report = generate_report(r, agent_mode=True)
        self.assertEqual(report["analysis"]["observedMs"], 25000)
        self.assertAlmostEqual(report["analysis"]["averageStress"], 0.54)
        self.assertEqual(len(report["rawSegments"]), 3)
        self.assertEqual(report["analysis"]["timeline"][2]["endMs"], 15000)
        self.assertEqual(report["analysis"]["timeline"][3]["startMs"], 20000)

    def test_previous_session_and_retry_remain_distinct(self):
        doc = self.ready()
        previous = document("older")
        doc, response = respond(
            doc,
            CoachRequest(sessionId="baseline", action="compare_previous_session"),
            previous=previous,
        )
        comparison = response["components"][0]["comparison"]
        self.assertEqual(comparison["previousSessionId"], "older")
        self.assertEqual(comparison["currentSessionId"], "baseline")
        self.assertEqual(comparison["outcome"], "comparable")

    def test_unrecognized_question_does_not_generate_factual_prose(self):
        doc, response = respond(
            document(),
            CoachRequest(sessionId="baseline", message="What did my audience think?"),
            route=lambda _: {"action": "unknown", "message": "Audience loved it"},
        )
        self.assertIn("답할 수 없습니다", response["message"])
        self.assertNotIn("loved", str(response))

    def test_response_for_unknown_components_and_cross_session_is_rejected(self):
        doc, response = self.step(document(), "review")
        response["components"] = [{"type": "html", "html": "<script>"}]
        with self.assertRaises(ValidationError):
            validate_response(response, doc)
        response["components"] = []
        response["conversationState"]["sessionId"] = "someone-else"
        with self.assertRaisesRegex(ValueError, "Cross-session"):
            validate_response(response, doc)

    def test_empty_session_is_an_explicit_gap_without_a_score(self):
        request = ReviewRequest(sessionId="empty", durationMs=30000, segments=[])
        report = generate_report(request, agent_mode=True)
        self.assertIsNone(report["analysis"]["averageStress"])
        self.assertIsNone(report["analysis"]["peakStress"])
        self.assertEqual(report["analysis"]["timeline"], [])
        self.assertEqual(report["analysis"]["coverage"], 0)
        self.assertEqual(report["rawSegments"], [])
        self.assertEqual(report["priorities"], [])

    def test_active_recording_cannot_be_skipped_or_replaced_by_a_new_goal(self):
        doc = self.ready()
        doc, _ = self.step(doc, "start_recording")
        for action in ("choose_next_goal", "finish_coaching", "retry_practice"):
            with self.assertRaises(ValueError):
                self.step(doc, action)
        with self.assertRaisesRegex(ValueError, "identity"):
            respond(doc, CoachRequest(sessionId="another", action="review"))

    def test_overlapping_changed_windows_do_not_fake_independent_repetition(self):
        request = ReviewRequest(
            sessionId="mixed",
            durationMs=60000,
            segments=[
                window(0, pitch=100),
                window(1, pitch=100),
                window(2, 0.8, 200, start=20000),
                window(3, 0.8, 210, start=21000),
                window(4, 0.3, 100, start=40000),
            ],
        )

        def decide(view):
            return (
                {
                    "action": "analyze_segment",
                    "candidateId": "pitch_change",
                    "segmentIds": ["s2", "s3", "s4"],
                }
                if not view["toolResults"]
                else {"action": "finish", "priorityCandidateIds": ["pitch_change"]}
            )

        report = generate_report(request, agent_mode=True, decide=decide)
        self.assertEqual(report["priorities"], [])
        self.assertEqual(
            report["agentRun"]["actions"][0]["result"]["coherentShiftCount"], 0
        )
