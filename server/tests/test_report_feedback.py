import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from agent.report_feedback import ReportFeedbackAgent, VERSION, context_for, validate_draft
from agent.provider_privacy import minimized_context, external_ai_allowed
from server.coaching_store import can_refresh_report


def fixture():
    request=SimpleNamespace(durationMs=40000,baselineSource='synthetic',language='ko',sessionId='private-session',externalAiConsent=False)
    report={'sessionId':request.sessionId,'analysis':{'observedMs':40000},'agentRun':{'stopReason':'finished'},'evidence':[],
        'priorities':[{'id':'pitch_change','label':'평균 목소리 높이 / Mean voice pitch','metric':'f0_mean','modality':'audio',
            'referenceValue':120,'measurementQuality':1,'predictionConfidence':.8,'independentObservations':1,'findingKind':'distinct',
            'observations':[{'segmentId':'private-segment','startMs':30000,'endMs':40000,'value':180}]}]}
    draft={'summary':{'ko':'{{fact:session}} 목소리 높이 변화는 녹음을 확인할 단서입니다.','en':'{{fact:session}} A pitch change is a cue for reviewing the recording.'},
        'limitations':{'ko':'비교 가능한 이전 기록은 제공되지 않았습니다.','en':'No comparable previous recording was supplied.'},
        'items':[{'findingId':'pitch_change','segmentIds':['private-segment'],
            'explanation':{'ko':'{{fact:finding0.observation0}} 의도한 강조인지 확인할 가치가 있습니다.','en':'{{fact:finding0.observation0}} Check whether this matches the intended emphasis.'},
            'review':{'ko':'앞부분과 이어 듣고 의도한 강조인지 확인하세요.','en':'Listen alongside the opening and check the intended emphasis.'},
            'paperIds':[], 'practice':{'strategyId':'contrast','segmentId':'private-segment',
                'reason':{'ko':'{{fact:finding0.observation0}} 높이를 고정하지 않고 선택한 강조를 비교합니다.','en':'{{fact:finding0.observation0}} Compare chosen emphasis without fixing pitch.'},
                'goal':{'ko':'직접 고른 단어의 강조를 비교하기','en':'Compare emphasis on a word you choose'},
                'steps':[{'ko':'해당 구간에서 직접 문장을 고르세요.','en':'Choose a sentence from that interval.'},
                         {'ko':'중요한 단어에 강조를 주어 다시 말하세요.','en':'Repeat it with emphasis on your chosen word.'}],
                'question':{'ko':'의도한 강조가 구분되나요?','en':'Is the intended emphasis distinct?'}}}]}
    return request,report,draft


class ReportFeedbackTests(unittest.TestCase):
    def test_independent_report_without_chat_or_papers(self):
        request,report,draft=fixture()
        before=deepcopy(report)
        result=ReportFeedbackAgent(lambda _:draft,lambda _:{'supported':True}).run(request,report)
        self.assertEqual(result['reportFeedback']['status'],'ready')
        self.assertIn('00:30–00:40',result['reportFeedback']['items'][0]['explanation']['ko'])
        self.assertEqual(report,before)
        self.assertNotIn('messages',result)
        self.assertEqual(result['reportFeedback']['items'][0]['practice']['strategyId'],'contrast')

    def test_partial_retry_preserves_accepted_items_and_only_composes_failed_finding(self):
        request,report,draft=fixture()
        second=deepcopy(report['priorities'][0]);second.update(id='pitch_variability',metric='f0_std')
        report['priorities'].append(second)
        def generate(context):
            value=deepcopy(draft)
            value['items'][0]['findingId']=context['findings'][0]['id']
            value['items'][0]['explanation']={'ko':'이 변화는 녹화를 확인할 단서입니다.','en':'This change is a cue to review the recording.'}
            value['items'][0]['practice']=None
            if context['findings'][0]['id']=='pitch_variability':value['items'][0]['review']['en']='99:99'
            return value
        partial=ReportFeedbackAgent(generate,lambda _:{'supported':True}).run(request,report)
        self.assertEqual(partial['reportFeedback']['status'],'partial')
        first=partial['reportFeedback']['items'][0]
        calls=[]
        def repair(context):
            calls.append(context['findings'][0]['id'])
            value=deepcopy(draft);value['items'][0]['findingId']='pitch_variability'
            value['items'][0]['explanation']={'ko':'변화의 쓰임을 녹화로 확인하세요.','en':'Review how this change is used in the recording.'}
            value['items'][0]['practice']=None
            return value
        ready=ReportFeedbackAgent(repair,lambda _:{'supported':True}).run(request,partial)
        self.assertEqual(calls,['pitch_variability'])
        self.assertEqual(ready['reportFeedback']['status'],'ready')
        self.assertEqual(ready['reportFeedback']['items'][0],first)

    def test_no_fixed_task_when_stable(self):
        request,report,draft=fixture(); report['priorities']=[]; draft['items']=[]
        result=ReportFeedbackAgent(lambda _:draft,lambda _:{'supported':True}).run(request,report)
        self.assertEqual(result['reportFeedback']['status'],'ready')
        self.assertEqual(result['reportFeedback']['items'],[])

    def test_generic_disclaimer_is_not_required_when_there_is_no_specific_limit(self):
        request,report,draft=fixture(); draft['limitations']=None
        result=ReportFeedbackAgent(lambda _:draft,lambda _:{'supported':True}).run(request,report)
        self.assertEqual(result['reportFeedback']['status'],'ready')
        self.assertIsNone(result['reportFeedback']['limitations'])

    def test_stress_guided_feedback_must_use_related_concept_not_stress_conclusion(self):
        request,report,draft=fixture()
        report['priorities'][0]['selectionBasis']='stress_guided_within_session_change'
        report['priorities'][0]['stressContext']={'role':'stress_signal_located_measurement_review'}
        report['priorities'][0]['relatedConcepts']=[{
            'name':'평균 음성 높이','meanPrediction':.7,'referencePrediction':.3}]
        context=context_for(request,report)
        draft['summary']={'ko':'평균 목소리 높이의 변화가 확인할 구간을 만들었습니다.',
                          'en':'A mean voice-pitch change marks an interval to review.'}
        draft['items'][0]['explanation']={
            'ko':'스트레스 신호가 상승해 확인할 가치가 있습니다.',
            'en':'The stress signal rose, so this is worth reviewing.'}
        with self.assertRaisesRegex(ValueError,'Stress may locate'):
            validate_draft(draft,context)
        concept_id=context['findings'][0]['relatedConcepts'][0]['factId']
        draft['items'][0]['explanation']={
            'ko':'선택한 문장의 강조와 맞는지 확인하세요.',
            'en':'Check whether it matches your intended emphasis.'}
        checked=validate_draft(draft,context)
        self.assertIn(f'{{{{fact:{concept_id}}}}}',checked.items[0].explanation.ko)
        self.assertIn(f'{{{{fact:{concept_id}}}}}',checked.items[0].explanation.en)
        broken=deepcopy(draft)
        broken['items'][0]['review']={'ko':'같은 구간의 눈썹 내림 움직임도 확인하세요.',
                                      'en':'Also review brow lowering movement in the same interval.'}
        with self.assertRaisesRegex(ValueError,'unselected measurement'):
            validate_draft(broken,context)

    def test_real_stable_session_gets_grounded_positive_review_without_correction(self):
        request,report,draft=fixture(); request.baselineSource='preparation'; report['priorities']=[]
        report['observationReport']={'features':[{'id':'v2_mean_f0','label':'평균 목소리 높이 / Mean voice pitch',
            'meanValue':24,'minValue':22,'maxValue':26,'unit':'semitones','observations':4}]}
        draft['summary']={'ko':'{{fact:selection}} 이번 발표의 측정 결과를 다음 녹화의 비교 기준으로 사용할 수 있습니다.',
                          'en':'{{fact:selection}} This session can provide a comparison reference for the next recording.'}
        draft['items']=[]
        draft['strengths']=[{'ko':'{{fact:measurement0}} 이 범위가 의도와 맞았다면 다음 발표에서 이어갈 기준점입니다.',
                             'en':'{{fact:measurement0}} If this range matched your intent, it is a reference to carry forward.'}]
        draft['nextReview']={'ko':'다음 발표에서 직접 고른 핵심 문장 하나에만 평균 목소리 높이 변화를 주어 다시 녹화하세요. 현재 발표와 평균 목소리 높이 측정값을 비교하고, 영상에서 의도한 강조로 들리는지는 별도로 확인하세요.',
                             'en':'In the next presentation, choose one key sentence and record it with a deliberate Mean voice pitch change. Compare the measurement with this session, then separately review whether the recording sounds like the emphasis you intended.'}
        def verifier_must_not_run(_): self.fail('Stable no-finding feedback uses deterministic grounding validation')
        result=ReportFeedbackAgent(lambda _:draft,verifier_must_not_run).run(request,report)
        self.assertEqual(result['reportFeedback']['version'],VERSION)
        self.assertEqual(result['reportFeedback']['items'],[])
        self.assertEqual(len(result['reportFeedback']['strengths']),1)
        self.assertIn('평균 목소리 높이',result['reportFeedback']['strengths'][0]['ko'])

    def test_real_stable_session_rejects_generic_replay_instruction(self):
        request,report,draft=fixture(); request.baselineSource='preparation'; report['priorities']=[]
        report['observationReport']={'features':[{'id':'v2_mean_f0','label':'평균 목소리 높이 / Mean voice pitch',
            'meanValue':24,'minValue':22,'maxValue':26,'unit':'semitones','observations':4}]}
        context=context_for(request,report)
        draft['summary']={'ko':'{{fact:selection}} 다음 녹화와 비교할 기준을 남겼습니다.',
                          'en':'{{fact:selection}} This leaves a reference for the next recording.'}
        draft['items']=[]
        draft['strengths']=[{'ko':'{{fact:measurement0}} 의도와 맞았다면 다음 발표의 기준으로 이어갈 수 있습니다.',
                             'en':'{{fact:measurement0}} This can serve as a reference for the next presentation if it matched your intent.'}]
        draft['nextReview']={'ko':'영상을 다시 확인하세요.','en':'Replay the recording.'}
        with self.assertRaisesRegex(ValueError,'same supplied measurement|preservation experiment'):
            validate_draft(draft,context)

    def test_real_recording_cannot_be_described_as_synthetic_or_nonexistent(self):
        request,report,draft=fixture(); request.baselineSource='preparation'; report['priorities']=[]
        report['observationReport']={'features':[{'id':'v2_mean_f0','label':'평균 목소리 높이 / Mean voice pitch',
            'meanValue':24,'minValue':22,'maxValue':26,'unit':'semitones','observations':4}]}
        context=context_for(request,report)
        draft['summary']={'ko':'{{fact:selection}} 다음 녹화와 비교할 기준을 남겼습니다.',
                          'en':'{{fact:selection}} This leaves a reference for the next recording.'}
        draft['items']=[]
        draft['strengths']=[{'ko':'{{fact:measurement0}} 의도와 맞았다면 이어갈 후보입니다.',
                             'en':'{{fact:measurement0}} This is worth carrying forward if it matched your intent.'}]
        draft['nextReview']={'ko':'평균 목소리 높이 측정값을 비교할 문장을 고르고 다시 녹화한 뒤, 영상에서 의도대로 들리는지 비교하세요.',
                             'en':'Choose a sentence for a Mean voice pitch measurement comparison, record it again, and compare separately whether it sounds as intended in the recording.'}
        draft['limitations']['ko']='실제 녹화나 참가자가 존재하지 않습니다.'
        draft['limitations']['en']='No actual recording or participant exists.'
        with self.assertRaisesRegex(ValueError,'user recording'):
            validate_draft(draft,context)

    def test_positive_feedback_cannot_invent_audience_or_delivery_benefit(self):
        request,report,draft=fixture(); request.baselineSource='preparation'; report['priorities']=[]
        report['observationReport']={'features':[{'id':'v2_mean_f0','label':'평균 목소리 높이 / Mean voice pitch',
            'meanValue':24,'minValue':22,'maxValue':26,'unit':'semitones','observations':4}]}
        context=context_for(request,report)
        draft['summary']={'ko':'{{fact:selection}} 다음 녹화와 비교할 기준을 남겼습니다.',
                          'en':'{{fact:selection}} This leaves a reference for the next recording.'}
        draft['items']=[]
        draft['strengths']=[{'ko':'{{fact:measurement0}} 목소리가 일정해서 청중의 집중 향상에 도움이 됩니다.',
                             'en':'{{fact:measurement0}} Consistent pitch helps improve audience focus and delivery clarity.'}]
        draft['nextReview']={'ko':'평균 목소리 높이 측정값을 비교할 문장을 고르고 다시 녹화한 뒤, 영상에서 의도대로 들리는지 비교하세요.',
                             'en':'Choose a sentence for a Mean voice pitch measurement comparison, record it again, and compare separately whether it sounds as intended in the recording.'}
        with self.assertRaisesRegex(ValueError,'audience'):
            validate_draft(draft,context)

        draft['strengths']=[{'ko':'{{fact:measurement0}} 측정된 변화가 작아서 평온한 전달로 들립니다.',
                             'en':'{{fact:measurement0}} The small measured changes indicate calm, natural delivery.'}]
        with self.assertRaisesRegex(ValueError,'Positive feedback|strength'):
            validate_draft(draft,context)

    def test_real_stable_session_rejects_universal_stability_claim(self):
        request,report,draft=fixture(); request.baselineSource='preparation'; report['priorities']=[]
        report['observationReport']={'features':[{'id':'v2_mean_f0','label':'평균 목소리 높이 / Mean voice pitch',
            'meanValue':24,'minValue':22,'maxValue':26,'unit':'semitones','observations':4}]}
        context=context_for(request,report)
        draft['summary']={'ko':'{{fact:selection}} 모든 측정 지표가 안정적으로 유지되었습니다.',
                          'en':'{{fact:selection}} All measured metrics remained stable.'}
        draft['items']=[]
        draft['strengths']=[{'ko':'{{fact:measurement0}} 의도와 맞았다면 이어갈 기준입니다.',
                             'en':'{{fact:measurement0}} This is a reference to carry forward if it matched your intent.'}]
        draft['nextReview']={'ko':'평균 목소리 높이 측정값을 비교할 문장을 고르고 다시 녹화한 뒤, 영상에서 의도대로 들리는지 비교하세요.',
                             'en':'Choose a sentence for a Mean voice pitch measurement comparison, record it again, and compare separately whether it sounds as intended in the recording.'}
        with self.assertRaisesRegex(ValueError,'all measurements'):
            validate_draft(draft,context)

    def test_rendered_selection_fact_is_not_repeated_verbatim(self):
        request,report,draft=fixture(); request.baselineSource='preparation'; report['priorities']=[]
        report['observationReport']={'features':[{'id':'v2_mean_f0','label':'평균 목소리 높이 / Mean voice pitch',
            'meanValue':24,'minValue':22,'maxValue':26,'unit':'semitones','observations':4}]}
        repeated_ko='측정 품질과 비교 기준을 적용한 결과, 교정 과제로 연결할 만큼 근거가 충분한 반복 변화나 단일 두드러진 변화는 선택되지 않았습니다.'
        repeated_en='After applying measurement-quality and comparison checks, no repeated or single prominent change had enough support to become a correction task.'
        draft['summary']={'ko':'{{fact:selection}} '+repeated_ko,'en':'{{fact:selection}} '+repeated_en}
        draft['items']=[]
        draft['strengths']=[{'ko':'{{fact:measurement0}} 의도와 맞았다면 이어갈 기준입니다.',
                             'en':'{{fact:measurement0}} This is a reference to carry forward if it matched your intent.'}]
        draft['nextReview']={'ko':'평균 목소리 높이 측정값을 비교할 문장을 고르고 다시 녹화한 뒤, 영상에서 의도대로 들리는지 비교하세요.',
                             'en':'Choose a sentence for a Mean voice pitch measurement comparison, record it again, and compare separately whether it sounds as intended in the recording.'}
        result=ReportFeedbackAgent(lambda _:draft,lambda _:self.fail('No semantic verifier for stable feedback')).run(request,report)
        self.assertEqual(result['reportFeedback']['summary']['ko'].count(repeated_ko),1)
        self.assertEqual(result['reportFeedback']['summary']['en'].count(repeated_en),1)

    def test_nonexistent_times_values_segments_and_findings_rejected(self):
        request,report,draft=fixture();context=context_for(request,report)
        for field,value in [('findingId','nonexistent'),('segmentIds',['fake'])]:
            broken=deepcopy(draft);broken['items'][0][field]=value
            with self.assertRaises(ValueError):validate_draft(broken,context)

    def test_exact_observed_interval_duration_is_not_treated_as_an_invented_value(self):
        request,report,draft=fixture();context=context_for(request,report)
        draft['items'][0]['explanation']['ko']='관측된 마지막 10초의 변화가 의도한 강조인지 확인하세요.'
        draft['items'][0]['explanation']['en']='Check whether the change in the final 10 seconds matched the intended emphasis.'
        validate_draft(draft,context)
        for text in ['00:35','999 Hz','{{fact:fake}}']:
            broken=deepcopy(draft);broken['items'][0]['review']['en']=text
            with self.assertRaises(ValueError):validate_draft(broken,context)

    def test_provider_and_semantic_failure_are_explicit(self):
        request,report,draft=fixture()
        result=ReportFeedbackAgent(lambda _:draft,lambda _:{'supported':False,'reason':'invented emotion'}).run(request,report)
        self.assertEqual(result['reportFeedback']['status'],'failed')
        self.assertNotIn('summary',result['reportFeedback'])
        self.assertEqual(result['status'],'limited')
        self.assertEqual(result['priorities'],report['priorities'])

    def test_selection_failure_not_stable(self):
        request,report,draft=fixture();report['agentRun']['stopReason']='decision_unavailable'
        def unexpected(_):self.fail('Writer must wait for selection retry')
        result=ReportFeedbackAgent(unexpected,unexpected).run(request,report)
        self.assertEqual(result['reportFeedback']['failedStage'],'selection')

    def test_privacy_non_uuid_ids_no_media_no_filenames(self):
        safe,restore=minimized_context({'sessionId':'private-session','segmentId':'private-segment','sceneLabel':'my name',
            'email':'private@example.com','frames':[1], 'request':{'externalAiConsent':True},
            'evidence':[{'id':'paper','source':'private.pdf','articleUrl':'https://doi.org/test','text':'word '*100}],
            'responseSchema':{'enum':['private-segment']}})
        import json
        serialized=json.dumps(safe)
        for value in ['private-session','private-segment','private.pdf','my name','private@example.com','frames']:
            self.assertNotIn(value,serialized)
        self.assertEqual(len(safe['evidence'][0]['text'].split()),25)
        self.assertEqual(restore({'id':safe['segmentId']})['id'],'private-segment')

    def test_egress_is_per_session_and_dataset_always_blocked(self):
        request,_,_=fixture()
        with patch.dict('os.environ',{},clear=True): self.assertFalse(external_ai_allowed(request))
        request.externalAiConsent=True;self.assertTrue(external_ai_allowed(request))
        request.baselineSource='dataset_example';self.assertFalse(external_ai_allowed(request))

    def test_failed_retry_cannot_replace_accepted_feedback_even_after_chat(self):
        _,report,_=fixture()
        existing={'snapshot':{'request':{},'report':{**report,'reportFeedback':{'status':'ready'}},'modelVersion':'test'},'state':{'stage':'practicing'},'messages':[{}]}
        incoming=deepcopy(existing); incoming['snapshot']['report']['reportFeedback']={'status':'failed'}
        self.assertFalse(can_refresh_report(existing,incoming))
        existing['snapshot']['report']['reportFeedback']={'status':'failed'}
        incoming['snapshot']['report']['reportFeedback']={'status':'ready'}
        self.assertTrue(can_refresh_report(existing,incoming))

    def test_new_feedback_version_can_replace_ready_feedback_without_touching_recording(self):
        _,report,_=fixture()
        existing={'snapshot':{'request':{},'report':{**report,'reportFeedback':{'status':'ready','version':'report-feedback-v1'}},'modelVersion':'test'},'state':{'stage':'session_review'},'messages':[],'practices':[]}
        incoming=deepcopy(existing)
        incoming['snapshot']['report']['reportFeedback']={'status':'ready','version':VERSION}
        self.assertTrue(can_refresh_report(existing,incoming))
