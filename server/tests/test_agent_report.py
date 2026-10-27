"""Behavioral tests for overlap accounting and verifiable research citations."""
import json
import unittest
from unittest.mock import patch
from pydantic import ValidationError

from agent.build_demo_report import sample_request
from agent.decision_agent import run_agent
from agent.report_agent import _parse_json_object, _parse_luxia_content, generate_report
from agent.report_schema import ReviewRequest
from agent.session_analyzer import analyze_session, describe_observations


def segment(identity, start, end, stress, *, audio=True, face=True, pitch=100, brow=.1, confidence=None):
    return {
        "segmentId": identity, "startMs": start, "endMs": end,
        "stressScore": stress, "concepts": {"음성 피치": .4},
        "predictionConfidence": confidence,
        "audioFeatures": {"f0_mean": pitch, "f0_std": 25},
        "videoFeatures": {"brow_tension": brow, "lip_tension": .3, "eye_contact_score": .8},
        "quality": {"audioValid": audio, "faceDetected": face},
    }


class FakeRag:
    def retrieve_evidence(self, query, k=3):
        return [{"id": "paper:1:0", "source": "paper.pdf", "page": 1,
                 "chunk": 0, "text": "Brow lowering (AU04) was measured during the speaking task.", "distance": .2,
                 "findingKo": "말하기 과제에서 눈썹 내림 움직임을 측정했습니다."}]


class AgentReportTests(unittest.TestCase):
    def test_fenced_luxia_action_json_is_accepted_without_free_text(self):
        self.assertEqual(_parse_json_object('```json\n{"action":"finish","priorityCandidateIds":[]}\n```'),
                         {"action": "finish", "priorityCandidateIds": []})
        with self.assertRaises(ValueError):
            _parse_json_object('The answer is {"action":"finish"}')

    def request(self, segments, duration=40000):
        return ReviewRequest(sessionId="session-1", durationMs=duration, source="live", segments=segments)

    def report(self, request, *, selected=("brow_tension",), **kwargs):
        """Isolate report verification from the Agent's feature selection."""
        summary, observations = analyze_session(request)
        chosen = [item for item in observations if item["id"] in selected]
        with patch("agent.report_agent.analyze_session", return_value=(summary, chosen)):
            return generate_report(request, **kwargs)

    def test_luxia_summary_text_wrapper_is_normalized(self):
        result = _parse_luxia_content(json.dumps({
            "summary": {"text": "Review 00:30–00:40."}, "coaching": []}))
        self.assertEqual(result.summary, "Review 00:30–00:40.")

    def test_extra_retrieved_citations_are_bounded_before_schema_validation(self):
        result = _parse_luxia_content(json.dumps({
            "summary": "Review 00:30–00:40.",
            "coaching": [{"issueId": "brow_tension", "recommendation": "Review the recording.",
                          "evidenceIds": ["one", "two", "three", "four"]}],
        }))
        self.assertEqual(result.coaching[0].evidenceIds, ["one", "two", "three"])

    def test_overlap_is_counted_once_and_missing_time_is_not_zero(self):
        request = self.request([
            segment("a", 0, 10000, .8),
            segment("b", 5000, 15000, .6),
        ])
        summary, _ = analyze_session(request)
        self.assertEqual(summary["observedMs"], 15000)
        self.assertNotIn("highStressThreshold", summary)
        self.assertEqual([row["stressScore"] for row in summary["timeline"]], [.8, .7, .6])
        self.assertEqual(summary["coverage"], .375)
        self.assertAlmostEqual(summary["averageStress"], .7)

    def test_invalid_channels_do_not_create_issues_or_coverage(self):
        request = self.request([segment("missing", 0, 10000, .9, audio=False, face=False, pitch=400, brow=.9)])
        summary, candidates = analyze_session(request)
        self.assertEqual(summary["observedMs"], 0)
        self.assertEqual(candidates, [])

    def test_report_describes_session_phases_and_peak_concepts(self):
        windows = [segment("opening", 0, 10000, .2),
                   segment("middle", 10000, 20000, .7, pitch=160),
                   segment("closing", 20000, 30000, .4)]
        windows[1]["concepts"]["음성 피치"] = .8
        request = self.request(windows, duration=30000)
        summary, _ = analyze_session(request)
        observed = describe_observations(request, summary)
        self.assertEqual([row["averageStressScore"] for row in observed["phaseSummaries"]],
                         [.2, .7, .4])
        self.assertEqual(observed["peakConcepts"][0]["name"], "음성 피치")
        self.assertEqual(observed["peakConcepts"][0]["value"], .8)
        self.assertEqual(observed["peakConcepts"][0]["comparisonValue"], .4)

    def test_summary_connects_peak_phase_feature_and_concept(self):
        windows = [segment("opening", 0, 10000, .2),
                   segment("middle", 10000, 20000, .7, pitch=160),
                   segment("closing", 20000, 30000, .4)]
        windows[1]["concepts"]["음성 피치"] = .8
        report = generate_report(self.request(windows, duration=30000), agent_mode=True,
                                 decide=lambda _: {"action": "finish", "priorityCandidateIds": []})
        text = report["summaryText"]
        self.assertIn("00:10–00:20", text)
        self.assertIn("70/100", text)
        self.assertIn("중반 평균", text)
        self.assertIn("평균 목소리 높이 160.00 Hz", text)
        self.assertIn("Concept 출력 ‘목소리 높이 패턴’ 값은 0.80", text)
        self.assertNotIn("긴장이 발견", text)

    def test_observation_report_omits_invalid_channel_values(self):
        request = self.request([
            segment("valid", 0, 10000, .6, pitch=130, brow=.2),
            segment("audio-only", 10000, 20000, .8, face=False, pitch=150, brow=.9),
            segment("invalid", 20000, 30000, .95, audio=False, face=False, pitch=400, brow=.9),
        ])
        report = generate_report(request, agent_mode=True, decide=lambda _: {"action": "finish", "priorityCandidateIds": []})
        observed = report["observationReport"]
        self.assertEqual(observed["peakSegment"]["segmentId"], "audio-only")
        self.assertEqual(observed["observedMs"], 20000)
        self.assertEqual(observed["concepts"][0]["observations"], 1)
        brow = next(row for row in observed["features"] if row["id"] == "brow_tension")
        self.assertEqual(brow["observations"], 1)
        self.assertEqual(brow["meanValue"], .2)

    def test_pitch_measurement_is_visible_without_reference_cutoff(self):
        few = [segment("a", 0, 10000, .3), segment("b", 10000, 20000, .3),
               segment("high", 30000, 40000, .8, pitch=160)]
        _, candidates = analyze_session(self.request(few))
        pitch = next(item for item in candidates if item["id"] == "pitch_change")
        self.assertIsNone(pitch["referenceValue"])
        self.assertNotIn("threshold", pitch)
        enough = few[:2] + [segment("c", 20000, 30000, .3), few[2]]
        request = self.request(enough)
        summary, candidates = analyze_session(request)
        self.assertIn("pitch_change", [c["id"] for c in candidates])
        state = run_agent(request, summary, candidates, decide=lambda view: (
            {"action": "analyze_segment", "candidateId": "pitch_change", "segmentIds": ["high"]}
            if not view["toolResults"] else {"action": "finish", "priorityCandidateIds": []}))
        self.assertEqual(state.actions[0]["result"]["referenceValue"], 100)

    def test_fabricated_citation_is_rejected_and_report_remains_usable(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        def bad_synthesis(context):
            return {"summary": "Unsupported", "coaching": [
                {"issueId": issue["id"], "recommendation": "Advice", "evidenceIds": ["made-up"]}
                for issue in context["issues"]]}
        report = self.report(request, rag=FakeRag(), synthesize=bad_synthesis)
        self.assertEqual(report["status"], "limited")
        self.assertTrue(report["priorities"])
        self.assertTrue(all(issue["evidenceIds"] == [] for issue in report["priorities"]))
        self.assertTrue(all(issue["evidenceStatus"] == "insufficient" for issue in report["priorities"]))

    def test_direct_study_is_not_attached_to_uncited_generated_review(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        class DirectRag(FakeRag):
            def retrieve_evidence(self, query, k=3):
                hits = super().retrieve_evidence(query, k)
                hits[0].update({"topics": ["brow_tension"], "applicability": "direct"})
                return hits
        def wrong_id(context):
            return {"summary": "Review the interval.", "coaching": [{
                "issueId": issue["id"], "researchBasis": "Brow movement was studied during speaking.",
                "recommendation": "Change your face.", "evidenceIds": ["invented:1:0"]}
                for issue in context["issues"]]}
        report = self.report(request, rag=DirectRag(), synthesize=wrong_id)
        issue = report["priorities"][0]
        self.assertEqual(issue["evidenceIds"], [])
        self.assertEqual(issue["recommendation"], "")
        self.assertEqual(issue["researchBasis"], "")

    def test_verified_citation_reaches_the_matching_priority(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        def valid_synthesis(context):
            return {"summary": "Observed brow movement in the high-score interval.",
                    "coaching": [{"issueId": issue["id"], "researchBasis": "Brow lowering was measured during speaking.", "recommendation": "Review the recording.",
                                  "evidenceIds": issue["retrievedEvidenceIds"][:1]}
                                 for issue in context["issues"]]}
        report = self.report(request, rag=FakeRag(), synthesize=valid_synthesis)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["priorities"][0]["evidenceIds"], ["paper:1:0"])
        self.assertEqual(report["priorities"][0]["researchBasis"], "말하기 과제에서 눈썹 내림 움직임을 측정했습니다.")
        self.assertEqual(report["evidence"][0]["page"], 1)

    def test_wrong_issue_citation_is_removed_without_losing_verified_one(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        def mixed_synthesis(context):
            return {"summary": "Review this interval.", "coaching": [{
                "issueId": issue["id"], "researchBasis": "Brow lowering was measured during speaking.", "recommendation": "Review the recording.",
                "evidenceIds": ["invented:1:0", *issue["retrievedEvidenceIds"][:1]]}
                for issue in context["issues"]]}
        report = self.report(request, rag=FakeRag(), synthesize=mixed_synthesis)
        self.assertEqual(report["synthesisStatus"], "generated")
        self.assertEqual(report["priorities"][0]["evidenceIds"], ["paper:1:0"])

    def test_citation_without_research_finding_is_not_shown_as_evidence_based_advice(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        def missing_basis(context):
            return {"summary": "Review this interval.", "coaching": [{
                "issueId": issue["id"], "recommendation": "Review the recording.",
                "evidenceIds": issue["retrievedEvidenceIds"][:1]}
                for issue in context["issues"]]}
        report = self.report(request, rag=FakeRag(), synthesize=missing_basis)
        self.assertEqual(report["priorities"][0]["evidenceStatus"], "insufficient")
        self.assertEqual(report["priorities"][0]["recommendation"], "")

    def test_practice_study_supplements_but_cannot_replace_issue_evidence(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        class TwoTrackRag:
            def retrieve_issue_evidence(self, issue_id, query, k=5):
                return [{"id": "brow:2:0", "source": "brow.pdf", "page": 2, "chunk": 0,
                         "text": "Brow lowerer action units were observed.", "distance": .2,
                         "topics": ["brow_tension"], "findingKo": "눈썹 움직임을 관찰한 연구입니다."}]

            def retrieve_evidence(self, query, k=4):
                return [{"id": "practice:1:0", "source": "feedback.pdf", "page": 1, "chunk": 0,
                         "text": "Video-based feedback was tested in oral presentations.",
                         "distance": .2, "topics": ["practice"]}]

        def combined(context):
            self.assertEqual(context["practiceEvidenceIds"], ["practice:1:0"])
            issue = context["issues"][0]
            return {"summary": "Review the observed interval.", "coaching": [{
                "issueId": issue["id"], "researchBasis": "Brow lowerer action units were observed.", "recommendation": "Review this interval in the recording.",
                "evidenceIds": [issue["retrievedEvidenceIds"][0], "practice:1:0"]}]}

        report = self.report(request, rag=TwoTrackRag(), synthesize=combined)
        self.assertEqual(report["priorities"][0]["evidenceIds"], ["brow:2:0", "practice:1:0"])
        self.assertEqual({item["source"] for item in report["evidence"]}, {"brow.pdf", "feedback.pdf"})

        def practice_only(context):
            return {"summary": "Review the observed interval.", "coaching": [{
                "issueId": context["issues"][0]["id"], "recommendation": "Review the video.",
                "evidenceIds": ["practice:1:0"]}]}

        report = self.report(request, rag=TwoTrackRag(), synthesize=practice_only)
        self.assertEqual(report["priorities"][0]["evidenceIds"], [])
        self.assertEqual(report["status"], "limited")

    def test_paper_that_did_not_measure_brow_cannot_support_brow_advice(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        class FacialRag:
            def retrieve_evidence(self, query, k=5):
                return [{"id": "facial:10:2", "source": "Blasberg_2023_facial_stress.pdf",
                         "page": 10, "chunk": 2,
                         "text": "Brow lowerer was not measured because the forehead was obscured.",
                         "distance": .2}]
        def synthesize(context):
            self.assertEqual(context["issues"][0]["retrievedEvidenceIds"], [])
            return {"summary": "Review the recorded interval.", "coaching": [
                {"issueId": issue["id"], "recommendation": "Review the recording.", "evidenceIds": []}
                for issue in context["issues"]]}
        report = self.report(request, rag=FacialRag(), synthesize=synthesize)
        self.assertEqual(report["priorities"][0]["evidenceStatus"], "insufficient")
        self.assertEqual(report["evidence"], [])

    def test_ai_mental_state_claim_is_replaced_with_observation_summary(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        def synthesize(context):
            return {"summary": "긴장이 잘 드러납니다.", "coaching": [
                {"issueId": issue["id"], "recommendation": "Review the recording.", "evidenceIds": []}
                for issue in context["issues"]]}
        report = self.report(request, rag=None, synthesize=synthesize)
        self.assertEqual(report["synthesisStatus"], "generated")
        self.assertTrue(report["summaryFallbackUsed"])
        self.assertNotIn("긴장이 잘 드러납니다", report["summaryText"])

    def test_out_of_session_time_in_ai_summary_is_not_shown(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        def synthesize(context):
            return {"summary": "40초부터 50초 구간을 보세요.", "coaching": [
                {"issueId": issue["id"], "recommendation": "Review the recording.", "evidenceIds": []}
                for issue in context["issues"]]}
        report = self.report(request, synthesize=synthesize)
        self.assertTrue(report["summaryFallbackUsed"])
        self.assertNotIn("50초", report["summaryText"])

    def test_summary_reports_measurements_without_unverified_communication_effect(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        def synthesize(context):
            return {"summary": "이 변화가 발표 전달력을 떨어뜨렸습니다.", "coaching": [
                {"issueId": issue["id"], "recommendation": "Review the recording.", "evidenceIds": []}
                for issue in context["issues"]]}
        report = self.report(request, synthesize=synthesize)
        self.assertNotIn("전달력을 떨어뜨렸", report["summaryText"])
        self.assertIn("00:00-00:10 구간의 눈썹 움직임 추정치", report["summaryText"])
        self.assertNotIn("모델 점수", report["summaryText"])

    def test_summary_rejects_speculative_delivery_impact(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        def synthesize(context):
            return {"summary": "이 변화가 메시지 전달에 영향을 미쳤을 수 있습니다.", "coaching": [
                {"issueId": issue["id"], "recommendation": "Review the recording.", "evidenceIds": []}
                for issue in context["issues"]]}
        report = self.report(request, synthesize=synthesize)
        self.assertNotIn("영향을 미쳤을 수", report["summaryText"])

    def test_overlapping_pitch_signals_can_both_be_reported_when_selected(self):
        report = self.report(sample_request(), selected=("pitch_change", "pitch_variability", "brow_tension"))
        ids = [issue["id"] for issue in report["priorities"]]
        self.assertIn("pitch_change", ids)
        self.assertIn("pitch_variability", ids)
        self.assertIn("brow_tension", ids)
        pitch = [issue for issue in report["priorities"] if issue["id"].startswith("pitch_")]
        self.assertEqual(pitch[0]["ranges"], pitch[1]["ranges"])
        self.assertEqual(pitch[0]["assessment"]["independentObservations"], 5)
        self.assertEqual(pitch[0]["assessment"]["adviceMode"], "review")

    def test_agent_followup_search_is_bounded_and_topic_checked(self):
        request = self.request([segment("high", 0, 10000, .8, brow=.5)], 10000)
        class ResearchRag:
            def __init__(self):
                self.queries = []

            def retrieve_issue_evidence(self, issue_id, query, k=5):
                self.queries.append((issue_id, query))
                return [{"id": f"{len(self.queries)}:1:0", "source": "brow.pdf", "page": 1,
                         "chunk": 0, "text": "Brow lowerer was measured during speaking.",
                         "distance": .2, "topics": [issue_id]}]

            def retrieve_evidence(self, query, k=4):
                return []

        rag = ResearchRag()
        report = self.report(request, rag=rag, plan=lambda _: {"followUpSearches": [
            {"issueId": "brow_tension", "query": "brow lowerer reliability during public speaking"}]})
        self.assertEqual(len(rag.queries), 2)
        self.assertEqual(len(report["researchActions"]), 1)
        self.assertEqual(len(report["priorities"][0]["retrievedEvidenceIds"]), 2)

        rag = ResearchRag()
        report = self.report(request, rag=rag, plan=lambda _: {"followUpSearches": [
            {"issueId": "invented", "query": "brow lowerer reliability during public speaking"}]})
        self.assertEqual(len(rag.queries), 1)
        self.assertEqual(report["researchActions"], [])

    def test_advice_mode_uses_all_four_dimensions_without_one_blended_score(self):
        class TaggedRag:
            def retrieve_issue_evidence(self, issue_id, query, k=5):
                return [{"id": "brow:1:0", "source": "brow.pdf", "page": 1,
                         "chunk": 0, "text": "Brow lowerer was measured during speaking.",
                         "distance": .2, "topics": [issue_id], "evidenceRole": "practice_specific",
                         "applicability": "direct",
                         "findingKo": "발표 연습 전후의 움직임을 비교했습니다."}]

            def retrieve_evidence(self, query, k=4):
                return []

        repeated = self.request([
            segment("a", 0, 10000, .9, brow=.5, confidence=.91),
            segment("b", 10000, 20000, .9, brow=.5, confidence=.92),
        ], 20000)
        issue = self.report(repeated, rag=TaggedRag())["priorities"][0]
        self.assertEqual(issue["assessment"]["adviceMode"], "conditional_practice")
        self.assertEqual(issue["assessment"]["independentObservations"], 2)
        self.assertEqual(issue["assessment"]["researchFit"], "direct")
        def practice_synthesis(context):
            return {"summary": "Review the observed interval.", "coaching": [{
                "issueId": item["id"], "researchBasis": "Movement was compared before and after training.",
                "recommendation": "Try one optional rehearsal comparison.",
                "evidenceIds": item["retrievedEvidenceIds"][:1]} for item in context["issues"]]}
        practiced = self.report(repeated, rag=TaggedRag(), synthesize=practice_synthesis)["priorities"][0]
        self.assertEqual(practiced["recommendation"], "Try one optional rehearsal comparison.")
        self.assertEqual(practiced["practiceSuggestion"], "Try one optional rehearsal comparison.")
        self.assertEqual(practiced["reviewAction"], "")
        def review_synthesis(context):
            return {"summary": "Review the observed interval.", "coaching": [{
                "issueId": item["id"], "researchBasis": "Movement was compared before and after training.",
                "recommendation": "Check the recording before changing anything.",
                "evidenceIds": item["retrievedEvidenceIds"][:1]} for item in context["issues"]]}
        reviewed = self.report(repeated, rag=TaggedRag(), synthesize=review_synthesis)["priorities"][0]
        self.assertEqual(reviewed["practiceSuggestion"], "")
        self.assertTrue(reviewed["reviewAction"])
        class ObservationalRag(TaggedRag):
            def retrieve_issue_evidence(self, issue_id, query, k=5):
                hits = super().retrieve_issue_evidence(issue_id, query, k)
                hits[0]["evidenceRole"] = "measurement"
                return hits

        issue = self.report(repeated, rag=ObservationalRag())["priorities"][0]
        self.assertEqual(issue["assessment"]["adviceMode"], "review")
        low_quality = self.request([
            segment("a", 0, 10000, .9, brow=.5, confidence=.91),
            segment("b", 10000, 20000, .9, brow=.5, confidence=.92),
            segment("c", 20000, 30000, .9, face=False, confidence=.93),
        ], 30000)
        issue = self.report(low_quality, rag=TaggedRag())["priorities"][0]
        self.assertEqual(issue["assessment"]["adviceMode"], "review")
        self.assertAlmostEqual(issue["assessment"]["measurementQuality"], .6667)

    def test_single_observation_revises_prescriptive_review_without_template(self):
        request = self.request([
            segment("a", 0, 10000, .3), segment("b", 10000, 20000, .3),
            segment("c", 20000, 30000, .3), segment("high", 30000, 40000, .8, pitch=160),
        ])
        class VoiceRag:
            def retrieve_evidence(self, query, k=5):
                return [{"id": "voice:1:0", "source": "voice.pdf", "page": 1,
                         "chunk": 0, "text": "Fundamental frequency (F0) was measured during public speaking.",
                         "distance": .2, "findingKo": "발표 중 기본주파수를 측정했습니다."}]
        calls = []
        generated_review = "앞선 구간과 이어 들으며 후반부의 목소리 높이 변화가 의도한 강조인지 확인해 보세요."
        def synthesize(context):
            calls.append(context)
            return {"summary": "Review 30–40 seconds.", "coaching": [
                {"issueId": issue["id"], "researchBasis": "Fundamental frequency was measured during public speaking.",
                 "recommendation": generated_review if "verificationErrors" in context else "일정한 톤으로 천천히 말하세요.",
                 "evidenceIds": issue["retrievedEvidenceIds"][:1]}
                for issue in context["issues"]]}
        report = self.report(request, selected=("pitch_change",), rag=VoiceRag(), synthesize=synthesize)
        self.assertTrue(report["priorities"])
        self.assertEqual(len(calls), 2)
        self.assertIn("review_mode_prescribes_correction", report["claimVerification"]["initialErrors"]["coaching"]["pitch_change"])
        self.assertEqual(report["priorities"][0]["recommendation"], generated_review)
        self.assertEqual(report["priorities"][0]["practiceSuggestion"], "")
        self.assertEqual(report["priorities"][0]["reviewAction"], generated_review)
        self.assertIn("160.00 Hz", report["priorities"][0]["observationText"])
        self.assertEqual(report["priorities"][0]["researchFinding"], report["priorities"][0]["researchBasis"])
        self.assertNotIn("천천히 말하세요", report["priorities"][0]["recommendation"])
        self.assertEqual(report["priorities"][0]["evidenceIds"], ["voice:1:0"])

    def test_contract_rejects_duplicate_ids_and_out_of_session_window(self):
        with self.assertRaises(ValidationError):
            self.request([segment("a", 0, 10000, .5), segment("a", 10000, 20000, .6)])
        with self.assertRaises(ValidationError):
            self.request([segment("a", 35000, 45000, .5)])


if __name__ == "__main__":
    unittest.main()
