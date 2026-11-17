"""Useful next decisions use saved repeated reviews, without adding product steps."""
import json
import unittest
from copy import deepcopy
from agent.coaching import CoachRequest, respond, localized_messages, validate_response
from agent.coach_ai import respond_with_ai
from agent.coaching_next_step import build_decision, validate_decision, recommend_next
from server.tests.test_coaching import document, delivery_review
from server.tests import test_practice_review as review_tests


def select(context, identity):
    option = next(o for o in context["options"] if o["id"] == identity)
    evidence = option["requiredEvidence"]
    tokens = " ".join("{{fact:" + key + "}}" for key in evidence)
    return {"optionId": identity, "reason": {"ko": tokens + " 이번에는 다른 방법을 선택해 같은 목표를 연습해 보세요.",
            "en": tokens + " Try another supported method for the same goal this time."}, "evidenceIds": evidence}


class NextCoachingStepTests(unittest.TestCase):
    def first(self):
        doc, attempt, _ = review_tests.PracticeReviewTests().ready("contrast")
        doc["snapshot"]["dataOrigin"] = "synthetic"
        return doc, attempt

    def second(self):
        doc, attempt = self.first()
        doc, _ = respond_with_ai(doc, CoachRequest(sessionId="baseline", action="submit_practice_review", deliveryReview=delivery_review(doc, attempt, ["yes", "partly"])), attempt=attempt)
        doc, _ = respond_with_ai(doc, CoachRequest(sessionId="baseline", action="retry_practice"))
        attempt = deepcopy(attempt)
        attempt["snapshot"]["request"].update(sessionId="retry-2", practiceContext={"sessionId":"baseline", "practiceId":doc["state"]["activePracticeId"]})
        doc, _ = respond(doc, CoachRequest(sessionId="baseline", action="finish_recording"), attempt=attempt)
        return doc, attempt

    def submit(self, doc, attempt, answers=None, generate=None, verify=None, **conditions):
        return respond_with_ai(doc, CoachRequest(sessionId="baseline", action="submit_practice_review",
            deliveryReview=delivery_review(doc, attempt, answers or ["yes", "partly"], **conditions)),
            attempt=attempt, generate=generate, verify=verify)

    def test_one_incomplete_take_keeps_the_method_without_an_extra_ai_call(self):
        doc, attempt = self.first()
        def forbidden(_): raise AssertionError("No decision needed yet")
        doc, response = self.submit(doc, attempt, generate=forbidden, verify=forbidden)
        option = doc["practices"][-1]["nextStep"]["option"]
        self.assertEqual(option["id"], "repeat")
        self.assertEqual(response["generation"]["source"], "system")
        self.assertEqual(response["generation"]["dataOrigin"], "synthetic")
        self.assertTrue(next(c for c in response["components"] if c["type"] == "action_choices")["choices"][0]["recommended"])

    def test_repeated_check_allows_ai_to_choose_an_actual_other_method_and_uses_that_choice(self):
        doc, attempt = self.second()
        calls = []
        def generate(context):
            calls.append(context)
            self.assertIn("review.repeated", context["facts"])
            return select(context, "try_phrasing")
        doc, response = self.submit(doc, attempt, generate=generate, verify=lambda _: {"supported":True})
        self.assertEqual(len(calls), 1)
        self.assertEqual(response["generation"]["source"], "ai")
        choice = next(c for c in response["components"] if c["type"] == "action_choices")["choices"][0]
        self.assertEqual(choice["action"], "create_practice")
        self.assertEqual(choice["practiceStrategyId"], "phrasing")
        before = deepcopy(doc["practices"])
        doc, response = respond(doc, CoachRequest(sessionId="baseline", action=choice["action"], findingId=choice["findingId"], practiceStrategyId=choice["practiceStrategyId"]))
        self.assertEqual(doc["state"]["practiceStrategyId"], "phrasing")
        self.assertEqual(doc["practices"][:-1], before)
        self.assertIn("의미가 끝나는", doc["practices"][-1]["successChecks"][0])

    def test_different_unresolved_checks_do_not_claim_repetition(self):
        doc, attempt = self.second()
        doc, _ = self.submit(doc, attempt, ["partly", "yes"])
        context = build_decision(doc)
        self.assertEqual([o["id"] for o in context["options"]], ["repeat"])
        self.assertNotIn("review.repeated", context["facts"])

    def test_changed_conditions_and_uncertain_answers_never_trigger_a_method_change(self):
        for conditions in [{"sameEnvironment":"changed"}, {"sameContent":"unknown"}]:
            doc, attempt = self.second()
            doc, response = self.submit(doc, attempt, generate=lambda _:self.fail("No AI call for insufficient data"), **conditions)
            self.assertEqual(doc["practices"][-1]["nextStep"]["option"]["id"], "recapture")
            self.assertEqual(response["components"][0]["comparison"]["outcome"], "insufficient_data")

    def test_ai_failure_does_not_lose_the_submitted_review_or_fake_a_recommendation(self):
        for generate, verify in [(lambda _: (_ for _ in ()).throw(RuntimeError("offline")), lambda _: {"supported":True}),
                                 (lambda c: select(c,"try_phrasing"), lambda _: {"supported":False})]:
            doc, attempt = self.second()
            old = deepcopy(doc)
            doc, response = self.submit(doc, attempt, generate=generate, verify=verify)
            self.assertEqual(doc["revision"], old["revision"] + 1)
            self.assertEqual(doc["practices"][-1]["comparison"]["outcome"], "partial")
            self.assertEqual(doc["practices"][-1]["nextStep"]["status"], "unavailable")
            self.assertEqual(response["generation"]["source"], "system")
            self.assertFalse(any(c.get("recommended") for item in response["components"] if item["type"] == "action_choices" for c in item["choices"]))

    def test_recovery_and_language_restore_use_saved_decision_without_another_provider_call(self):
        doc, attempt = self.second()
        doc, response = self.submit(doc, attempt, generate=lambda c:select(c,"try_two_versions"), verify=lambda _: {"supported":True})
        original = deepcopy(doc)
        en = localized_messages(doc,"en")[-1]["response"]
        self.assertEqual(doc,original)
        self.assertEqual(en["conversationState"],response["conversationState"])
        self.assertNotRegex(en["message"],r"[가-힣]")
        def forbidden(_):raise AssertionError("Decision is already saved")
        doc, response = recommend_next(doc, response, "ko", attempt=attempt, generate=forbidden, verify=forbidden)
        self.assertEqual(doc["practices"][-1]["nextStep"], original["practices"][-1]["nextStep"])
        self.assertEqual(response["generation"]["source"],"ai")

    def test_hallucinated_options_missing_evidence_numbers_and_forged_buttons_are_rejected(self):
        doc, attempt = self.second()
        doc, response = self.submit(doc, attempt)
        ctx = build_decision(doc)
        good = select(ctx,"try_phrasing")
        for bad in [{**good,"optionId":"try_gaze_anchor"}, {**good,"evidenceIds":["made_up"]},
                    {**good,"reason":{"ko":"점수가 30점 낮아졌습니다.","en":"Your score dropped by 30 points."}}]:
            with self.assertRaises(ValueError):validate_decision(bad,ctx)
        doc, response = recommend_next(doc,response,"ko",generate=lambda c:good,verify=lambda _: {"supported":True},attempt=attempt)
        forged=deepcopy(response)
        choice=next(c for c in forged["components"] if c["type"] == "action_choices")["choices"][0]
        choice["practiceStrategyId"]="gaze_anchor"
        with self.assertRaises(ValueError):validate_response(forged,doc,attempt)
        raw=json.dumps(ctx,ensure_ascii=False)
        for private in ["baseline", "retry-2", "sessionId", "practiceId", "email", "mediaPath"]:
            self.assertNotIn(private,raw)

    def test_achieved_goal_can_finish_without_forcing_an_unobserved_next_goal(self):
        doc, attempt = self.first()
        doc, response = self.submit(doc,attempt,["yes","yes"])
        self.assertEqual(doc["practices"][-1]["nextStep"]["option"]["id"],"finish")
        self.assertEqual(response["generation"]["source"],"system")

    def test_achieved_goal_lets_ai_pick_only_an_existing_unreviewed_focus(self):
        from server.tests.test_concept_v2 import request as v2_request
        from agent.report_agent import generate_report
        from agent.coaching import new_document
        req = v2_request()
        req.sessionId = "baseline"
        report = generate_report(req, model_version=req.modelVersion, agent_mode=True)
        doc = new_document(req, report, req.modelVersion)
        doc["snapshot"]["dataOrigin"] = "synthetic"
        doc, _ = respond(doc, CoachRequest(sessionId="baseline", action="create_practice", practiceStrategyId="two_versions"))
        doc, _ = respond(doc, CoachRequest(sessionId="baseline", action="start_recording"))
        from agent.report_schema import ReviewRequest
        retry = ReviewRequest.model_validate({**req.model_dump(), "sessionId":"take", "practiceContext":{"sessionId":"baseline", "practiceId":doc["state"]["activePracticeId"]}})
        attempt = new_document(retry, generate_report(retry, model_version=retry.modelVersion, agent_mode=True), retry.modelVersion)
        doc, _ = respond(doc, CoachRequest(sessionId="baseline", action="finish_recording"), attempt=attempt)
        chosen = []
        def generate(context):
            option = next(o for o in context["options"] if o["id"].startswith("next_"))
            chosen.append(option)
            result = select(context, option["id"])
            tokens = " ".join("{{fact:" + key + "}}" for key in option["requiredEvidence"])
            result["reason"] = {"ko":tokens + " 다음 목표를 함께 확인해 보세요.", "en":tokens + " Review the next supported focus together."}
            return result
        doc, response = self.submit(doc, attempt, ["yes","yes"], generate=generate, verify=lambda _: {"supported":True})
        self.assertNotEqual(chosen[0]["findingId"],doc["practices"][-1]["findingId"])
        self.assertIn(chosen[0]["findingId"],{f["id"] for f in report["priorities"]})
        self.assertEqual(chosen[0]["action"],"explain_finding")
        doc, response = respond(doc, CoachRequest(sessionId="baseline",action="explain_finding",findingId=chosen[0]["findingId"]))
        self.assertEqual(doc["state"]["selectedFindingId"],chosen[0]["findingId"])
        self.assertTrue(any(c["type"] == "video_segment" for c in response["components"]))

    def test_existing_recording_review_updates_only_answers_and_preserves_history(self):
        from agent.practice_rubric import checks_for
        doc, attempt, _ = review_tests.PracticeReviewTests().ready("two_versions")
        doc, _ = self.submit(doc, attempt, ["yes","no"], generate=lambda c:select(c,"review_existing"), verify=lambda _: {"supported":True})
        original = deepcopy(doc["practices"][-1]["deliveryReview"])
        measurements = deepcopy(attempt["snapshot"])
        ctx = build_decision(doc)
        self.assertIn("review_existing", {o["id"] for o in ctx["options"]})
        with self.assertRaisesRegex(ValueError,"already"):
            self.submit(doc,attempt,["yes","yes"])
        doc, response = respond_with_ai(doc,CoachRequest(sessionId="baseline",action="compare_attempts"),attempt=attempt)
        card = next(c for c in response["components"] if c["type"] == "practice_review")
        self.assertEqual(card["review"],original)
        self.assertTrue(any(c["type"] == "video_segment" for c in response["components"]))
        doc, response = self.submit(doc,attempt,["yes","yes"])
        self.assertEqual(doc["practices"][-1]["comparison"]["outcome"],"achieved")
        self.assertEqual(doc["practices"][-1]["reviewHistory"][0]["review"],original)
        self.assertEqual(doc["practices"][-1]["reviewHistory"][0]["nextStep"]["option"]["id"],"review_existing")
        from agent.coach_ai import build_context
        facts=build_context(doc,CoachRequest(sessionId="baseline",message="왜 다시 확인하라고 했어?"),attempt=attempt)["facts"]
        self.assertIn("수정하기 전",facts["practice.previous_next_step"]["ko"])
        self.assertEqual(attempt["snapshot"],measurements)
        self.assertEqual(len(doc["practices"]),1)

    def test_dataset_examples_never_send_next_step_context_to_a_provider(self):
        doc,attempt = self.second()
        doc["snapshot"]["dataOrigin"]="stressid"
        doc,response=self.submit(doc,attempt,generate=lambda _:self.fail("Dataset egress"),verify=lambda _:self.fail("Dataset egress"))
        self.assertEqual(doc["practices"][-1]["nextStep"]["status"],"unavailable")
        self.assertEqual(response["generation"]["dataOrigin"],"stressid")
