"""Owner-scoped coaching persistence in an existing session JSONB column.

No service key or schema changes. A JSON revision is shared by every report
writer so a note, a new report and a coaching turn cannot overwrite each other.
"""
from copy import deepcopy
import requests
from fastapi import HTTPException

FIELD = 'coachingSession'
VERSION = 'storageRevision'


class RecordCoachingStore:
    def __init__(self, url, headers, user_id):
        self.url=url.rstrip('/')+'/rest/v1/presentation_records'
        self.headers=dict(headers)
        self.user_id=user_id

    def _call(self, method, **kwargs):
        headers={**self.headers, 'Prefer':'return=representation'}
        try:
            response=requests.request(method,self.url,headers=headers,timeout=(3,15),**kwargs)
            response.raise_for_status()
            return response.json() if response.content else []
        except requests.RequestException as error:
            code='coaching_storage_access' if error.response is not None and error.response.status_code in {401,403} else 'coaching_storage_unavailable'
            raise HTTPException(503,{'code':code}) from error
        except ValueError as error:
            raise HTTPException(503,{'code':'coaching_storage_response'}) from error

    def _row(self, identity):
        rows=self._call('GET',params={'id':f'eq.{identity}','user_id':f'eq.{self.user_id}',
                                     'select':'id,agent_report,session_date,scene_label','limit':'1'})
        return rows[0] if rows else None

    @staticmethod
    def _document_from_row(row):
        report=row.get('agent_report') or {}
        if report.get(FIELD): return deepcopy(report[FIELD])
        if report.get('generationState') in {'pending','failed'} or not isinstance(report.get('rawSegments'),list): return None
        from agent.report_schema import ReviewRequest
        from agent.coaching import new_document
        source=report.get('reportInput')
        if not isinstance(source,dict):
            source={'sessionId':row['id'],'durationMs':report.get('analysis',{}).get('durationMs'),
                    'language':report.get('language','ko'),'sceneLabel':row.get('scene_label')}
        try:
            request=ReviewRequest.model_validate({**source,'sessionId':row['id'],'segments':report['rawSegments']})
        except ValueError:
            return None
        clean={key:value for key,value in report.items() if key not in {FIELD,VERSION}}
        document=new_document(request,clean,report.get('modelVersion') or request.modelVersion or 'unknown')
        document['snapshot']['recordedAt']=row.get('session_date')
        baseline_source=report.get('observationReport',{}).get('personalBaseline',{}).get('source')
        origin=report.get('dataOrigin') or ('stressid' if request.baselineSource=='dataset_example' or baseline_source=='dataset_example' else 'synthetic' if request.baselineSource=='synthetic' or baseline_source=='synthetic' else 'recorded')
        document['snapshot']['dataOrigin']=origin
        document['snapshot']['report']['coachingAvailable']=origin!='stressid'
        if origin!='stressid':document['snapshot']['report'].pop('coachingDisabledReason',None)
        return document

    def _write(self, identity, current, document):
        revision=current.get(VERSION)
        if revision is not None and (isinstance(revision,bool) or not isinstance(revision,int) or revision<0):
            raise HTTPException(503,{'code':'coaching_storage_response'})
        report={**current,FIELD:deepcopy(document),VERSION:(revision or 0)+1}
        if report.get('generationState') not in {'pending','failed'}:
            blocked=document['snapshot'].get('dataOrigin')=='stressid' or document['snapshot']['request'].get('baselineSource')=='dataset_example'
            report['coachingAvailable']=not blocked
            if blocked: report['coachingDisabledReason']='dataset_privacy'
            else: report.pop('coachingDisabledReason',None)
        rows=self._call('PATCH',params={'id':f'eq.{identity}','user_id':f'eq.{self.user_id}',
                      f'agent_report->>{VERSION}':f'eq.{revision}' if revision is not None else 'is.null','select':'id'},
                      json={'agent_report':report})
        return bool(rows)

    def get(self, identity, bootstrap=True):
        row=self._row(identity)
        if not row: return None
        report=row.get('agent_report') or {}
        if report.get(FIELD): return deepcopy(report[FIELD])
        if not bootstrap: return None
        document=self._document_from_row(row)
        if document is None:return None
        return self.create(identity,document)

    def previous(self, identity):
        rows=self._call('GET',params={'id':f'neq.{identity}','user_id':f'eq.{self.user_id}',
                       'agent_report':'not.is.null','select':'id,agent_report,session_date,scene_label',
                       'order':'session_date.desc','limit':'20'})
        # Comparison may use an analyzed record even when its chat was never opened.
        # Build an in-memory coaching snapshot without mutating the historical row.
        return [document for row in rows if (document:=self._document_from_row(row)) is not None]

    def create(self, identity, document):
        from server.coaching_store import can_refresh_report, same_recording
        for _ in range(5):
            row=self._row(identity)
            if not row: raise HTTPException(503,{'code':'coaching_parent_not_saved'})
            current=row.get('agent_report') or {}
            existing=current.get(FIELD)
            next_doc=deepcopy(document)
            if existing:
                if not same_recording(existing['snapshot']['request'],document['snapshot']['request']):
                    raise HTTPException(409,'Session observations are immutable')
                if not can_refresh_report(existing,document): return deepcopy(existing)
                next_doc=deepcopy(existing)
                next_doc['snapshot']['report']=deepcopy(document['snapshot']['report'])
                next_doc['revision']=existing['revision']+1
            if self._write(identity,current,next_doc): return next_doc
        raise HTTPException(409,'The session changed. Reload and retry.')

    def save(self, identity, document, revision):
        for _ in range(5):
            row=self._row(identity)
            current=(row or {}).get('agent_report') or {}
            existing=current.get(FIELD)
            if not existing or existing['revision']!=revision:
                raise HTTPException(409,'Coaching changed in another tab. Reload and retry.')
            if existing['snapshot']['request']!=document['snapshot']['request']:
                raise HTTPException(409,'Session observations are immutable')
            if self._write(identity,current,document): return
        raise HTTPException(409,'The session changed. Reload and retry.')
