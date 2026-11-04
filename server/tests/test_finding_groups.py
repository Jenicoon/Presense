"""Regression coverage for coherent interval groups and legacy references. No external AI."""
import unittest
from copy import deepcopy

from agent.finding_groups import repeated_group_reason
from agent.finding_evidence import complete_document_evidence
from agent.decision_agent import run_agent
from agent.report_schema import ReviewRequest
from agent.session_analyzer import analyze_session
from server.tests.test_agent_report import segment
from server.tests.test_coaching import document


def rows(values):
    return [{"startMs": n * 10000, "endMs": (n+1) * 10000, "value": value}
            for n, value in enumerate(values)]


class FindingGroupTests(unittest.TestCase):
    def test_mixed_directions_and_near_reference_are_not_repetition(self):
        self.assertEqual(repeated_group_reason(rows([.52,.2,.41]),.24,"energy"),"mixed_directions")
        self.assertEqual(repeated_group_reason(rows([.52,.25]),.24,"energy"),"includes_reference_like_observation")
        self.assertEqual(repeated_group_reason(rows([.52,.28]),.24,"energy"),"dissimilar_changes")

    def test_consistent_higher_and_lower_changes_are_allowed(self):
        for values in ([.52,.50],[.12,.10]):
            self.assertIsNone(repeated_group_reason(rows(values),.24,"energy"))

    def test_overlap_and_missing_reference_are_not_evidence_of_repetition(self):
        overlapping=rows([.52,.50]); overlapping[1]["startMs"]=5000
        self.assertEqual(repeated_group_reason(overlapping,.24,"energy"),"overlapping_observations")
        self.assertEqual(repeated_group_reason(rows([.52,.50]),None,"energy"),"missing_reference")

    def test_legacy_group_is_kept_as_individual_references_without_changing_source(self):
        doc=document()
        finding=doc["snapshot"]["report"]["priorities"][0]
        finding["modality"]="audio"; finding["metric"]="energy_variability"
        finding["id"]="audio:energy_variability"; finding["selectedSegmentIds"]=["s2","s3","s4"]
        for row,value in zip(doc["snapshot"]["request"]["segments"],[.24,.24,.52,.20,.41]):
            row["audioFeatures"]["energy_variability"]=value
        original=deepcopy(doc)
        normalized=complete_document_evidence(doc)
        self.assertEqual(normalized["snapshot"]["report"]["priorities"],[])
        reference=normalized["snapshot"]["report"]["referenceFindings"][0]
        self.assertEqual(reference["groupingReason"],"mixed_directions")
        self.assertEqual([row["value"] for row in reference["observations"]],[.52,.20,.41])
        self.assertEqual(doc,original)
        self.assertEqual(complete_document_evidence(normalized),normalized)

    def test_new_agent_cannot_finish_with_mixed_group_and_can_reselect(self):
        windows=[segment(f"s{n}",n*10000,(n+1)*10000,.5) for n in range(5)]
        for row,value in zip(windows,[.24,.24,.52,.20,.50]):
            row["audioFeatures"]["energy_variability"]=value
        request=ReviewRequest(sessionId="synthetic-grouping",durationMs=50000,segments=windows)
        summary,candidates=analyze_session(request)
        def decide(view):
            if not view["toolResults"]:
                return {"action":"analyze_segment","candidateId":"audio:energy_variability","segmentIds":["s2","s3","s4"]}
            if view["decisionErrors"]:
                return {"action":"analyze_segment","candidateId":"audio:energy_variability","segmentIds":["s2","s4"]}
            return {"action":"finish","priorityCandidateIds":["audio:energy_variability"]}
        state=run_agent(request,summary,candidates,decide=decide,decision_provider="luxia")
        rejected=[proposal["reason"] for decision in state.decisions for proposal in decision["proposals"] if proposal["serverValidation"]=="rejected"]
        self.assertTrue(any("mixed_directions" in reason for reason in rejected))
        self.assertEqual(state.selected_ids,["audio:energy_variability"])
        self.assertEqual([row["segmentId"] for row in state.candidate("audio:energy_variability")["observations"]],["s2","s4"])

    def test_unsupported_legacy_candidate_is_not_in_chat_fact_catalog(self):
        from agent.coach_ai import build_context
        from agent.coaching import CoachRequest
        doc=document()
        finding=doc["snapshot"]["report"]["priorities"][0]
        finding.pop("metric"); finding.pop("modality")
        normalized=complete_document_evidence(doc)
        context=build_context(normalized,CoachRequest(sessionId="baseline",action="review"))
        self.assertEqual(context["findings"],[])
        self.assertTrue(normalized["snapshot"]["report"]["referenceFindings"])

class DistinctFindingTests(unittest.TestCase):
    def request(self, pitch=170, baseline=(120,121,119), quality=True):
        windows=[segment(f"s{n}",n*10000,(n+1)*10000,.3,pitch=value)
                 for n,value in enumerate([*baseline,pitch])]
        windows[-1]["stressScore"]=.99
        windows[-1]["quality"]["audioValid"]=quality
        return ReviewRequest(sessionId="single-synthetic",durationMs=40000,segments=windows)

    def test_distinctness_uses_measurement_and_reference_range_not_stress_score(self):
        from agent.finding_groups import finding_kind
        for value in (170,80):
            self.assertEqual(finding_kind(rows([value]),120,"f0_mean",[120,121,119]),"distinct")
        for value, earlier in ((120,[120,121,119]),(125,[120,121,119]),(170,[100,120,160]),(170,[120,120])):
            self.assertIsNone(finding_kind(rows([value]),120,"f0_mean",earlier))

    def test_agent_can_choose_one_distinct_interval(self):
        request=self.request()
        summary,candidates=analyze_session(request)
        def decide(view):
            if not view["toolResults"]:
                return {"action":"analyze_segment","candidateId":"pitch_change","segmentIds":["s3"]}
            self.assertIn("pitch_change",view["finishEligibleCandidateIds"])
            self.assertIsNone(view["weakMeasurementContext"])
            return {"action":"finish","priorityCandidateIds":["pitch_change"]}
        state=run_agent(request,summary,candidates,decide=decide,decision_provider="luxia")
        self.assertEqual(state.selected_ids,["pitch_change"])
        self.assertEqual(state.candidate("pitch_change")["findingKind"],"distinct")
        self.assertEqual(state.actions[0]["result"]["independentObservations"],1)

    def test_report_restore_and_coaching_preserve_a_single_distinct_finding(self):
        from agent.report_agent import generate_report
        from agent.coaching import new_document, CoachRequest, respond
        from agent.coach_ai import build_context
        request=self.request()
        report=generate_report(request,agent_mode=True,model_version="synthetic-model")
        self.assertEqual(report["priorities"][0]["findingKind"],"distinct")
        doc=complete_document_evidence(new_document(request,report,"synthetic-model"))
        finding=doc["snapshot"]["report"]["priorities"][0]
        self.assertEqual(finding["findingKind"],"distinct")
        self.assertEqual(len(finding["observations"]),1)
        context=build_context(doc,CoachRequest(sessionId=request.sessionId,action="review"))
        self.assertEqual(context["findings"][0]["findingKind"],"distinct")
        _,response=respond(doc,CoachRequest(sessionId=request.sessionId,action="review"))
        self.assertTrue(any(component["type"]=="finding" for component in response["components"]))

    def test_noisy_reference_flat_measurement_and_bad_audio_do_not_create_single_findings(self):
        from agent.report_agent import generate_report
        for request in (self.request(120),self.request(170,baseline=(100,120,160)),self.request(170,quality=False)):
            report=generate_report(request,agent_mode=True,model_version="synthetic-model")
            self.assertFalse(any(f.get("findingKind")=="distinct" for f in report["priorities"]))

    def test_a_single_concept_prediction_without_a_measurement_cannot_be_distinct(self):
        request=self.request(120)
        for index,row in enumerate(request.segments):
            row.concepts["음성 피치"] = .9 if index==3 else .4
        summary,candidates=analyze_session(request)
        def decide(view):
            if not view["toolResults"]:
                return {"action":"analyze_segment","candidateId":"concept:음성 피치","segmentIds":["s3"]}
            return {"action":"finish","priorityCandidateIds":[]}
        state=run_agent(request,summary,candidates,decide=decide,decision_provider="luxia")
        self.assertIsNone(state.candidate("concept:음성 피치")["findingKind"])
        self.assertEqual(state.selected_ids,[])

if __name__ == "__main__":
    unittest.main()
