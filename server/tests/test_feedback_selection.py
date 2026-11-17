"""Finding count follows verified evidence, never a three-item or two-item quota."""
import unittest
from agent.model_contract import RAW_METRICS
from agent.report_agent import generate_report
from agent.report_schema import ReviewRequest, Synthesis
from agent.coaching import CoachRequest, new_document, respond
from agent.coach_ai import build_context
from agent.report_feedback import context_for
from ai.concept_registry import PROPOSED_CONCEPTS_V2
from server.tests.test_concept_v2 import request


def measured_request(changed_count):
    data = request().model_dump()
    baseline = [20, .01, .5, 20, .1, .2, .3]
    changed = [30, .03, 1, 10, .4, .5, .6]
    for n, row in enumerate(data['segments']):
        for i, (modality, key, _, _) in enumerate(RAW_METRICS):
            row[modality+'Features'][key] = changed[i] if n >= 3 and i < changed_count else baseline[i]
    return ReviewRequest.model_validate(data)


class EvidenceDrivenFindingCount(unittest.TestCase):
    def report(self, count):
        req = measured_request(count)
        return req, generate_report(req, model_version=req.modelVersion, agent_mode=True)

    def test_five_or_seven_verified_changes_are_all_reported(self):
        for count in [5, 7]:
            with self.subTest(count=count):
                _, report = self.report(count)
                self.assertEqual({f['id'] for f in report['priorities']}, {row[2] for row in RAW_METRICS[:count]})
                self.assertTrue(all(f['observations'] for f in report['priorities']))

    def test_one_change_stays_one_and_a_stable_session_stays_empty(self):
        for count in [0, 1]:
            with self.subTest(count=count):
                _, report = self.report(count)
                self.assertEqual(len(report['priorities']), count)

    def test_coach_can_select_and_explain_the_seventh_finding(self):
        req, report = self.report(7)
        doc = new_document(req, report, req.modelVersion)
        last = report['priorities'][-1]['id']
        action = CoachRequest(sessionId=req.sessionId, action='show_measurements', findingId=last)
        updated, reply = respond(doc, action)
        self.assertEqual(updated['state']['selectedFindingId'], last)
        context = build_context(doc, action)
        self.assertTrue(any(last in key for key in context['facts']))

    def test_synthesis_can_cover_every_supplied_issue(self):
        result = Synthesis(summary='Verified changes.', coaching=[{'issueId':row[2]} for row in RAW_METRICS])
        self.assertEqual(len(result.coaching), 7)

    def test_within_session_stress_turn_locates_a_coobserved_measurement_change(self):
        data = request().model_dump()
        stress = [.78, .72, .62, .65, .73, .80]
        eye_name = PROPOSED_CONCEPTS_V2[5].model_name_ko
        for index, row in enumerate(data['segments']):
            row['stressScore'] = stress[index]
            for modality, key, _, _ in RAW_METRICS:
                row[modality + 'Features'][key] = (20 if key == 'egemap_f0_semitone' else .2)
            row['videoFeatures']['eye_squint'] = .2 if index < 4 else .4
            row['concepts'] = {concept.model_name_ko: .4 for concept in PROPOSED_CONCEPTS_V2}
            row['concepts'][eye_name] = .25 if index < 4 else .7
        req = ReviewRequest.model_validate(data)
        report = generate_report(req, model_version=req.modelVersion, agent_mode=True)
        self.assertEqual([item['id'] for item in report['priorities']], ['v2_eye_squint'])
        finding = report['priorities'][0]
        self.assertEqual(finding['selectionBasis'], 'stress_guided_within_session_change')
        self.assertGreater(finding['stressContext']['signalDifference'], 0)
        self.assertEqual(finding['relatedConcepts'][0]['name'], eye_name)
        self.assertIn('analyze_concept', [row['action'] for row in report['agentRun']['actions']])

        feedback_context = context_for(req, report)
        supplied = feedback_context['findings'][0]
        self.assertEqual(supplied['stressContext']['role'], 'stress_signal_located_measurement_review')
        concept_fact = supplied['relatedConcepts'][0]['factId']
        self.assertIn(concept_fact, feedback_context['facts'])
        self.assertIn('같은 관측 구간', feedback_context['facts'][concept_fact]['ko'])
        document = new_document(req, report, req.modelVersion)
        coaching_context = build_context(document, CoachRequest(
            sessionId=req.sessionId, action='show_measurements', findingId='v2_eye_squint'))
        self.assertIn('같은 구간의 눈꺼풀 조임 움직임',
                      coaching_context['facts']['finding.v2_eye_squint']['ko'])

    def test_stress_turn_without_a_measured_feature_change_does_not_create_feedback(self):
        data = request().model_dump()
        stress = [.78, .72, .62, .65, .73, .80]
        for index, row in enumerate(data['segments']):
            row['stressScore'] = stress[index]
            for modality, key, _, _ in RAW_METRICS:
                row[modality + 'Features'][key] = (20 if key == 'egemap_f0_semitone' else .2)
            row['concepts'] = {concept.model_name_ko: .4 for concept in PROPOSED_CONCEPTS_V2}
        req = ReviewRequest.model_validate(data)
        report = generate_report(req, model_version=req.modelVersion, agent_mode=True)
        self.assertEqual(report['priorities'], [])
