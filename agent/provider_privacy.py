"""Explicit per-session external AI eligibility and minimized provider payloads."""
import os
import re
from uuid import uuid4


def external_ai_allowed(request, snapshot=None):
    snapshot = snapshot or {}
    if request.baselineSource == 'dataset_example' or snapshot.get('dataOrigin') == 'stressid':
        return False
    allowed={value.strip() for value in os.getenv('PRESENSE_LUXIA_TEST_SESSION_IDS','').split(',') if value.strip()}
    return (request.sessionId in allowed or getattr(request,'externalAiConsent',False)
            or snapshot.get('externalAiConsent') is True)


def minimized_context(context):
    """Remove identifiers/paths; replace all linking IDs, including non-UUID IDs.

    Feature values, relative times, quality and schema remain. No raw media or
    free-form session labels enter the provider payload. Papers export at most
    twenty-five words per source across the whole request.
    """
    ids={}
    identity_keys={'sessionId','previousSessionId','attemptSessionId','parentSessionId','segmentId','segmentIds','selectedSegmentIds','supportingSegmentIds','reviewSegmentIds'}
    blocked={'email','name','full_name','userId','accountId','filename','fileName','videoPath','videoUrl','audioPath','mediaPath','frames','audio','video','scene','sceneLabel','recordedAt','rawSegments','coachingSession'}
    uuid_pattern=re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
    def identity(value):
        if isinstance(value,list): return [identity(child) for child in value]
        if isinstance(value,str):return ids.setdefault(value,str(uuid4()))
        return value
    def scan(value):
        if isinstance(value,dict):
            for key,child in value.items():
                if key in identity_keys: identity(child)
                else: scan(child)
        elif isinstance(value,list):
            for child in value: scan(child)
    scan(context)
    seen_papers={}
    def clean(value):
        if isinstance(value,dict):
            output={key:clean(child) for key,child in value.items() if key not in blocked}
            if isinstance(output.get('text'),str) and ('source' in output or 'doi' in output):
                source=output.get('doi') or output.get('articleUrl') or output.get('source')
                remaining=max(0,25-seen_papers.get(source,0))
                words=output['text'].split()[:remaining]
                output['text']=' '.join(words)
                seen_papers[source]=seen_papers.get(source,0)+len(words)
                output['source']=output.get('articleUrl') or ('https://doi.org/'+output['doi'] if output.get('doi') else 'local research reference')
            return output
        if isinstance(value,list):return [clean(child) for child in value]
        if isinstance(value,str):
            if value in ids: return ids[value]
            for old,new in sorted(ids.items(),key=lambda pair:-len(pair[0])):
                if len(old) >= 8: value=value.replace(old,new)
            value=uuid_pattern.sub(lambda match:match[0] if match[0] in ids.values() else ids.setdefault(match[0],str(uuid4())),value)
            value=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[redacted]',value)
            value=re.sub(r'(?:/Users/|/private/|/tmp/)[^\s"<>]+','[redacted]',value)
            value=re.sub(r'\b[\w.-]+\.(?:pdf|webm|mp4|mov|wav)\b','[local reference]',value,flags=re.I)
            return value
        return value
    safe=clean(context)
    def restore(value):
        if isinstance(value,dict):return {key:restore(child) for key,child in value.items()}
        if isinstance(value,list):return [restore(child) for child in value]
        if isinstance(value,str):
            for old,new in ids.items(): value=value.replace(new,old)
        return value
    return safe,restore
