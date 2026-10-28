import unittest
from copy import deepcopy

from agent.coach_ai import respond_with_ai
from agent.coaching import (
    CoachRequest,
    localized_messages,
    new_document,
    validate_response,
)
from agent.finding_evidence import complete_document_evidence
from agent.report_agent import generate_report
from agent.report_schema import ReviewRequest
from server.tests.test_coach_ai import grounded_plan
from server.tests.test_coaching import window


def four_observations():
    request = ReviewRequest(
        sessionId="four",
        durationMs=60000,
        segments=[window(n, pitch=100 if n < 2 else 200 + n) for n in range(6)],
    )
    report = generate_report(request, agent_mode=True, model_version="test-model")
    return new_document(request, report, "test-model")


class FindingEvidenceTests(unittest.TestCase):
    def test_report_keeps_every_independent_observation(self):
        finding = four_observations()["snapshot"]["report"]["priorities"][0]
        self.assertEqual(finding["independentObservations"], 4)
        self.assertEqual(len(finding["observations"]), 4)
        self.assertEqual(
            [o["startMs"] for o in finding["observations"]],
            [20000, 30000, 40000, 50000],
        )
        self.assertEqual(len(finding["selectedSegmentIds"]), 4)

    def test_legacy_truncation_is_recovered_from_exact_saved_action_ids(self):
        doc = four_observations()
        f = doc["snapshot"]["report"]["priorities"][0]
        f["observations"] = f["observations"][:3]
        f.pop("selectedSegmentIds")
        original = deepcopy(doc)
        recovered = complete_document_evidence(doc)
        found = recovered["snapshot"]["report"]["priorities"][0]
        self.assertEqual(len(found["observations"]), 4)
        self.assertEqual(found["observations"][-1]["startMs"], 50000)
        self.assertTrue(found["observationEvidenceComplete"])
        self.assertEqual(doc, original)
        self.assertEqual(recovered["state"], doc["state"])
        self.assertEqual(recovered["revision"], doc["revision"])

    def test_merged_range_does_not_invent_unselected_observations(self):
        doc = four_observations()
        f = doc["snapshot"]["report"]["priorities"][0]
        f["selectedSegmentIds"] = ["s2", "s4"]
        f["independentObservations"] = 2
        result = complete_document_evidence(doc)["snapshot"]["report"]["priorities"][0]
        self.assertEqual([o["segmentId"] for o in result["observations"]], ["s2", "s4"])

    def test_missing_original_evidence_is_disclosed_not_recreated(self):
        doc = four_observations()
        doc["snapshot"]["request"]["segments"] = doc["snapshot"]["request"]["segments"][
            :-1
        ]
        result = complete_document_evidence(doc)["snapshot"]["report"]["priorities"][0]
        self.assertEqual(len(result["observations"]), 3)
        self.assertFalse(result["observationEvidenceComplete"])

    def test_ai_representative_card_cannot_hide_the_four_supporting_intervals(self):
        doc = four_observations()
        updated, response = respond_with_ai(
            doc,
            CoachRequest(sessionId="four", action="explain_finding"),
            generate=grounded_plan,
            verify=lambda _: {"supported": True},
        )
        cards = [
            c
            for c in response["components"]
            if c["type"] == "video_segment" and c.get("findingId") == "pitch_change"
        ]
        self.assertEqual([c["startMs"] for c in cards], [20000, 30000, 40000, 50000])
        # Omitting or duplicating an actual supporting interval fails server validation.
        for bad_cards in (cards[:-1], cards + cards[:1]):
            bad = deepcopy(response)
            bad["components"] = bad_cards
            with self.assertRaisesRegex(ValueError, "omitted or duplicated"):
                validate_response(bad, updated)

    def test_restore_adds_missing_cards_without_rewriting_ai_text_or_advancing_state(
        self,
    ):
        doc = four_observations()
        doc, response = respond_with_ai(
            doc,
            CoachRequest(sessionId="four", action="explain_finding"),
            generate=grounded_plan,
            verify=lambda _: {"supported": True},
        )
        saved = doc["messages"][-1]
        saved["translations"]["ko"]["response"]["components"] = [
            c for c in response["components"] if c["type"] != "video_segment"
        ] + [next(c for c in response["components"] if c["type"] == "video_segment")]
        original = deepcopy(doc)
        restored = localized_messages(doc, "ko")[-1]
        self.assertEqual(restored["text"], saved["text"])
        self.assertEqual(
            sum(
                c["type"] == "video_segment" and c.get("findingId") == "pitch_change"
                for c in restored["response"]["components"]
            ),
            4,
        )
        self.assertEqual(doc, original)


if __name__ == "__main__":
    unittest.main()
