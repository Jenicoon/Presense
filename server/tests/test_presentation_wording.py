"""Presenter copy describes the measured quantity without inferring speech quality."""

import unittest
from copy import deepcopy

from agent.coach_ai import build_context, respond_with_ai, validate_plan
from agent.coaching import CoachRequest
from agent.coaching_methods import prepare_review_request
from agent.presentation_guidance import guidance
from server.tests.test_coach_ai import grounded_plan
from server.tests.test_coaching import document


def mouth(value=0.203, reference=0.137):
    return {
        "id": "lip_tension",
        "metric": "lip_tension",
        "referenceValue": reference,
        "independentObservations": 8,
        "observations": [
            {"startMs": 20000, "endMs": 30000, "value": value},
            {"startMs": 30000, "endMs": 40000, "value": 0.155},
        ],
    }


class PresentationWordingTests(unittest.TestCase):
    def test_mouth_copy_explains_direction_and_uses_available_clip_count(self):
        for value, word, english in [
            (0.203, "컸어요", "more open"),
            (0.1, "작았어요", "less open"),
            (0.137, "비슷했어요", "similar"),
        ]:
            with self.subTest(value=value):
                view = guidance(mouth(value), True)
                self.assertIn("입이 벌어진 정도", view["observation"])
                self.assertIn(word, view["observation"])
                self.assertIn("00:20–00:30", view["observation"])
                self.assertIn("영상은 2곳", view["observation"])
                self.assertNotRegex(
                    view["observation"], r"구간 차이|겹치지|긴장|8곳|0\.203"
                )
                self.assertIn(english, guidance(mouth(value), False)["observation"])

    def test_missing_or_invalid_reference_does_not_invent_a_direction(self):
        for reference in (None, float("nan"), float("inf")):
            text = guidance(mouth(reference=reference), True)["observation"]
            self.assertIn("비교할 자료가 부족", text)
            self.assertNotRegex(text, "컸어요|작았어요|비슷했어요")
        finding = mouth()
        finding["observations"] = []
        self.assertIn(
            "상세 관측 자료가 없습니다", guidance(finding, True)["observation"]
        )
        self.assertNotIn("곳", guidance(finding, True)["observation"])

    def test_mouth_guidance_distinguishes_shape_from_pronunciation_and_next_action(
        self,
    ):
        view = guidance(mouth(), True)
        self.assertIn("입 모양만으로", view["question"])
        self.assertIn("소리와 함께", view["question"])
        self.assertIn("지금 방식을 유지", view["question"])
        self.assertIn("그 문장만 짧게 나눠 연습", view["question"])
        self.assertNotRegex(view["observation"], "발음이|불명확|나쁜|개선|향상")

    def test_other_measurements_explain_what_increased_or_decreased(self):
        finding = mouth(0.058, 0.106)
        finding["id"] = "brow_tension"
        self.assertIn("덜 내려간", guidance(finding, True)["observation"])
        finding.update(id="pitch_variability", referenceValue=28.9)
        finding["observations"][0]["value"] = 56.5
        self.assertIn(
            "변화 폭이 앞부분보다 컸어요", guidance(finding, True)["observation"]
        )

    def test_mouth_coach_cannot_revert_to_a_generic_intention_question(self):
        doc = document()
        finding = doc["snapshot"]["report"]["priorities"][0]
        finding.update(
            id="lip_tension",
            metric="lip_tension",
            modality="video",
            referenceValue=0.137,
        )
        finding["observations"][0]["value"] = 0.203
        context = build_context(
            doc,
            CoachRequest(
                sessionId="baseline", action="explain_finding", findingId="lip_tension"
            ),
        )
        for addition, reason in [
            (
                "입술의 움직임이 의도된 것인지 확인해 보세요.",
                "mouth movement was intentional",
            ),
            ("이 구간에서 입이 더욱 벌어졌어요.", "repeat the mouth-opening"),
            (
                "침착함을 유지하고 있는지 판단해 보세요.",
                "Mouth opening does not measure",
            ),
        ]:
            with self.subTest(addition=addition):
                plan = grounded_plan(context)
                plan["message"]["ko"] = "{{evidence:finding.lip_tension}} " + addition
                with self.assertRaisesRegex(ValueError, reason):
                    validate_plan(plan, context)

    def test_model_schema_is_limited_to_the_actual_button_and_saved_references(self):
        seen = []

        def generate(context):
            seen.append(context)
            return grounded_plan(context)

        respond_with_ai(
            document(),
            CoachRequest(
                sessionId="baseline", action="explain_finding", findingId="pitch_change"
            ),
            generate=generate,
            verify=lambda _: {"supported": True},
        )
        context = seen[0]
        properties = context["responseSchema"]["properties"]
        self.assertEqual(properties["action"]["enum"], ["explain_finding"])
        self.assertEqual(properties["findingId"]["const"], "pitch_change")
        self.assertEqual(
            properties["videoRefs"]["items"]["enum"], list(context["videoRefs"])
        )
        self.assertEqual(
            properties["evidenceIds"]["items"]["enum"], list(context["facts"])
        )

    def test_direct_finding_review_does_not_inherit_another_findings_conversation(self):
        doc = document()
        old = doc["snapshot"]["report"]["priorities"][0]
        finding = deepcopy(old)
        finding.update(
            id="lip_tension",
            metric="lip_tension",
            modality="video",
            referenceValue=0.137,
        )
        doc["snapshot"]["report"]["priorities"].append(finding)
        doc["messages"] = [
            {
                "role": "agent",
                "text": "old goal",
                "response": {"conversationState": {"selectedFindingId": old["id"]}},
            }
        ]
        context = build_context(
            doc,
            CoachRequest(
                sessionId="baseline", action="explain_finding", findingId="lip_tension"
            ),
        )
        self.assertEqual([f["id"] for f in context["findings"]], ["lip_tension"])
        self.assertEqual(context["history"], [])
        self.assertNotIn("finding." + old["id"], context["facts"])
        broad = build_context(
            doc,
            CoachRequest(
                sessionId="baseline", action="ask", message="Compare my findings"
            ),
        )
        self.assertEqual(len(broad["findings"]), 2)
        self.assertEqual(len(broad["history"]), 1)
        doc["state"].update(
            selectedFindingId=old["id"],
            stage="practice_created",
            activePracticeId="saved-practice",
            reviewOutcome="intentional",
            reviewFeedback="intentional",
        )
        doc["practices"] = [{"id": "saved-practice"}]
        updated, _ = prepare_review_request(
            doc,
            CoachRequest(
                sessionId="baseline", action="explain_finding", findingId="lip_tension"
            ),
        )
        self.assertEqual(updated["state"]["stage"], "finding_selected")
        self.assertIsNone(updated["state"]["activePracticeId"])
        self.assertIsNone(updated["state"]["reviewOutcome"])
        self.assertEqual(updated["practices"], doc["practices"])

    def test_actual_ai_fact_catalog_receives_the_same_plain_language(self):
        doc = document()
        finding = doc["snapshot"]["report"]["priorities"][0]
        finding.update(
            id="lip_tension",
            metric="lip_tension",
            modality="video",
            referenceValue=0.137,
        )
        finding["observations"][0]["value"] = 0.203
        context = build_context(
            doc,
            CoachRequest(
                sessionId="baseline", action="explain_finding", findingId="lip_tension"
            ),
        )
        fact = context["facts"]["finding.lip_tension"]
        self.assertIn("입이 벌어진 정도가 앞부분보다 컸어요", fact["ko"])
        self.assertIn("more open", fact["en"])
        self.assertNotIn("구간 차이", fact["ko"])


if __name__ == "__main__":
    unittest.main()
