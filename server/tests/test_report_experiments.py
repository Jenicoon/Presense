"""AI may select a concrete comparison, never fabricate an interval or a treatment."""
import unittest
from unittest.mock import patch
from agent.report_schema import PracticeChoice
from agent.practice_experiments import experiment_for, choices_for
from agent.report_agent import generate_report
from agent.session_analyzer import analyze_session
from server.tests.test_feedback_selection import measured_request

class Papers:
    def retrieve_issue_evidence(self, identity, query, k=3):
        return [{'id':'measurement:1:0','source':'test-measurement.pdf','chunk':0,'text':'Jitter was an acoustic measurement in the recorded voice.','distance':.1,
                 'topics':[identity],'applicability':'direct','evidenceRole':'measurement','findingKo':'음성 녹음에서 지터를 음향 지표로 측정한 연구입니다.','scope':'Jitter measurement; no exercise effect was tested.'}]

class ReportExperiments(unittest.TestCase):
    def finding(self):
        req=measured_request(2)
        summary,candidates=analyze_session(req)
        return req,summary,[c for c in candidates if c['id']=='v2_jitter']

    def test_generated_report_has_verified_target_and_one_actionable_exercise(self):
        req,summary,candidates=self.finding()
        captured=[]
        def synth(context):
            issue=context['issues'][0];captured.append(issue)
            return {'summary':'기록된 구간의 음높이 미세 변동이 앞부분보다 컸습니다.','coaching':[{'issueId':issue['id'],
                'researchBasis':'지터를 음향 측정 지표로 사용한 연구입니다.','recommendation':'원본에서 비교할 문장을 본인이 고르고 끝 단어까지 구분되는지 들어보세요.',
                'evidenceIds':issue['retrievedEvidenceIds'],'practicePlan':{'strategyId':'clear_phrases','segmentId':issue['observations'][0]['segmentId'],
                'instructions':{'reason':'앞부분보다 음높이 미세 변동이 커진 구간을 비교하기 위해 선택했습니다.',
                    'goal':'본인이 고른 문장을 짧은 의미 단위로 나눠 비교하기',
                    'steps':['해당 구간에서 비교할 문장 하나를 고르세요.','같은 문장을 의미 단위로 나눠 말해 녹화하세요.','두 버전에서 마지막 단어까지 한 번에 구분되는지 들어보세요.'],
                    'question':'어느 버전에서 마지막 단어를 한 번에 구분할 수 있었나요?'}}}]}
        with patch('agent.report_agent.analyze_session',return_value=(summary,candidates)):
            report=generate_report(req,rag=Papers(),synthesize=synth,model_version=req.modelVersion,agent_mode=True)
        self.assertEqual(report['synthesisStatus'],'generated')
        issue=report['priorities'][0];plan=issue['practicePlan']
        self.assertEqual(plan['strategyId'],'clear_phrases')
        self.assertEqual(plan['language'],'ko')
        self.assertIn('미세 변동',plan['instructions']['reason'])
        target=next(row for row in issue['observations'] if row['segmentId']==plan['segmentId'])
        self.assertEqual((plan['startMs'],plan['endMs']),(target['startMs'],target['endMs']))
        self.assertTrue(issue['evidenceIds'])
        self.assertIn('clear_phrases',captured[0]['allowedPracticeChoices'])
        self.assertNotIn('expression',captured[0]['allowedPracticeChoices'])

    def test_nonexistent_target_and_unrelated_method_are_rejected(self):
        issue={'id':'v2_jitter','observations':[{'segmentId':'real','startMs':10000,'endMs':20000}]}
        for choice in [PracticeChoice(strategyId='clear_phrases',segmentId='invented'),PracticeChoice(strategyId='expression',segmentId='real')]:
            with self.assertRaises(ValueError):experiment_for(issue,choice)

    def test_stock_method_selection_without_authored_instructions_is_rejected(self):
        from agent.report_agent import _validate_synthesis
        issue={'id':'v2_jitter','observations':[{'segmentId':'real','startMs':10000,'endMs':20000}]}
        with self.assertRaisesRegex(ValueError,'AI-authored'):
            _validate_synthesis({'summary':'관측 구간입니다.','coaching':[{'issueId':'v2_jitter',
                'practicePlan':{'strategyId':'clear_phrases','segmentId':'real'}}]},[issue],{'v2_jitter':[]})

    def test_fabricated_time_inside_exercise_is_rejected(self):
        from agent.report_agent import _invalid_generated_text
        from agent.report_schema import CoachingItem
        item=CoachingItem(issueId='v2_jitter',recommendation='고른 구간의 마지막 단어까지 구분되는지 들어보세요.',
            practicePlan={'strategyId':'clear_phrases','segmentId':'real','instructions':{
                'reason':'앞부분과 비교해 미세 변동이 커진 구간입니다.', 'goal':'고른 문장의 끝 단어 비교하기',
                'steps':['99:00–99:10 구간을 재생하세요.','같은 문장의 마지막 단어까지 구분되는지 비교하세요.'],
                'question':'마지막 단어가 어느 버전에서 구분됐나요?'}})
        issue={'id':'v2_jitter','ranges':[{'startMs':30000,'endMs':40000}],
               'predictionConfidence':.8,'measurementQuality':1,'independentObservations':3,'assessment':{'adviceMode':'review'}}
        self.assertIn('exercise_unverified_interval',_invalid_generated_text(item,issue,{},True))

    def test_presenter_selection_and_keeping_current_delivery_are_not_invented_observations(self):
        from types import SimpleNamespace
        from agent.report_agent import _invalid_generated_text
        issue={'id':'v2_mean_f0','ranges':[{'startMs':30000,'endMs':40000}],
               'predictionConfidence':.8,'measurementQuality':1,'independentObservations':3,'assessment':{'adviceMode':'review'}}
        selected=SimpleNamespace(recommendation='핵심 단어 하나를 고르세요. 그 단어가 구분돼 들린다면 현재 목소리 변화를 유지하세요.',evidenceIds=[])
        self.assertEqual(_invalid_generated_text(selected,issue,{},True),[])
        invented=SimpleNamespace(recommendation='핵심 단어가 명확하지 않았습니다.',evidenceIds=[])
        self.assertIn('speech_content_or_audience_not_observed',_invalid_generated_text(invented,issue,{},True))

    def test_actual_ten_second_observation_is_valid_inside_a_merged_finding_range(self):
        from types import SimpleNamespace
        from agent.report_agent import _invalid_generated_text
        issue={'id':'v2_mean_f0','ranges':[{'startMs':30000,'endMs':60000}],
               'observations':[{'segmentId':'real','startMs':30000,'endMs':40000}],
               'predictionConfidence':.8,'measurementQuality':1,'independentObservations':3,'assessment':{'adviceMode':'review'}}
        item=SimpleNamespace(recommendation='00:30–00:40 구간을 다시 들어보세요.',evidenceIds=[])
        self.assertEqual(_invalid_generated_text(item,issue,{},True),[])

    def test_each_available_exercise_has_steps_and_a_single_comparison_question(self):
        for identity in ['pitch_change','v2_jitter','v2_shimmer','v2_hnr','v2_mean_f0','v2_brow_down','v2_eye_squint','v2_jaw_open','gaze']:
            for method in choices_for({'id':identity}).values():
                self.assertEqual(len(method['steps']),3)
                for lang in [0,1]:
                    self.assertTrue(method['goal'][lang]);self.assertTrue(method['question'][lang].endswith('?'))
                    self.assertTrue(all(step[lang] for step in method['steps']))

    def test_local_research_index_can_open_with_runtime_dependencies(self):
        from tempfile import TemporaryDirectory
        from agent.rag_db import PaperRAG
        with TemporaryDirectory() as directory:
            rag=PaperRAG(db_path=directory,sync=False)
            self.assertEqual(rag._collection.count(),0)

    def test_vague_vocal_advice_needs_an_observable_listening_criterion(self):
        from types import SimpleNamespace
        from agent.report_agent import _invalid_generated_text
        issue={'id':'v2_jitter','ranges':[{'startMs':30000,'endMs':40000}],
               'predictionConfidence':.8,'measurementQuality':1,'independentObservations':3,'assessment':{'adviceMode':'review'}}
        vague=SimpleNamespace(recommendation='발성의 안정성을 확인하고 더 안정적인 버전을 선택하세요.',evidenceIds=[])
        concrete=SimpleNamespace(recommendation='문장 끝 단어를 한 번에 구분할 수 있는지 들어보세요.',evidenceIds=[])
        self.assertIn('vague_listening_criterion',_invalid_generated_text(vague,issue,{},True))
        self.assertNotIn('vague_listening_criterion',_invalid_generated_text(concrete,issue,{},True))
