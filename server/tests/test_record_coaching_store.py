"""Coaching survives missing-table deployments and competing report writers."""
import json
from copy import deepcopy
import unittest
from unittest.mock import patch
import requests
from fastapi import HTTPException
from agent.coaching import new_document
from agent.report_agent import generate_report
from server.tests.test_feedback_selection import measured_request
from server.coaching_store import CoachingStore

class Database:
    def __init__(self):
        req=measured_request(1)
        report=generate_report(req,model_version=req.modelVersion,agent_mode=True)
        report['reportInput']={k:v for k,v in req.model_dump().items() if k!='segments'}
        self.row={'id':req.sessionId,'user_id':'owner','agent_report':report,'scene_label':'camera','session_date':'2026-11-06T00:00:00Z'}
        self.request=req;self.doc=new_document(req,report,req.modelVersion)
        self.calls=[];self.conflict=False
    def call(self,method,url,**kwargs):
        self.calls.append((method,url,deepcopy(kwargs)))
        response=requests.Response();response.status_code=200
        if url.endswith('/coaching_sessions'):
            response.status_code=404;response._content=json.dumps({'code':'PGRST205'}).encode();return response
        params=kwargs.get('params',{}); rows=[]
        allowed=params.get('user_id')=='eq.'+self.row['user_id']
        identity=params.get('id','')
        matching=identity=='eq.'+self.row['id'] or identity.startswith('neq.') and identity!='neq.'+self.row['id']
        if method=='GET' and allowed and matching:rows=[deepcopy(self.row)]
        if method=='PATCH' and allowed and matching:
            current=self.row['agent_report']
            if self.conflict:
                self.conflict=False
                current['selfFeedback']='a simultaneous reflection'
                current['storageRevision']=current.get('storageRevision',0)+1
            revision=current.get('storageRevision')
            expected=f'eq.{revision}' if revision is not None else 'is.null'
            if params.get('agent_report->>storageRevision')==expected:
                self.row.update(deepcopy(kwargs['json']));rows=[{'id':self.row['id']}]
        response._content=json.dumps(rows).encode();return response

class RecordCoachingTests(unittest.TestCase):
    def setUp(self):self.db=Database()
    def store(self,user='owner'):return CoachingStore('https://example.test','publishable','scoped-token',user)

    def test_previous_analyzed_record_is_available_before_its_chat_is_opened(self):
        with patch('requests.request',side_effect=self.db.call):
            previous=self.store().previous('another-session')
        self.assertEqual(previous[0]['state']['sessionId'],self.db.row['id'])
        self.assertEqual(previous[0]['snapshot']['recordedAt'],self.db.row['session_date'])
        self.assertNotIn('coachingSession',self.db.row['agent_report'])

    def test_no_schema_change_needed_to_bootstrap_restore_save_and_compare_history(self):
        with patch('requests.request',side_effect=self.db.call):
            store=self.store();doc=store.get(self.db.row['id'])
            self.assertTrue(store.using_record_storage)
            self.assertEqual(doc['snapshot']['request'],self.db.request.model_dump())
            changed=deepcopy(doc);changed['revision']+=1;changed['state']['stage']='completed'
            store.save(self.db.row['id'],changed,doc['revision'])
            restored=self.store().get(self.db.row['id'])
            self.assertEqual(restored['state']['stage'],'completed')
            self.assertEqual(restored['revision'],1)
            previous=self.store().previous('another-session')
            self.assertEqual(previous[0]['state']['sessionId'],self.db.row['id'])
            self.assertIsNone(self.store('other-user').get(self.db.row['id']))
        for method,url,args in self.db.calls:
            self.assertEqual(args['headers']['Authorization'],'Bearer scoped-token')
            self.assertIn('user_id',args['params'])
            if method=='PATCH':self.assertEqual(set(args['json']),{'agent_report'})

    def test_competing_reflection_survives_coaching_retry(self):
        with patch('requests.request',side_effect=self.db.call):
            store=self.store();doc=store.create(self.db.row['id'],self.db.doc)
            self.db.conflict=True
            changed=deepcopy(doc);changed['revision']+=1
            store.save(self.db.row['id'],changed,doc['revision'])
        self.assertEqual(self.db.row['agent_report']['selfFeedback'],'a simultaneous reflection')
        self.assertEqual(self.db.row['agent_report']['coachingSession']['revision'],1)

    def test_consent_metadata_can_change_without_mutating_saved_measurements(self):
        from agent.provider_privacy import external_ai_allowed
        from agent.report_schema import ReviewRequest
        with patch('requests.request',side_effect=self.db.call):
            store=self.store();doc=store.create(self.db.row['id'],self.db.doc)
            original=deepcopy(doc['snapshot']['request'])
            original_report=deepcopy(doc['snapshot']['report'])
            changed=deepcopy(doc);changed['snapshot']['externalAiConsent']=True;changed['revision']+=1
            self.db.conflict=True
            store.save(self.db.row['id'],changed,doc['revision'])
            restored=self.store().get(self.db.row['id'])
        self.assertEqual(restored['snapshot']['request'],original)
        self.assertEqual(restored['snapshot']['report'],original_report)
        self.assertTrue(external_ai_allowed(ReviewRequest.model_validate(original),restored['snapshot']))
        self.assertEqual(self.db.row['agent_report']['selfFeedback'],'a simultaneous reflection')

    def test_stale_coaching_revision_and_changed_observations_are_rejected(self):
        with patch('requests.request',side_effect=self.db.call):
            store=self.store();doc=store.create(self.db.row['id'],self.db.doc)
            changed=deepcopy(doc);changed['revision']=1;store.save(self.db.row['id'],changed,0)
            with self.assertRaises(HTTPException) as stale:store.save(self.db.row['id'],doc,0)
            self.assertEqual(stale.exception.status_code,409)
            altered=deepcopy(doc);altered['snapshot']['request']['segments'][0]['stressScore']=.99
            with self.assertRaises(HTTPException) as immutable:store.create(self.db.row['id'],altered)
            self.assertEqual(immutable.exception.status_code,409)
        self.assertNotEqual(self.db.row['agent_report']['coachingSession']['snapshot']['request']['segments'][0]['stressScore'],.99)
