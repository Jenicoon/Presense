"""Saved exercise checks, matched retries and server-calculated delivery results."""
import unittest
from copy import deepcopy
from pydantic import ValidationError
from agent.coaching import CoachRequest, respond, localized_messages, validate_response
from agent.coach_ai import respond_with_ai, build_context
from agent.practice_rubric import CHECKS, checks_for
from server.tests.test_coaching import document, window, delivery_review
from server.tests.test_coach_ai import grounded_plan

class PracticeReviewTests(unittest.TestCase):
    def ready(self, strategy="contrast"):
        doc, _ = respond(document(), CoachRequest(sessionId="baseline", action="create_practice", practiceStrategyId=strategy))
        doc, _ = respond(doc, CoachRequest(sessionId="baseline", action="start_recording"))
        practice = doc["practices"][-1]
        attempt = document("attempt", context={"sessionId": "baseline", "practiceId": practice["id"]})
        attempt["snapshot"]["request"].update(durationMs=30000, segments=[window(n, .15, 120) for n in range(3)])
        doc, response = respond(doc, CoachRequest(sessionId="baseline", action="finish_recording"), attempt=attempt)
        return doc, attempt, response

    def submit(self, doc, attempt, values=None, **conditions):
        return respond_with_ai(doc, CoachRequest(sessionId="baseline", action="submit_practice_review", deliveryReview=delivery_review(doc, attempt, values, **conditions)), attempt=attempt)

    def test_pre_recording_checks_match_ai_strategy_and_survive_language_switch(self):
        doc, response = respond_with_ai(document(), CoachRequest(sessionId="baseline", action="create_practice", practiceStrategyId="phrasing"), generate=grounded_plan, verify=lambda _: {"supported": True})
        card = next(c for c in response["components"] if c["type"] == "practice")
        self.assertEqual(card["successChecks"], [c["label"] for c in checks_for(doc["practices"][-1], True)])
        self.assertIn("의미가 끝나는", card["successChecks"][0])
        before = deepcopy(doc)
        english = localized_messages(doc, "en")[-1]["response"]
        self.assertEqual(next(c for c in english["components"] if c["type"] == "practice")["successChecks"], [c["label"] for c in checks_for(doc["practices"][-1], False)])
        self.assertEqual(doc, before)

    def test_lower_signal_cannot_replace_a_delivery_checklist(self):
        doc, attempt, response = self.ready()
        self.assertLess(response["components"][0]["comparison"]["modelScoreChange"], 0)
        card = next(c for c in response["components"] if c["type"] == "practice_review")
        self.assertEqual(card["checks"], checks_for(doc["practices"][-1], True))
        self.assertEqual(response["components"][0]["comparison"]["outcome"], "review_required")
        with self.assertRaisesRegex(ValueError, "checklist"):
            respond(doc, CoachRequest(sessionId="baseline", action="assess_delivery_achieved"), attempt=attempt)

    def test_outcomes_follow_each_answer_and_not_model_score_direction(self):
        for values, expected in [(["yes", "yes"], "achieved"), (["yes", "partly"], "partial"), (["no", "no"], "retry_recommended"), (["yes", "unavailable"], "insufficient_data")]:
            with self.subTest(values=values):
                doc, attempt, _ = self.ready()
                doc, response = self.submit(doc, attempt, values)
                result = response["components"][0]["comparison"]
                self.assertEqual(result["outcome"], expected)
                self.assertEqual(result["assessmentSource"], "presenter")
                self.assertEqual(result["deliveryReview"]["answers"], delivery_review(doc, attempt, values)["answers"])
                self.assertEqual(result["formula"], "")
                self.assertEqual(response["generation"]["source"], "system")

    def test_changed_or_unknown_conditions_withhold_both_grade_and_deltas(self):
        for condition in ["sameContent", "sameEnvironment"]:
            for value in ["changed", "unknown"]:
                doc, attempt, _ = self.ready()
                doc, response = self.submit(doc, attempt, **{condition: value})
                result = response["components"][0]["comparison"]
                self.assertEqual(result["outcome"], "insufficient_data")
                self.assertIsNone(result["modelScoreChange"])
                self.assertEqual(result["measurements"], [])
                self.assertIn("비교 조건", response["message"])

    def test_feedback_targets_uncompleted_action_and_retry_preserves_criteria(self):
        doc, attempt, _ = self.ready("phrasing")
        doc, response = self.submit(doc, attempt, ["yes", "no"])
        self.assertIn("다음 문장을 새로 시작", response["message"])
        self.assertNotIn("핵심 단어", response["message"])
        facts = build_context(doc, CoachRequest(sessionId="baseline", message="내 연습 결과는?"), attempt=attempt)["facts"]
        self.assertIn("사용자가", facts["practice.delivery_review"]["ko"])
        self.assertIn("부분 달성", facts["practice.delivery_review"]["ko"])
        old = deepcopy(doc["practices"][-1])
        doc, retry_response = respond_with_ai(doc, CoachRequest(sessionId="baseline", action="retry_practice"))
        self.assertIn("다음 문장을 새로 시작", retry_response["message"])
        retry_card = next(c for c in retry_response["components"] if c["type"] == "practice")
        self.assertEqual(retry_card["successChecks"], old["successChecks"])
        new = doc["practices"][-1]
        self.assertNotEqual(new["id"], old["id"])
        self.assertEqual(new["successChecks"], old["successChecks"])
        self.assertNotIn("deliveryReview", new)
        self.assertEqual(doc["practices"][-2]["deliveryReview"], old["deliveryReview"])

    def test_forged_missing_duplicate_and_other_attempt_answers_are_rejected(self):
        doc, attempt, response = self.ready()
        review = delivery_review(doc, attempt)
        for bad in [{**review, "practiceId": "other"}, {**review, "attemptSessionId": "other"}, {**review, "answers": {"imaginary": "yes", "other": "yes"}}]:
            with self.assertRaises(ValueError):
                self.submit_input(doc, attempt, bad)
        with self.assertRaises(ValidationError):
            self.submit_input(doc, attempt, {**review, "answers": {"key_sentence": "yes"}})
        altered = deepcopy(response)
        next(c for c in altered["components"] if c["type"] == "practice_review")["checks"][0]["label"] = "Invented criterion"
        with self.assertRaisesRegex(ValueError, "Unsupported practice review"):
            validate_response(altered, doc, attempt)
        doc, _ = self.submit(doc, attempt)
        with self.assertRaisesRegex(ValueError, "already"):
            self.submit(doc, attempt)

    def submit_input(self, doc, attempt, value):
        return respond(doc, CoachRequest(sessionId="baseline", action="submit_practice_review", deliveryReview=value), attempt=attempt)

    def test_insufficient_metric_coverage_never_allows_achievement_review(self):
        doc, attempt, _ = self.ready()
        for segment in attempt["snapshot"]["request"]["segments"][1:]: segment["audioFeatures"] = {}
        doc["state"]["stage"] = "evaluating"
        doc, response = respond(doc, CoachRequest(sessionId="baseline", action="finish_recording"), attempt=attempt)
        self.assertEqual(response["components"][0]["comparison"]["outcome"], "insufficient_data")
        self.assertFalse(any(c["type"] == "practice_review" for c in response["components"]))
        with self.assertRaisesRegex(ValueError, "Insufficient"): self.submit(doc, attempt)

    def test_each_strategy_has_two_specific_checks_without_sensor_targets(self):
        self.assertEqual(len(CHECKS), 7)
        for strategy in CHECKS:
            checks = checks_for({"strategyId": strategy}, True)
            self.assertEqual(len({c["id"] for c in checks}), 2)
            self.assertNotRegex(str(checks), r"Hz|스트레스.*낮|점수.*낮")

    def test_retry_then_complete_saves_both_attempts_and_the_same_goal(self):
        doc, attempt, _ = self.ready("phrasing")
        doc, _ = self.submit(doc, attempt, ["yes", "partly"])
        first = deepcopy(doc["practices"][-1])
        doc, _ = respond(doc, CoachRequest(sessionId="baseline", action="retry_practice"))
        retry = deepcopy(attempt)
        retry["snapshot"]["request"].update(sessionId="next-attempt", practiceContext={"sessionId":"baseline", "practiceId":doc["state"]["activePracticeId"]})
        doc, response = respond(doc, CoachRequest(sessionId="baseline", action="finish_recording"), attempt=retry)
        card = next(c for c in response["components"] if c["type"] == "practice_review")
        self.assertEqual([c["label"] for c in card["checks"]], first["successChecks"])
        doc, response = self.submit(doc, retry)
        self.assertEqual(response["components"][0]["comparison"]["outcome"], "achieved")
        self.assertEqual(doc["practices"][0], first)
        doc, _ = respond(doc, CoachRequest(sessionId="baseline", action="choose_next_goal", findingId=first["findingId"]))
        doc, _ = respond(doc, CoachRequest(sessionId="baseline", action="finish_coaching"))
        restored = localized_messages(deepcopy(doc), "en")[-1]["response"]
        self.assertEqual(restored["conversationState"]["stage"], "completed")
        self.assertEqual(restored["conversationState"]["nextGoalId"], first["findingId"])
        self.assertEqual(doc["practices"][1]["deliveryReview"]["attemptSessionId"], "next-attempt")
