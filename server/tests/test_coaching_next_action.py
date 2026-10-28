import unittest
from copy import deepcopy

from agent.coach_ai import build_context, respond_with_ai, validate_plan
from agent.coaching import CoachRequest, localized_messages
from agent.presentation_guidance import guidance
from server.tests.test_coach_ai import grounded_plan
from server.tests.test_coaching import document


class CoachingNextActionTests(unittest.TestCase):
    def respond(self, doc, action, **kwargs):
        return respond_with_ai(
            doc,
            CoachRequest(sessionId="baseline", action=action, **kwargs),
            generate=grounded_plan,
            verify=lambda _: {"supported": True},
        )

    def test_a_review_question_alone_is_not_an_accepted_coaching_plan(self):
        context = build_context(
            document(), CoachRequest(sessionId="baseline", action="explain_finding")
        )
        plan = grounded_plan(context)
        plan.pop("reviewGuide")
        with self.assertRaisesRegex(ValueError, "two concrete"):
            validate_plan(plan, context)

    def test_first_review_has_concrete_instructions_and_outcome_controls(self):
        doc, response = self.respond(document(), "explain_finding")
        self.assertTrue(
            any(c["type"] == "review_guide" for c in response["components"])
        )
        choices = next(
            c["choices"]
            for c in response["components"]
            if c["type"] == "action_choices"
        )
        self.assertIn("needs_contrast", [c.get("reviewOutcome") for c in choices])
        self.assertIn("needs_phrasing", [c.get("reviewOutcome") for c in choices])
        self.assertEqual(doc["practices"], [])

    def test_review_result_creates_one_matching_ai_exercise_in_the_same_step(self):
        for answer, strategy in [
            ("needs_contrast", "contrast"),
            ("needs_phrasing", "phrasing"),
            ("unsure", "two_versions"),
        ]:
            with self.subTest(answer=answer):
                doc, _ = self.respond(document(), "explain_finding")
                doc, response = self.respond(doc, "submit_review", reviewOutcome=answer)
                self.assertEqual(doc["state"]["stage"], "practice_created")
                self.assertEqual(doc["state"]["reviewOutcome"], answer)
                self.assertEqual(doc["state"]["practiceStrategyId"], strategy)
                self.assertEqual(len(doc["practices"]), 1)
                self.assertEqual(doc["practices"][0]["strategyId"], strategy)
                card = next(
                    c for c in response["components"] if c["type"] == "practice"
                )
                self.assertIn("쉼", card["criterion"])
                self.assertTrue(
                    any(
                        c["action"] == "start_recording"
                        for item in response["components"]
                        if item["type"] == "action_choices"
                        for c in item["choices"]
                    )
                )
                self.assertEqual(len(response["conversationState"]), 10)
                CoachRequest(
                    sessionId="baseline",
                    conversationState=response["conversationState"],
                )
                self.assertNotIn("aiAudit", doc)
                self.assertTrue(doc["snapshot"]["aiAudit"])

    def test_answered_intention_is_not_asked_again_even_if_semantic_checker_approves(
        self,
    ):
        doc, _ = self.respond(document(), "explain_finding")
        doc, response = self.respond(doc, "confirm_intent")
        self.assertEqual(doc["state"]["reviewOutcome"], "intentional")
        self.assertNotIn("의도한 강조", response["message"])
        context = build_context(
            doc, CoachRequest(sessionId="baseline", action="guide_review")
        )
        bad = grounded_plan(context)
        bad["message"] = {
            "ko": "의도한 강조였는지 확인해 보시겠어요?",
            "en": "Could you check whether that was intentional?",
        }
        with self.assertRaisesRegex(ValueError, "already answered"):
            validate_plan(bad, context)
        controls = next(
            c["choices"]
            for c in response["components"]
            if c["type"] == "action_choices"
        )
        self.assertIn("phrasing", [c.get("practiceStrategyId") for c in controls])
        self.assertEqual(doc["practices"], [])

    def test_answered_review_moves_to_optional_methods_without_another_review_guide(
        self,
    ):
        doc, _ = self.respond(document(), "explain_finding")
        doc, _ = self.respond(doc, "confirm_intent")
        doc, response = self.respond(doc, "guide_review")
        self.assertFalse(
            any(c["type"] == "review_guide" for c in response["components"])
        )
        self.assertIn("유지", response["message"])

    def test_paraphrased_observations_outside_fact_tokens_are_rejected(self):
        context = build_context(
            document(), CoachRequest(sessionId="baseline", action="explain_finding")
        )
        plan = grounded_plan(context)
        plan["message"]["ko"] += " 이 구간에서 피치 변화가 두드러졌습니다."
        with self.assertRaisesRegex(ValueError, "restate any observation"):
            validate_plan(plan, context)

    def test_optional_practice_preserves_presenters_intentional_answer(self):
        doc, _ = self.respond(document(), "explain_finding")
        doc, _ = self.respond(doc, "confirm_intent")
        doc, _ = self.respond(doc, "create_practice", practiceStrategyId="phrasing")
        self.assertEqual(doc["state"]["reviewOutcome"], "intentional")
        self.assertEqual(doc["state"]["reviewFeedback"], "intentional")
        self.assertEqual(doc["practices"][-1]["strategyId"], "phrasing")

    def test_legacy_intentional_answer_is_preserved_when_optional_practice_starts(self):
        doc = document()
        doc["state"].update(
            selectedFindingId="pitch_change",
            stage="finding_selected",
            reviewFeedback="intentional",
        )
        doc["state"].pop("reviewOutcome", None)
        doc, response = self.respond(
            doc, "create_practice", practiceStrategyId="phrasing"
        )
        self.assertEqual(response["conversationState"]["reviewOutcome"], "intentional")
        self.assertEqual(doc["state"]["reviewFeedback"], "intentional")
        self.assertEqual(doc["practices"][-1]["reviewOutcome"], "intentional")

    def test_invalid_review_outcome_or_modality_is_rejected_before_model_access(self):
        calls = []
        for kwargs in (
            {"action": "submit_review", "reviewOutcome": "expression_mismatch"},
            {"action": "create_practice", "practiceStrategyId": "gaze_anchor"},
        ):
            with self.assertRaises(ValueError):
                respond_with_ai(
                    document(),
                    CoachRequest(sessionId="baseline", **kwargs),
                    generate=lambda c: calls.append(c),
                    verify=lambda c: {"supported": True},
                )
        self.assertEqual(calls, [])

    def test_language_switch_restores_the_selected_method_without_new_exercise(self):
        doc, _ = self.respond(document(), "explain_finding")
        doc, _ = self.respond(doc, "submit_review", reviewOutcome="needs_phrasing")
        original = deepcopy(doc)
        response = localized_messages(doc, "en")[-1]["response"]
        self.assertEqual(
            response["conversationState"]["practiceStrategyId"], "phrasing"
        )
        self.assertNotRegex(str(response), r"[가-힣]")
        self.assertEqual(doc, original)

    def test_different_modalities_do_not_share_the_same_intention_question(self):
        questions = {
            identity: guidance({"id": identity, "observations": []}, True)["question"]
            for identity in ["pitch_variability", "lip_tension", "brow_tension", "gaze"]
        }
        self.assertEqual(len(set(questions.values())), 4)
        self.assertIn("문장", questions["pitch_variability"])
        self.assertIn("소리", questions["lip_tension"])
        self.assertIn("표정", questions["brow_tension"])
        self.assertIn("시선", questions["gaze"])


if __name__ == "__main__":
    unittest.main()
