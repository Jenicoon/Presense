"""Grounding contracts for LLM-authored coaching. No external calls."""

import unittest
from copy import deepcopy

from agent.coach_ai import AIUnavailable, build_context, respond_with_ai, validate_plan
from agent.coaching import CoachRequest
from server.tests.test_coaching import document


def grounded_plan(context):
    action = context["request"]["action"]
    finding = context["request"].get("findingId") or context["state"].get(
        "selectedFindingId"
    )
    finding = finding or next((f["id"] for f in context["findings"]), None)
    key = f"finding.{finding}" if finding else "current.summary"
    plan = {
        "action": "explain_finding" if action == "ask" else action,
        "findingId": finding,
        "evidenceIds": [key],
        "message": {
            "ko": "{{evidence:"
            + key
            + "}} 이 변화가 의도한 강조였는지 먼저 확인해 보세요.",
            "en": "{{evidence:"
            + key
            + "}} First check whether this change was intentional emphasis.",
        },
        "videoRefs": [next(iter(context["videoRefs"]))] if context["videoRefs"] else [],
        "followUps": [],
        "practice": None,
    }
    if action == "create_practice" and finding:
        plan["practice"] = {
            "label": {
                "ko": "선택한 문장을 나눠 말하기",
                "en": "Rehearse a sentence in phrases",
            },
            "steps": [
                {
                    "ko": "영상에서 다시 말할 문장을 직접 골라 주세요.",
                    "en": "Choose a sentence from your recording yourself.",
                },
                {
                    "ko": "의미 단위 사이에 멈추며 같은 내용을 다시 말해 보세요.",
                    "en": "Repeat the same content with a pause between meaningful phrases.",
                },
            ],
            "durationSeconds": 30,
        }
    return plan


class CoachAIContractTests(unittest.TestCase):
    def setUp(self):
        self.doc = document()
        self.request = CoachRequest(sessionId="baseline", action="explain_finding")
        self.context = build_context(self.doc, self.request)

    def test_context_contains_all_window_summary_quality_and_no_credentials(self):
        ctx = self.context
        self.assertEqual(ctx["sessionSummaries"]["current"]["windowCount"], 5)
        self.assertEqual(
            ctx["sessionSummaries"]["current"]["analysis"]["observedMs"], 50000
        )
        self.assertIn("finding.pitch_change", ctx["facts"])
        self.assertIn("current.window0.audio0", ctx["facts"])
        self.assertNotIn("api_key", str(ctx).lower())
        self.assertNotIn("recommendation", ctx)
        self.assertEqual(self.doc["messages"], [])

    def test_valid_plan_uses_existing_facts_and_video_references(self):
        plan = validate_plan(grounded_plan(self.context), self.context)
        self.assertEqual(plan.findingId, "pitch_change")

    def test_invented_evidence_time_number_component_markup_and_finding_rejected(self):
        for field, value in [
            ("evidenceIds", ["made_up"]),
            ("videoRefs", ["current.window999"]),
            ("findingId", "nonexistent"),
            ("action", "start_recording"),
            (
                "message",
                {"ko": "스트레스가 90%입니다.", "en": "Your actual stress is 90%."},
            ),
            ("message", {"ko": "<script>내용</script>", "en": "<script>bad</script>"}),
        ]:
            plan = grounded_plan(self.context)
            plan[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_plan(plan, self.context)

    def test_no_forced_exercise_without_a_supported_finding(self):
        context = build_context(
            document(changed=False),
            CoachRequest(sessionId="baseline", action="create_practice"),
        )
        plan = grounded_plan(context)
        other = deepcopy(plan)
        other["practice"] = grounded_plan(
            build_context(
                self.doc, CoachRequest(sessionId="baseline", action="create_practice")
            )
        )["practice"]
        with self.assertRaises(ValueError):
            validate_plan(other, context)
        self.assertIsNone(validate_plan(plan, context).practice)

    def test_semantic_checker_cannot_approve_unmeasured_delivery_claim(self):
        plan = grounded_plan(self.context)
        plan["message"]["ko"] += " 전달이 어려웠을 수 있어요."
        with self.assertRaisesRegex(ValueError, "Unmeasured delivery"):
            validate_plan(plan, self.context)

    def test_unsafe_choice_label_uses_the_server_label_without_changing_action(self):
        def generate(context):
            plan = grounded_plan(context)
            plan["followUps"] = [
                {
                    "action": "create_practice",
                    "label": {"ko": "영상 99:99", "en": "Video <script>99:99</script>"},
                }
            ]
            return plan

        updated, response = respond_with_ai(
            self.doc,
            self.request,
            generate=generate,
            verify=lambda c: {"supported": True},
        )
        choice = next(
            c for c in response["components"] if c["type"] == "action_choices"
        )["choices"][0]
        self.assertEqual(choice["action"], "create_practice")
        self.assertNotIn("99:99", choice["label"])
        self.assertEqual(updated["revision"], 1)

    def test_model_cannot_change_explicit_selection(self):
        context = build_context(
            self.doc, self.request.model_copy(update={"findingId": "pitch_change"})
        )
        plan = grounded_plan(context)
        plan["findingId"] = None
        with self.assertRaises(ValueError):
            validate_plan(plan, context)

    def test_missing_ai_does_not_mutate_or_create_template_coaching(self):
        original = deepcopy(self.doc)
        with self.assertRaises(AIUnavailable):
            respond_with_ai(self.doc, self.request)
        self.assertEqual(self.doc, original)

    def test_injected_ai_authors_one_exercise_and_restores_both_languages(self):
        from agent.coaching import localized_messages, validate_response

        request = self.request.model_copy(update={"action": "create_practice"})
        calls = []

        def generate(context):
            calls.append(context)
            return grounded_plan(context)

        updated, response = respond_with_ai(
            self.doc, request, generate=generate, verify=lambda c: {"supported": True}
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(response["generation"]["source"], "ai")
        self.assertEqual(updated["revision"], 1)
        self.assertEqual(len(updated["practices"]), 1)
        self.assertEqual(updated["practices"][0]["authoredBy"], "ai")
        self.assertIn("문장을 나눠", updated["practices"][0]["label"])
        self.assertEqual(updated["messages"][-1]["text"], response["message"])
        translated = localized_messages(updated, "en")[-1]["response"]
        self.assertNotRegex(str(translated), r"[가-힣]")
        self.assertEqual(
            translated["conversationState"]["activePracticeId"],
            response["conversationState"]["activePracticeId"],
        )
        validate_response(translated, updated)
        self.assertEqual(self.doc["revision"], 0)

    def test_rejected_semantic_claims_and_provider_failure_never_commit(self):
        original = deepcopy(self.doc)
        for verifier in (
            lambda c: {"supported": False, "reason": "invented cause"},
            lambda c: {},
        ):
            with self.assertRaises(AIUnavailable):
                respond_with_ai(
                    self.doc, self.request, generate=grounded_plan, verify=verifier
                )
            self.assertEqual(self.doc, original)

        def broken(context):
            raise TimeoutError("provider unavailable")

        with self.assertRaises(AIUnavailable):
            respond_with_ai(
                self.doc,
                self.request,
                generate=broken,
                verify=lambda c: {"supported": True},
            )
        self.assertEqual(self.doc, original)

    def test_invalid_user_interval_is_rejected_before_any_model_access(self):
        calls = []
        with self.assertRaises(ValueError):
            respond_with_ai(
                self.doc,
                self.request.model_copy(update={"findingId": "fake"}),
                generate=lambda c: calls.append(c),
                verify=lambda c: {"supported": True},
            )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
