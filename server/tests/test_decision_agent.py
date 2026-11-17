"""Decision-loop tests: tool feedback, memory gating, and verified report output."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.decision_agent import MAX_ACTIONS, run_agent
from agent.report_agent import _invalid_generated_text, _summary_errors, generate_report
from agent.report_schema import ReviewRequest
from agent.session_analyzer import analyze_session
from server.agent_memory import load_recent_memory
from server.tests.test_agent_report import segment


class ResearchRag:
    def __init__(self):
        self.queries = []

    def retrieve_issue_evidence(self, issue_id, query, k=5):
        self.queries.append((issue_id, query))
        return [{"id": f"{issue_id}:1:0", "source": "voice.pdf", "page": 1, "chunk": 0,
                 "text": "Pitch variation and intonation were measured during oral presentations.",
                 "distance": .1, "topics": [issue_id], "applicability": "direct",
                 "findingKo": "발표에서 음성 운율의 변화를 측정했습니다.",
                 "scope": "Presentation prosody measurement; no rehearsal intervention tested."}]

    def retrieve_evidence(self, query, k=4):
        return []


class DecisionAgentTests(unittest.TestCase):
    def request(self):
        windows = [segment(f"base-{n}", n * 10000, (n + 1) * 10000, .3, pitch=120)
                   for n in range(3)]
        windows.extend([segment("high-1", 30000, 40000, .84, pitch=170, brow=.6, confidence=.84),
                        segment("high-2", 40000, 50000, .82, pitch=165, brow=.6, confidence=.82)])
        return ReviewRequest(sessionId="current", durationMs=50000, sceneLabel="camera", segments=windows)

    def test_replans_after_tool_result_and_searches_only_selected_candidate(self):
        request = self.request()
        rag = ResearchRag()
        seen = []

        def decide(state):
            seen.append(state)
            if not state["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change"}
            if len(state["toolResults"]) == 1:
                self.assertEqual(state["toolResults"][0]["result"]["metric"], "f0_mean")
                return {"action": "retrieve_papers", "candidateId": "pitch_change",
                        "claimKind": "interpretation"}
            self.assertEqual(state["toolResults"][1]["result"]["support"], "direct")
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}

        def synthesize(context):
            return {"summary": "Review the measured voice change.", "coaching": [{
                "issueId": "pitch_change", "researchBasis": "Pitch was measured.",
                "recommendation": "Listen to the highlighted interval and compare the emphasis.",
                "evidenceIds": context["issues"][0]["retrievedEvidenceIds"]}]}

        report = generate_report(request, rag=rag, decide=decide, synthesize=synthesize,
                                 model_version="test-model", agent_mode=True)
        self.assertEqual(len(seen), 3)
        self.assertEqual([action["action"] for action in report["agentRun"]["actions"]],
                         ["analyze_segment", "retrieve_papers"])
        self.assertEqual([item["id"] for item in report["priorities"]], ["pitch_change"])
        self.assertEqual(report["analysisStatus"], "findings_available")
        self.assertEqual(len(rag.queries), 1)
        self.assertEqual(report["agentMemory"]["modelVersion"], "test-model")
        self.assertEqual(report["agentMemory"]["focusGoal"]["candidateId"], "pitch_change")
        claim = report["claimVerification"]["claims"][1]
        self.assertEqual(claim["candidateId"], "pitch_change")
        self.assertEqual(claim["measurement"]["metric"], "f0_mean")
        self.assertTrue(claim["segmentIds"])
        self.assertEqual(claim["evidenceIds"], report["priorities"][0]["evidenceIds"])

    def test_report_searches_when_agent_selects_a_finding_without_calling_papers(self):
        rag = ResearchRag()

        def decide(view):
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["high-1", "high-2"]}
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}

        def synthesize(context):
            ids = context["issues"][0]["retrievedEvidenceIds"]
            self.assertEqual(ids, ["pitch_change:1:0"])
            return {"summary": "Review the measured voice change.", "coaching": [{
                "issueId": "pitch_change", "researchBasis": "Pitch was measured.",
                "recommendation": "Listen to the highlighted interval and compare the emphasis.",
                "evidenceIds": ids}]}

        report = generate_report(self.request(), rag=rag, decide=decide, synthesize=synthesize)
        self.assertEqual([issue_id for issue_id, _ in rag.queries], ["pitch_change"])
        self.assertEqual(report["researchActions"][0]["acceptedHits"], 1)
        self.assertEqual(report["priorities"][0]["evidenceStatus"], "cited_excerpt")

    def test_path_a_segment_concept_paper_finish_uses_each_result(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        def decide(view):
            previous = view["toolResults"][-1] if view["toolResults"] else None
            if previous is None:
                return {"action": "analyze_segment", "candidateId": "pitch_change"}
            if previous["action"] == "analyze_segment":
                self.assertGreaterEqual(previous["result"]["independentObservations"], 2)
                return {"action": "analyze_concept", "candidateId": "pitch_change"}
            if previous["action"] == "analyze_concept":
                self.assertEqual(previous["result"]["relationship"], "co_observed_not_causal")
                return {"action": "retrieve_papers", "candidateId": "pitch_change",
                        "claimKind": "interpretation"}
            self.assertEqual(previous["result"]["support"], "direct")
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}
        state = run_agent(request, summary, candidates, rag=ResearchRag(), decide=decide)
        self.assertEqual([row["selectedAction"]["action"] for row in state.decisions],
                         ["analyze_segment", "analyze_concept", "retrieve_papers", "finish"])
        self.assertIsNone(state.decisions[0]["observedResult"])
        self.assertEqual(state.decisions[2]["observedResult"]["relationship"],
                         "co_observed_not_causal")
        self.assertTrue(all(row["source"] == "callback" for row in state.decisions))

    def test_path_b_low_quality_segment_finishes_without_paper_search(self):
        windows = [segment(f"base-{n}", n * 10000, (n + 1) * 10000, .3, pitch=120)
                   for n in range(3)]
        windows += [segment("measured", 30000, 40000, .84, pitch=170, confidence=.84),
                    segment("audio-missing", 40000, 50000, .82, audio=False, confidence=.82)]
        request = ReviewRequest(sessionId="low-quality", durationMs=50000, segments=windows)
        summary, candidates = analyze_session(request)
        def decide(view):
            if not view["toolResults"]:
                self.assertIn("measured", {row["segmentId"] for row in view["sessionWindows"]})
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["measured", "audio-missing"]}
            self.assertEqual(view["toolResults"][-1]["result"]["measurementQuality"], .5)
            self.assertEqual(view["weakMeasurementContext"]["sameIntervalAlternatives"], [])
            return {"action": "finish", "priorityCandidateIds": []}
        state = run_agent(request, summary, candidates, rag=ResearchRag(), decide=decide)
        self.assertEqual([row["selectedAction"]["action"] for row in state.decisions],
                         ["analyze_segment", "finish"])
        self.assertEqual(state.selected_ids, [])
        self.assertEqual(state.stop_reason, "no_valid_finding")
        self.assertNotIn("pitch_change", state.decisions[1]["conceptEligibleCandidateIds"])
        self.assertEqual(state.decisions[1]["observedResult"]["measurementQuality"], .5)

    def test_weak_interval_rejects_redundant_analysis_then_finishes(self):
        windows = [segment(f"base-{n}", n * 10000, (n + 1) * 10000, .3, pitch=120)
                   for n in range(3)]
        windows += [segment("measured", 30000, 40000, .84, pitch=170),
                    segment("audio-missing", 40000, 50000, .82, audio=False)]
        request = ReviewRequest(sessionId="weak-retry", durationMs=50000, segments=windows)
        summary, candidates = analyze_session(request)
        rag = ResearchRag()

        def decide(view):
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["measured", "audio-missing"]}
            if not view["decisionErrors"]:
                self.assertEqual(view["weakMeasurementContext"]["sameIntervalAlternatives"], [])
                return {"action": "analyze_segment", "candidateId": "concept:음성 피치",
                        "segmentIds": ["measured", "audio-missing"]}
            return {"action": "finish", "priorityCandidateIds": []}

        state = run_agent(request, summary, candidates, rag=rag, decide=decide,
                          decision_provider="luxia")
        self.assertEqual([action["action"] for action in state.actions], ["analyze_segment"])
        self.assertEqual(state.decisions[1]["proposals"][0]["serverValidation"], "rejected")
        self.assertIn("No independently valid alternative",
                      state.decisions[1]["proposals"][0]["reason"])
        self.assertEqual(state.stop_reason, "no_valid_finding")
        self.assertEqual(rag.queries, [])

    def test_two_rejected_followups_can_still_end_by_agent_finish(self):
        windows = [segment(f"base-{n}", n * 10000, (n + 1) * 10000, .3, pitch=120)
                   for n in range(3)]
        windows += [segment("measured", 30000, 40000, .84, pitch=170),
                    segment("audio-missing", 40000, 50000, .82, audio=False)]
        request = ReviewRequest(sessionId="weak-three-attempts", durationMs=50000,
                                segments=windows)
        summary, candidates = analyze_session(request)
        calls = 0

        def decide(view):
            nonlocal calls
            calls += 1
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["measured", "audio-missing"]}
            if len(view["decisionErrors"]) < 2:
                return {"action": "retrieve_papers", "candidateId": "pitch_change",
                        "claimKind": "interpretation"}
            return {"action": "finish", "priorityCandidateIds": []}

        state = run_agent(request, summary, candidates, rag=ResearchRag(), decide=decide,
                          decision_provider="luxia")
        self.assertEqual(calls, 4)
        self.assertEqual([proposal["serverValidation"]
                          for proposal in state.decisions[1]["proposals"]],
                         ["rejected", "rejected", "accepted"])
        self.assertEqual(state.decisions[1]["source"], "luxia")
        self.assertEqual(state.stop_reason, "no_valid_finding")

    def test_one_changed_pitch_plus_one_baseline_is_not_repetition(self):
        windows = [segment(f"base-{n}", n * 10000, (n + 1) * 10000, .3,
                           pitch=[120, 122, 124][n]) for n in range(3)]
        windows += [segment("measured", 30000, 40000, .84, pitch=170),
                    segment("audio-missing", 40000, 50000, .82, audio=False)]
        request = ReviewRequest(sessionId="mixed-interval", durationMs=50000,
                                segments=windows)
        summary, candidates = analyze_session(request)
        rag = ResearchRag()

        def decide(view):
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["base-2", "measured"]}
            if not view["decisionErrors"]:
                self.assertEqual(view["toolResults"][0]["result"]["coherentShiftCount"], 1)
                self.assertNotIn("pitch_change", view["paperEligibleCandidateIds"])
                self.assertEqual(view["weakMeasurementContext"]["sameIntervalAlternatives"], [])
                self.assertNotIn("concept:음성 피치", view["conceptEligibleCandidateIds"])
                return {"action": "retrieve_papers", "candidateId": "pitch_change",
                        "claimKind": "interpretation"}
            return {"action": "finish", "priorityCandidateIds": []}

        state = run_agent(request, summary, candidates, rag=rag, decide=decide,
                          decision_provider="luxia")
        self.assertEqual(state.decisions[1]["proposals"][0]["reason"],
                         "candidate_change_not_repeated")
        self.assertEqual(state.actions[0]["result"]["coherentShiftCount"], 1)
        self.assertEqual(state.stop_reason, "no_valid_finding")
        self.assertEqual(state.selected_ids, [])
        self.assertEqual(rag.queries, [])

    def test_agent_sees_unlisted_model_features_and_can_choose_an_interval(self):
        windows = [segment(f"window-{n}", n * 10000, (n + 1) * 10000, .35,
                           pitch=120) for n in range(3)]
        windows += [segment("window-3", 30000, 40000, .82, pitch=125),
                    segment("window-4", 40000, 50000, .81, pitch=122)]
        for index, window in enumerate(windows):
            window["audioFeatures"]["energy_variability"] = .2 if index < 3 else .75
            window["videoFeatures"]["motion"] = .03 if index < 3 else .08
            window["concepts"]["새 concept"] = .1 if index < 3 else .7
        request = ReviewRequest(sessionId="new-features", durationMs=50000, segments=windows)
        summary, candidates = analyze_session(request)
        ids = {row["id"] for row in candidates}
        self.assertTrue({"audio:energy_variability", "video:motion", "concept:새 concept"} <= ids)
        self.assertTrue(all(item["selectionBasis"] == "all_valid_model_measurements"
                            and "priorityScore" not in item and "threshold" not in item
                            for item in candidates))
        def decide(view):
            if not view["toolResults"]:
                chosen = next(item for item in view["candidates"]
                              if item["candidateId"] == "audio:energy_variability")
                self.assertEqual(chosen["valueRange"], [.2, .75])
                return {"action": "analyze_segment", "candidateId": chosen["candidateId"],
                        "segmentIds": ["window-3", "window-4"]}
            return {"action": "finish", "priorityCandidateIds": []}
        state = run_agent(request, summary, candidates, decide=decide, rag=ResearchRag())
        self.assertEqual(state.actions[0]["result"]["ranges"], [{"startMs": 30000, "endMs": 50000}])
        self.assertEqual(state.actions[0]["result"]["observedValue"], .75)
        self.assertEqual(state.actions[0]["result"]["independentObservations"], 2)
        self.assertEqual(state.hits, {})

    def test_agent_can_choose_lower_scored_interval_when_measurement_changes_there(self):
        scores = [.76, .78, .58, .55, .57]
        pitches = [120, 121, 150, 154, 151]
        windows = [segment(f"window-{index}", index * 10000, (index + 1) * 10000,
                           scores[index], pitch=pitches[index]) for index in range(5)]
        request = ReviewRequest(sessionId="relative-review", durationMs=50000, segments=windows)
        summary, candidates = analyze_session(request)
        self.assertNotIn("highStressThreshold", summary)
        self.assertEqual(next(item for item in candidates if item["id"] == "pitch_change")["ranges"],
                         [{"startMs": 0, "endMs": 50000}])

        def decide(view):
            if not view["toolResults"]:
                self.assertEqual([row["stressScore"] for row in view["sessionWindows"]], scores)
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["window-2", "window-3", "window-4"]}
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}

        state = run_agent(request, summary, candidates, decide=decide)
        self.assertEqual(state.actions[0]["result"]["ranges"],
                         [{"startMs": 20000, "endMs": 50000}])
        self.assertEqual(state.actions[0]["result"]["referenceValue"], 120.5)
        self.assertEqual(state.selected_ids, ["pitch_change"])

    def test_pitch_review_without_earlier_comparison_is_rejected_and_reselected(self):
        scores = [.76, .78, .58, .55, .57]
        pitches = [120, 121, 150, 154, 151]
        windows = [segment(f"window-{index}", index * 10000, (index + 1) * 10000,
                           scores[index], pitch=pitches[index]) for index in range(5)]
        request = ReviewRequest(sessionId="pitch-reference", durationMs=50000, segments=windows)
        summary, candidates = analyze_session(request)

        def decide(view):
            if view["decisionErrors"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["window-2", "window-3", "window-4"]}
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["window-0", "window-1"]}
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}

        state = run_agent(request, summary, candidates, decide=decide,
                          decision_provider="luxia")
        self.assertIn("needs repeated earlier comparison measurements",
                      state.decisions[0]["proposals"][0]["reason"])
        self.assertEqual(state.actions[0]["segmentIds"], ["window-2", "window-3", "window-4"])
        self.assertEqual(state.actions[0]["result"]["referenceValue"], 120.5)

    def test_invalid_agent_interval_is_rejected_without_tool_execution(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        state = run_agent(request, summary, candidates, decide=lambda _: {
            "action": "analyze_segment", "candidateId": "pitch_change",
            "segmentIds": ["not-a-real-window"]})
        self.assertEqual(state.actions, [])
        self.assertEqual(state.stop_reason, "decision_unavailable")
        self.assertEqual(state.decisions[0]["proposals"][0]["serverValidation"], "rejected")

    def test_live_agent_must_choose_the_interval_it_inspects(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        state = run_agent(request, summary, candidates, decision_provider="luxia",
                          decide=lambda _: {"action": "analyze_segment", "candidateId": "pitch_change"})
        self.assertEqual(state.actions, [])
        self.assertEqual(state.stop_reason, "decision_unavailable")
        self.assertEqual(state.decisions[0]["proposals"][0]["reason"],
                         "Luxia must select segmentIds for segment analysis")

    def test_whole_session_interval_is_rejected_and_agent_reselects(self):
        request = self.request()
        summary, candidates = analyze_session(request)

        def decide(view):
            if view["decisionErrors"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["high-1", "high-2"]}
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": [row.segmentId for row in request.segments]}
            return {"action": "finish", "priorityCandidateIds": []}

        state = run_agent(request, summary, candidates, decide=decide)
        self.assertEqual(state.decisions[0]["proposals"][0]["serverValidation"], "rejected")
        self.assertIn("leave a measured comparison window",
                      state.decisions[0]["proposals"][0]["reason"])
        self.assertEqual(state.actions[0]["segmentIds"], ["high-1", "high-2"])
        self.assertEqual(state.actions[0]["result"]["referenceValue"], 120)

    def test_new_metric_without_research_does_not_create_user_advice(self):
        request = self.request()
        for index, row in enumerate(request.segments):
            row.audioFeatures["energy_variability"] = .2 if index < 3 else .7
        def decide(view):
            return ({"action": "analyze_segment", "candidateId": "audio:energy_variability",
                     "segmentIds": ["high-1", "high-2"]} if not view["toolResults"] else
                    {"action": "finish", "priorityCandidateIds": ["audio:energy_variability"]})
        report = generate_report(request, decide=decide, agent_mode=True,
                                 synthesize=lambda _: {"summary": "이 값을 반드시 고치세요.",
                                                       "coaching": [{"issueId": "audio:energy_variability",
                                                                     "recommendation": "즉시 교정하세요.",
                                                                     "evidenceIds": []}]})
        self.assertEqual(report["status"], "limited")
        self.assertEqual(report["priorities"][0]["recommendation"], "")
        self.assertTrue(report["summaryFallbackUsed"])
        self.assertNotIn("고치세요", report["summaryText"])

    def test_low_quality_empty_finish_produces_completed_explanation_without_tools(self):
        windows = [segment(f"base-{n}", n * 10000, (n + 1) * 10000, .3, pitch=120)
                   for n in range(3)]
        windows += [segment("measured", 30000, 40000, .84, pitch=170),
                    segment("audio-missing", 40000, 50000, .82, audio=False)]
        request = ReviewRequest(sessionId="weak-report", durationMs=50000, segments=windows)
        rag = ResearchRag()
        report = generate_report(
            request, rag=rag, agent_mode=True,
            decide=lambda _: {"action": "finish", "priorityCandidateIds": []},
            synthesize=lambda _: self.fail("No LLM synthesis is needed without findings"),
        )
        self.assertEqual(report["agentRun"]["stopReason"], "no_valid_finding")
        self.assertEqual(report["agentRun"]["actions"], [])
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["analysisStatus"], "insufficient_evidence")
        self.assertEqual(report["synthesisStatus"], "not_required")
        self.assertIn("평균 목소리 높이", report["summaryText"])
        self.assertIn("170.00 Hz", report["summaryText"])
        self.assertIn("00:30–00:40", report["summaryText"])
        self.assertEqual(report["observationReport"]["peakSegment"]["segmentId"], "measured")
        self.assertTrue(report["observationReport"]["concepts"])
        self.assertTrue(report["observationReport"]["features"])
        self.assertEqual(report["priorities"], [])
        self.assertEqual(report["claimVerification"]["claims"][0]["status"], "outcome_explanation")
        self.assertEqual([item[0] for item in rag.queries], ["pitch_change"])
        self.assertEqual(report["observationEvidenceIds"], ["pitch_change:1:0"])
        self.assertNotIn("AI 종합 분석이 설정되지", " ".join(report["limitations"]))

    def test_clean_session_agent_sees_measurements_and_reports_no_significant_finding(self):
        windows = [segment(f"stable-{n}", n * 10000, (n + 1) * 10000, .3, pitch=120)
                   for n in range(5)]
        request = ReviewRequest(sessionId="stable-report", durationMs=50000, segments=windows)
        report = generate_report(request, agent_mode=True,
                                 decide=lambda view: {"action": "finish", "priorityCandidateIds": []})
        self.assertGreater(report["candidateCount"], 0)
        self.assertEqual(report["analysisStatus"], "no_significant_finding")
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["synthesisStatus"], "not_required")
        self.assertIn("음성·영상 특징은 뚜렷한 구간 차이를 보이지 않았습니다", report["summaryText"])
        self.assertIn("30/100", report["summaryText"])
        self.assertIn("평균 목소리 높이 120.00 Hz", report["summaryText"])
        self.assertIn("Concept 출력", report["summaryText"])
        self.assertIn("실제 발화와 표정", report["summaryText"])
        self.assertIn("비슷했습니다", report["summaryText"])
        self.assertNotIn("이번 발표에서 가장 높았습니다", report["summaryText"])
        self.assertEqual(report["priorities"], [])

    def test_unavailable_decision_service_does_not_fake_a_completed_analysis(self):
        def unavailable(_): raise RuntimeError("Provider unavailable")
        report = generate_report(self.request(), agent_mode=True, decide=unavailable)
        self.assertEqual(report["agentRun"]["stopReason"], "decision_unavailable")
        self.assertEqual(report["status"], "limited")
        self.assertEqual(report["priorities"], [])
        self.assertIn("00:30–00:40", report["summaryText"])

    def test_observation_report_uses_comparable_previous_record(self):
        prior = {"sessionId": "previous", "modelVersion": "test-model",
                 "metricDefinitionVersion": "session-analysis-v4", "sceneLabel": "camera",
                 "durationMs": 50000, "candidates": [{"candidateId": "brow_tension",
                 "metric": "brow_tension", "observedValue": .2,
                 "observationCount": 2, "measurementQuality": 1.0}]}
        report = generate_report(self.request(), agent_mode=True,
                                 decide=lambda _: {"action": "finish", "priorityCandidateIds": []},
                                 prior_memory=prior, model_version="test-model")
        comparison = report["observationReport"]["previousComparison"]
        self.assertEqual(comparison["previousSessionId"], "previous")
        self.assertEqual(comparison["previousSessionCount"], 1)
        self.assertEqual(comparison["metricId"], "brow_tension")
        self.assertEqual(comparison["currentValue"], .1)
        self.assertIn("00:30–00:40", report["observationReport"]["practiceFocus"])

    def test_report_lists_related_paper_as_context_without_unverified_coaching(self):
        class ContextRag:
            def retrieve_issue_evidence(self, issue_id, query, k=5):
                return [{"id": "brow:context:0", "source": "brow-paper.pdf", "page": 3,
                         "chunk": 0, "text": "Eyebrow movement was measured in speaking interaction.",
                         "distance": .2, "topics": ["brow_tension"], "applicability": "related",
                         "findingKo": "발화 중 눈썹 움직임을 관찰했습니다."}]
        report = generate_report(self.request(), rag=ContextRag(), agent_mode=True,
                                 decide=lambda _: {"action": "finish", "priorityCandidateIds": []})
        self.assertEqual(report["observationEvidenceIds"], ["brow:context:0"])
        self.assertEqual(report["evidence"][0]["applicability"], "related")
        self.assertEqual(report["priorities"], [])
        self.assertIn("00:30–00:40", report["summaryText"])

    def test_invalid_later_decisions_preserve_checked_measurements_without_advice(self):
        def decide(view):
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["high-1", "high-2"]}
            return {"action": "compare_previous_session", "candidateId": "pitch_change"}

        report = generate_report(self.request(), decide=decide, agent_mode=True)
        self.assertEqual(report["agentRun"]["stopReason"], "decision_unavailable")
        self.assertEqual(report["status"], "limited")
        self.assertEqual([item["id"] for item in report["priorities"]], ["pitch_change"])
        self.assertIn("평균 목소리 높이", report["summaryText"])
        self.assertEqual(report["priorities"][0]["recommendation"], "")
        self.assertEqual(report["priorities"][0]["evidenceIds"], [])

    def test_coverage_alone_does_not_mean_measurements_are_sufficient(self):
        windows = [segment(f"missing-{n}", n * 10000, (n + 1) * 10000, .3,
                           audio=False, face=True)
                   for n in range(5)]
        for window in windows:
            window["videoFeatures"] = {}
        request = ReviewRequest(sessionId="missing-metrics", durationMs=50000, segments=windows)
        report = generate_report(request, agent_mode=True)
        self.assertEqual(report["analysis"]["coverage"], 1)
        self.assertEqual(report["analysisStatus"], "insufficient_evidence")
        self.assertIn("비교할 음성·영상 측정값은 수집되지 않았습니다", report["summaryText"])

    def test_low_quality_concept_request_is_rejected_before_fallback_finish(self):
        windows = [segment(f"base-{n}", n * 10000, (n + 1) * 10000, .3, pitch=120)
                   for n in range(3)]
        windows += [segment("measured", 30000, 40000, .84, pitch=170),
                    segment("audio-missing", 40000, 50000, .82, audio=False)]
        request = ReviewRequest(sessionId="weak-concept", durationMs=50000, segments=windows)
        summary, candidates = analyze_session(request)
        rag = ResearchRag()
        attempts = []
        def decide(view):
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["measured", "audio-missing"]}
            attempts.append(view)
            return {"action": "analyze_concept", "candidateId": "pitch_change"}
        state = run_agent(request, summary, candidates, rag=rag, decide=decide)
        self.assertEqual([row["selectedAction"]["action"] for row in state.decisions],
                         ["analyze_segment", "finish"])
        self.assertEqual(state.decisions[1]["proposals"][0]["reason"], "candidate_quality_below_0_8")
        self.assertEqual(state.decisions[1]["source"], "fallback")
        self.assertEqual(state.stop_reason, "decision_unavailable")
        self.assertEqual(rag.queries, [])

    def test_server_accepts_luxia_early_finish_for_valid_candidate(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        state = run_agent(request, summary, candidates, rag=ResearchRag(),
                          decide=lambda _: {"action": "finish", "priorityCandidateIds": []})
        self.assertEqual(state.actions, [])
        self.assertEqual(state.decisions[0]["source"], "callback")
        self.assertEqual(state.stop_reason, "finished")

    def test_action_limit_does_not_make_server_choose_a_priority(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        with patch("agent.decision_agent.MAX_ACTIONS", 1):
            state = run_agent(request, summary, candidates,
                              decide=lambda _: {"action": "analyze_segment", "candidateId": "pitch_change"})
        self.assertEqual(state.stop_reason, "action_limit")
        self.assertEqual(state.selected_ids, [])
        self.assertEqual([row["action"] for row in state.actions], ["analyze_segment"])

    def test_path_c_memory_comparison_changes_next_action(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        prior = {"sessionId": "older", "modelVersion": "test-model",
                 "metricDefinitionVersion": "session-analysis-v4", "sceneLabel": "camera",
                 "durationMs": 50000, "focusGoal": {"candidateId": "pitch_change"},
                 "candidates": [{"candidateId": "pitch_change", "metric": "f0_mean",
                                 "observedValue": 130, "observationCount": 2,
                                 "measurementQuality": 1}]}
        def decide(view):
            previous = view["toolResults"][-1] if view["toolResults"] else None
            if previous is None:
                self.assertIn("pitch_change", view["comparableCandidateIds"])
                return {"action": "compare_previous_session", "candidateId": "pitch_change"}
            if previous["action"] == "compare_previous_session":
                self.assertTrue(previous["result"]["comparable"])
                self.assertLess(previous["result"]["difference"], 0)
                return {"action": "analyze_segment", "candidateId": "pitch_change", "segmentIds": ["high-1", "high-2"]}
            if previous["action"] == "analyze_segment":
                return {"action": "analyze_concept", "candidateId": "pitch_change"}
            self.assertEqual(previous["result"]["relationship"], "co_observed_not_causal")
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}
        state = run_agent(request, summary, candidates, decide=decide, prior=prior,
                          model_version="test-model")
        self.assertEqual([row["selectedAction"]["action"] for row in state.decisions],
                         ["compare_previous_session", "analyze_segment", "analyze_concept", "finish"])
        self.assertEqual(state.decisions[1]["observedResult"]["difference"], -10)
        self.assertEqual(state.actions[0]["result"]["previousSessionId"], "older")
        def report_decide(view):
            return ({"action": "compare_previous_session", "candidateId": "pitch_change"}
                    if not view["toolResults"] else
                    {"action": "finish", "priorityCandidateIds": []})
        report = generate_report(request, decide=report_decide, prior_memory=prior,
                                 model_version="test-model", agent_mode=True)
        self.assertEqual(report["sessionComparison"]["difference"], -10)
        self.assertEqual(report["agentRun"]["decisions"][1]["observedResult"]["difference"], -10)

    def test_previous_memory_changes_available_action_only_when_comparable(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        prior = {"sessionId": "older", "modelVersion": "test-model",
                 "metricDefinitionVersion": "session-analysis-v4", "sceneLabel": "camera",
                 "durationMs": 50000, "focusGoal": {"candidateId": "pitch_change"},
                 "candidates": [{"candidateId": "pitch_change", "metric": "f0_mean", "observedValue": 130,
                                 "observationCount": 2, "measurementQuality": 1}]}
        views = []

        def decide(state):
            views.append(state)
            if not state["toolResults"]:
                return {"action": "compare_previous_session", "candidateId": "pitch_change"}
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}

        state = run_agent(request, summary, candidates, decide=decide, prior=prior, model_version="test-model")
        self.assertIn("pitch_change", views[0]["comparableCandidateIds"])
        self.assertEqual(state.actions[0]["result"]["previousValue"], 130)
        self.assertEqual(state.actions[0]["result"]["interpretation"],
                         "metric_difference_only_not_coaching_improvement")
        fallback = run_agent(request, summary, candidates, prior=prior, model_version="test-model")
        self.assertEqual(fallback.actions, [])
        self.assertEqual(fallback.stop_reason, "decision_unavailable")
        changed = {**prior, "modelVersion": "other-model"}
        views.clear()
        state = run_agent(request, summary, candidates, decide=decide, prior=changed, model_version="test-model")
        self.assertNotIn("pitch_change", views[0]["comparableCandidateIds"])
        self.assertEqual(state.actions, [])
        stale_definition = {**prior, "metricDefinitionVersion": "session-analysis-v2"}
        views.clear()
        state = run_agent(request, summary, candidates, decide=decide,
                          prior=stale_definition, model_version="test-model")
        self.assertNotIn("pitch_change", views[0]["comparableCandidateIds"])
        self.assertEqual(state.actions, [])

    def test_invalid_and_repeated_decisions_remain_bounded(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        state = run_agent(request, summary, candidates, decide=lambda _: {
            "action": "analyze_segment", "candidateId": "invented"})
        self.assertLessEqual(len(state.actions), MAX_ACTIONS)
        self.assertEqual(state.actions, [])
        self.assertEqual(state.stop_reason, "decision_unavailable")
        self.assertTrue(all(action["candidateId"] in {item["id"] for item in candidates}
                            for action in state.actions))

    def test_invalid_tool_request_is_retried_without_disabling_decider(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        views = []

        def decide(view):
            views.append(view)
            if len(views) == 1:
                return {"action": "compare_previous_session", "candidateId": "pitch_change"}
            if len(views) == 2:
                self.assertTrue(view["decisionErrors"])
                return {"action": "analyze_segment", "candidateId": "pitch_change"}
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}

        state = run_agent(request, summary, candidates, decide=decide)
        self.assertEqual(len(views), 3)
        self.assertEqual([action["action"] for action in state.actions], ["analyze_segment"])
        self.assertEqual(state.stop_reason, "finished")

    def test_paper_first_is_rejected_with_proposal_and_fallback_reason(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        rag = ResearchRag()
        state = run_agent(request, summary, candidates, rag=rag, decide=lambda _: {
            "action": "retrieve_papers", "candidateId": "pitch_change",
            "claimKind": "interpretation"})
        first = state.decisions[0]
        self.assertEqual(first["selectedAction"]["action"], "finish")
        self.assertEqual(first["source"], "fallback")
        self.assertEqual(first["serverValidation"], "fallback_after_rejection")
        self.assertEqual(first["remainingActions"], state.action_limit)
        self.assertIn("pitch_change", first["validCandidateIds"])
        self.assertEqual(first["proposals"][0]["proposedAction"]["action"], "retrieve_papers")
        self.assertEqual(first["proposals"][0]["reason"], "candidate_measurement_not_checked")
        self.assertEqual(first["proposals"][-1]["serverValidation"], "accepted_fallback")
        self.assertEqual(state.actions, [])

    def test_low_quality_cannot_search_after_segment_check(self):
        windows = [segment(f"base-{n}", n * 10000, (n + 1) * 10000, .3, pitch=120)
                   for n in range(3)]
        windows += [segment("measured", 30000, 40000, .84, pitch=170),
                    segment("audio-missing", 40000, 50000, .82, audio=False)]
        request = ReviewRequest(sessionId="quality", durationMs=50000, segments=windows)
        summary, candidates = analyze_session(request)
        rag = ResearchRag()
        def decide(view):
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["measured", "audio-missing"]}
            return {"action": "retrieve_papers", "candidateId": "pitch_change",
                    "claimKind": "interpretation"}
        state = run_agent(request, summary, candidates, rag=rag, decide=decide)
        self.assertEqual([row["action"] for row in state.actions], ["analyze_segment"])
        self.assertEqual(state.decisions[1]["proposals"][0]["reason"], "candidate_quality_below_0_8")
        self.assertEqual(state.decisions[1]["selectedAction"]["action"], "finish")
        self.assertEqual(state.selected_ids, [])
        self.assertEqual(rag.queries, [])

    def test_flat_measurement_cannot_trigger_paper_search(self):
        request = self.request()
        for window in request.segments:
            window.videoFeatures["brow_tension"] = .1
        summary, candidates = analyze_session(request)
        rag = ResearchRag()

        def decide(view):
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "brow_tension",
                        "segmentIds": ["base-0", "base-1", "base-2"]}
            return {"action": "retrieve_papers", "candidateId": "brow_tension",
                    "claimKind": "interpretation"}

        state = run_agent(request, summary, candidates, rag=rag, decide=decide)
        self.assertEqual([action["action"] for action in state.actions], ["analyze_segment"])
        self.assertEqual(state.decisions[1]["proposals"][0]["reason"],
                         "candidate_has_no_observed_change")
        self.assertEqual(rag.queries, [])

    def test_final_empty_selection_is_respected_after_tool_budget(self):
        request = self.request()
        summary, candidates = analyze_session(request)
        choices = [
            {"action": "analyze_segment", "candidateId": "pitch_change"},
            {"action": "analyze_segment", "candidateId": "brow_tension"},
            {"action": "retrieve_papers", "candidateId": "pitch_change", "claimKind": "interpretation"},
            {"action": "retrieve_papers", "candidateId": "brow_tension", "claimKind": "interpretation"},
            {"action": "analyze_concept", "candidateId": "pitch_change"},
            {"action": "finish", "priorityCandidateIds": []},
        ]
        with patch("agent.decision_agent.MAX_ACTIONS", 5):
            state = run_agent(request, summary, candidates, rag=ResearchRag(),
                              decide=lambda _: choices.pop(0))
        self.assertEqual(state.stop_reason, "finished")
        self.assertEqual(state.selected_ids, [])
        self.assertEqual(len(state.actions), state.action_limit)

    def test_bad_causal_recommendation_is_revised_or_removed(self):
        request = self.request()
        rag = ResearchRag()
        calls = []

        def decide(state):
            if not state["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change"}
            if state["toolResults"][-1]["action"] == "analyze_segment":
                return {"action": "retrieve_papers", "candidateId": "pitch_change",
                        "claimKind": "interpretation"}
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}

        def synthesize(context):
            calls.append(context)
            return {"summary": "Review the measured interval.", "coaching": [{
                "issueId": "pitch_change", "researchBasis": "Pitch was measured.",
                "recommendation": "목소리 때문에 스트레스가 증가했습니다.",
                "evidenceIds": context["issues"][0]["retrievedEvidenceIds"]}]}

        report = generate_report(request, rag=rag, decide=decide, synthesize=synthesize,
                                 agent_mode=True)
        self.assertEqual(len(calls), 2)
        self.assertIn("verificationErrors", calls[1])
        self.assertNotIn("스트레스가 증가", report["priorities"][0]["recommendation"])
        self.assertEqual(report["priorities"][0]["recommendation"], "")
        self.assertEqual(report["priorities"][0]["evidenceIds"], [])
        self.assertTrue(report["claimVerification"]["revisionAttempted"])
        self.assertIn("causal_or_psychological_claim",
                      report["claimVerification"]["initialErrors"]["coaching"]["pitch_change"])

    def test_interpretive_summary_is_revised_to_measured_fact_once(self):
        request = self.request()
        calls = []
        def decide(view):
            if not view["toolResults"]:
                return {"action": "analyze_segment", "candidateId": "pitch_change",
                        "segmentIds": ["high-1", "high-2"]}
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}
        def synthesize(context):
            calls.append(context)
            summary = ("새로운 억양적 특성으로 나타났습니다." if len(calls) == 1
                       else "00:30-00:50 구간에서 평균 목소리 높이가 앞선 구간보다 높았습니다.")
            return {"summary": summary, "coaching": [{
                "issueId": "pitch_change", "researchBasis": "", "recommendation": "녹음을 확인하세요.",
                "evidenceIds": []}]}
        report = generate_report(request, decide=decide, synthesize=synthesize, agent_mode=True)
        self.assertEqual(len(calls), 2)
        self.assertIn("interpretation_or_speech_content_not_measured",
                      report["claimVerification"]["initialErrors"]["summary"])
        self.assertFalse(report["claimVerification"]["finalErrors"]["summary"])
        self.assertTrue(report["summaryFallbackUsed"])
        self.assertIn("평균 목소리 높이", report["summaryText"])

    def test_unobserved_numeric_summary_is_replaced_after_one_failed_revision(self):
        request = self.request()
        calls = []
        def synthesize(context):
            calls.append(context)
            return {"summary": "00:30-00:40 구간 평균 목소리 높이가 999 Hz였습니다.",
                    "coaching": [{"issueId": item["id"], "recommendation": "녹음을 확인하세요.",
                                  "evidenceIds": []} for item in context["issues"]]}
        report = generate_report(request, synthesize=synthesize, agent_mode=True,
                                 decide=lambda view: ({"action": "analyze_segment", "candidateId": "pitch_change"}
                                                      if not view["toolResults"] else
                                                      {"action": "finish", "priorityCandidateIds": ["pitch_change"]}))
        self.assertEqual(len(calls), 2)
        self.assertTrue(report["claimVerification"]["revisionAttempted"])
        self.assertIn("hz_value_not_observed", report["claimVerification"]["finalErrors"]["summary"])
        self.assertTrue(report["summaryFallbackUsed"])
        self.assertNotIn("999", report["summaryText"])

    def test_brow_proxy_is_not_reported_as_observed_frown(self):
        request = ReviewRequest(sessionId="face", durationMs=20000, segments=[
            segment("face-1", 0, 10000, .82, audio=False, brow=.5),
            segment("face-2", 10000, 20000, .80, audio=False, brow=.45)])
        calls = []
        def synthesize(context):
            calls.append(context)
            return {"summary": "00:00-00:20 구간에서 눈썹을 찡그렸습니다.",
                    "coaching": [{"issueId": item["id"],
                                  "recommendation": "불안한 표정을 보였습니다.",
                                  "evidenceIds": []} for item in context["issues"]]}
        report = generate_report(request, synthesize=synthesize, agent_mode=True,
                                 decide=lambda view: ({"action": "analyze_segment", "candidateId": "brow_tension"}
                                                      if not view["toolResults"] else
                                                      {"action": "finish", "priorityCandidateIds": ["brow_tension"]}))
        self.assertEqual(len(calls), 2)
        self.assertIn("measurement_described_as_behavior_or_intent",
                      report["claimVerification"]["initialErrors"]["summary"])
        self.assertTrue(report["summaryFallbackUsed"])
        self.assertIn("눈썹 움직임 추정치", report["summaryText"])
        self.assertNotIn("찡그렸", report["summaryText"])
        self.assertEqual(report["priorities"][0]["practiceSuggestion"], "")

    def test_claim_guard_checks_exact_interval_pair_and_decimal(self):
        _, candidates = analyze_session(self.request())
        pitch = next(item for item in candidates if item["id"] == "pitch_change")
        self.assertIn("decimal_value_not_observed", _summary_errors(
            "모델 점수 0.99였습니다.", 50000, [pitch]))
        self.assertIn("speech_content_or_audience_not_observed", _summary_errors(
            "관객 조건 변화가 발표를 바꿨습니다.", 50000, [pitch]))
        self.assertIn("prosody_variation_not_measured", _summary_errors(
            "평균 목소리 높이와 운율 변화가 관찰됐습니다.", 50000, [pitch]))
        self.assertIn("measured_pitch_described_as_prediction", _summary_errors(
            "기계 학습이 예측한 이러한 변화입니다.", 50000, [pitch]))
        self.assertIn("unmeasured_whole_session_pitch_reference", _summary_errors(
            "평균 목소리 높이가 전체 세션보다 높았습니다.", 50000, [pitch]))
        self.assertIn("unsupported_psychological_causal_or_improvement_claim", _summary_errors(
            "이를 확인하면 발표 전달의 명확성을 높일 수 있습니다.", 50000, [pitch]))
        issue = {**pitch, "ranges": [{"startMs": 30000, "endMs": 40000},
                                      {"startMs": 50000, "endMs": 60000}],
                 "assessment": {"adviceMode": "review"}}
        item = SimpleNamespace(recommendation="00:30–01:00 구간을 확인하세요.", evidenceIds=[])
        self.assertIn("unverified_interval_pair",
                      _invalid_generated_text(item, issue, {}, True))
        item = SimpleNamespace(recommendation="설명 모드에서 목소리 높이를 확인하세요.", evidenceIds=[])
        self.assertIn("speech_content_or_audience_not_observed",
                      _invalid_generated_text(item, issue, {}, True))

    def test_low_coverage_finishes_without_inventing_a_priority(self):
        request = ReviewRequest(sessionId="short", durationMs=50000, sceneLabel="camera",
                                segments=[segment("high", 0, 10000, .9, brow=.7)])
        report = generate_report(request, decide=lambda _: self.fail("Should not plan"), agent_mode=True)
        self.assertEqual(report["agentRun"]["stopReason"], "insufficient_coverage")
        self.assertEqual(report["priorities"], [])

    def test_unverified_skill_improvement_is_removed_from_summary(self):
        def synthesize(context):
            return {"summary": "발표 실력이 좋아졌습니다.", "coaching": [
                {"issueId": item["id"], "recommendation": "Listen to the recording.", "evidenceIds": []}
                for item in context["issues"]]}
        report = generate_report(self.request(), synthesize=synthesize, agent_mode=True,
                                 decide=lambda view: ({"action": "analyze_segment", "candidateId": "pitch_change"}
                                                      if not view["toolResults"] else
                                                      {"action": "finish", "priorityCandidateIds": ["pitch_change"]}))
        self.assertTrue(report["summaryFallbackUsed"])
        self.assertNotIn("실력이 좋아", report["summaryText"])

    def test_memory_load_uses_user_token_and_structured_report_only(self):
        report = {"sessionId": "old", "agentMemory": {
            "sessionId": "old", "modelVersion": "v1", "metricDefinitionVersion": "session-analysis-v1",
            "sceneLabel": "camera", "durationMs": 50000,
            "candidates": [{"candidateId": "pitch_change", "metric": "f0_mean",
                            "observedValue": 180, "observationCount": 2, "measurementQuality": 1}],
            "focusGoal": {"candidateId": "pitch_change", "metric": "f0_mean",
                          "action": "untrusted user-authored text"}}}
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return [{"agent_report": report}]
        with patch("server.agent_memory.requests.get", return_value=Response()) as get:
            memory = load_recent_memory("https://example.supabase.co", "public", "secret", "user-1")
        self.assertEqual(memory["modelVersion"], "v1")
        self.assertNotIn("action", memory["focusGoal"])
        self.assertEqual(get.call_args.kwargs["params"]["user_id"], "eq.user-1")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer secret")

    def test_memory_load_preserves_multiple_valid_structured_sessions(self):
        def report(identity, value):
            return {"sessionId": identity, "agentMemory": {
                "sessionId": identity, "modelVersion": "v1", "metricDefinitionVersion": "session-analysis-v4",
                "sceneLabel": "camera", "durationMs": 50000,
                "candidates": [{"candidateId": "brow_tension", "metric": "brow_tension",
                                "observedValue": value, "observationCount": 2,
                                "measurementQuality": 1.0}], "focusGoal": None}}
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return [{"agent_report": report("recent", .2)},
                        {"agent_report": report("older", .4)}]
        with patch("server.agent_memory.requests.get", return_value=Response()):
            prior = load_recent_memory("https://example.supabase.co", "public", "secret", "user-1")
        self.assertEqual([item["sessionId"] for item in prior["history"]], ["recent", "older"])
        report_result = generate_report(self.request(), agent_mode=True,
                                        decide=lambda _: {"action": "finish", "priorityCandidateIds": []},
                                        prior_memory=prior, model_version="v1")
        comparison = report_result["observationReport"]["previousComparison"]
        self.assertEqual(comparison["previousSessionCount"], 2)
        self.assertEqual(comparison["previousValue"], .3)

    def test_generated_memory_survives_storage_loader_and_next_session(self):
        first_request = self.request()
        rag = ResearchRag()
        def first_decide(view):
            actions = view["toolResults"]
            if not actions:
                return {"action": "analyze_segment", "candidateId": "pitch_change"}
            if actions[-1]["action"] == "analyze_segment":
                return {"action": "retrieve_papers", "candidateId": "pitch_change",
                        "claimKind": "interpretation"}
            return {"action": "finish", "priorityCandidateIds": ["pitch_change"]}
        def synthesize(context):
            return {"summary": "Review the measured voice interval.", "coaching": [{
                "issueId": "pitch_change", "researchBasis": "Pitch was measured in presentations.",
                "recommendation": "Listen to the highlighted interval.",
                "evidenceIds": context["issues"][0]["retrievedEvidenceIds"][:1]}]}
        first = generate_report(first_request, rag=rag, decide=first_decide,
                                synthesize=synthesize, model_version="test-model", agent_mode=True)
        self.assertEqual(first["agentMemory"]["focusGoal"]["candidateId"], "pitch_change")

        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                return [{"agent_report": first}]

        with patch("server.agent_memory.requests.get", return_value=Response()):
            prior = load_recent_memory("https://example.supabase.co", "public", "secret", "user-1")
        self.assertEqual(prior["sessionId"], first["sessionId"])
        self.assertEqual(prior["focusGoal"]["candidateId"], "pitch_change")
        self.assertNotIn("action", prior["focusGoal"])
        second_request = first_request.model_copy(update={"sessionId": "current-2"})
        def second_decide(view):
            if not view["toolResults"]:
                self.assertIn("pitch_change", view["comparableCandidateIds"])
                return {"action": "compare_previous_session", "candidateId": "pitch_change"}
            return {"action": "finish", "priorityCandidateIds": []}
        second = generate_report(second_request, decide=second_decide, prior_memory=prior,
                                 model_version="test-model", agent_mode=True)
        self.assertEqual(second["sessionComparison"]["previousSessionId"], first["sessionId"])
        self.assertEqual(second["sessionComparison"]["difference"], 0)


if __name__ == "__main__":
    unittest.main()
