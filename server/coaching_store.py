"""Authenticated, RLS-scoped durable coaching store; no process-global user state."""

from functools import wraps
import requests
from fastapi import HTTPException


def same_recording(left, right):
    return ({k:v for k,v in (left or {}).items() if k not in {'language', 'externalAiConsent'}}
            == {k:v for k,v in (right or {}).items() if k not in {'language', 'externalAiConsent'}})


def can_refresh_report(existing, incoming):
    """Refresh narrative only; retain the recording and all coaching activity."""
    previous_report = existing.get("snapshot", {}).get("report", {})
    new_report = incoming.get("snapshot", {}).get("report", {})
    if previous_report.get('reportFeedback', {}).get('status') in {'ready','partial'} and new_report.get('reportFeedback', {}).get('status') in {'failed','blocked'}:
        return False
    pending_feedback = (previous_report.get("synthesisStatus") == "unavailable"
                        or previous_report.get("synthesisStatus") == "generated" and not any(
                            issue.get("evidenceIds") and issue.get("recommendation")
                            for issue in previous_report.get("priorities", [])))
    idle_retry = (pending_feedback and existing.get("state", {}).get("stage") == "session_review"
                  and not existing.get("messages") and not existing.get("practices"))
    used = {existing.get('state', {}).get('selectedFindingId')}
    used.update(practice.get('findingId') for practice in existing.get('practices', []))
    used.discard(None)
    upgrade = (new_report.get('practiceDefinitionVersion') == 'personalized-experiments-v2'
               and new_report.get('synthesisStatus') == 'generated'
               and (previous_report.get('practiceDefinitionVersion') != 'personalized-experiments-v2'
                    or previous_report.get('language') != new_report.get('language'))
               and used.issubset({item['id'] for item in new_report.get('priorities', [])}))
    feedback_refresh = (new_report.get('reportFeedback') != previous_report.get('reportFeedback')
                        and previous_report.get('reportFeedback', {}).get('status') != 'ready')
    feedback_upgrade = (previous_report.get('reportFeedback', {}).get('status') == 'ready'
                        and new_report.get('reportFeedback', {}).get('status') == 'ready'
                        and previous_report.get('reportFeedback', {}).get('version')
                        != new_report.get('reportFeedback', {}).get('version'))
    return (previous_report != new_report
            and same_recording(existing.get("snapshot", {}).get("request"), incoming.get("snapshot", {}).get("request"))
            and existing.get("snapshot", {}).get("modelVersion") == incoming.get("snapshot", {}).get("modelVersion")
            and (idle_retry or upgrade or feedback_refresh or feedback_upgrade))


def record_fallback(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        if self.using_record_storage:
            return getattr(self._record_store(), method.__name__)(*args, **kwargs)
        try:
            return method(self, *args, **kwargs)
        except HTTPException as error:
            if error.status_code != 503 or not isinstance(error.detail, dict) or error.detail.get("code") != "coaching_schema_missing":
                raise
            self.using_record_storage = True
            return getattr(self._record_store(), method.__name__)(*args, **kwargs)
    return call


class CoachingStore:
    def __init__(self, url, key, token, user_id):
        self.url = url.rstrip("/") + "/rest/v1/coaching_sessions"
        self.user_id = user_id
        self.base_url = url
        self.using_record_storage = False
        self._records = None
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if not url or not key or not token or not user_id:
            raise HTTPException(503, "Coaching storage is not configured.")

    def _record_store(self):
        if self._records is None:
            from server.record_coaching_store import RecordCoachingStore
            self._records = RecordCoachingStore(self.base_url, self.headers, self.user_id)
        return self._records

    def _call(self, method, **kwargs):
        try:
            response = requests.request(
                method, self.url, headers=self.headers, timeout=(3, 10), **kwargs
            )
            response.raise_for_status()
            return response.json() if response.content else []
        except requests.RequestException as error:
            response = error.response
            code = "coaching_storage_unavailable"
            if response is not None:
                try:
                    reason = response.json().get("code")
                except (ValueError, AttributeError):
                    reason = None
                if reason in {"PGRST205", "42P01"}:
                    code = "coaching_schema_missing"
                elif response.status_code in {401, 403}:
                    code = "coaching_storage_access"
            raise HTTPException(503, {"code": code}) from error
        except ValueError as error:
            raise HTTPException(503, {"code": "coaching_storage_response"}) from error

    @record_fallback
    def get(self, session_id, bootstrap=True):
        rows = self._call(
            "GET",
            params={
                "user_id": f"eq.{self.user_id}",
                "session_id": f"eq.{session_id}",
                "select": "*",
                "limit": "1",
            },
        )
        if rows: return self._doc(rows[0])
        legacy = self._record_store().get(session_id, bootstrap=False)
        if legacy is not None: self.using_record_storage = True
        return legacy

    @staticmethod
    def _doc(row):
        return {
            k: row[k]
            for k in ("snapshot", "state", "practices", "messages", "revision")
        }

    @record_fallback
    def previous(self, session_id):
        rows = self._call(
            "GET",
            params={
                "user_id": f"eq.{self.user_id}",
                "session_id": f"neq.{session_id}",
                "select": "*",
                "order": "created_at.desc",
                "limit": "20",
            },
        )
        documents = [self._doc(row) for row in rows]
        previous = self._record_store().previous(session_id)
        known = {doc["state"]["sessionId"] for doc in documents}
        combined = documents + [doc for doc in previous if doc["state"]["sessionId"] not in known]
        return sorted(combined, key=lambda doc: doc["snapshot"].get("recordedAt") or "", reverse=True)[:20]

    @record_fallback
    def create(self, session_id, doc):
        existing = self.get(session_id, bootstrap=False)
        if self.using_record_storage:
            return self._record_store().create(session_id, doc)
        if existing:
            if not same_recording(existing["snapshot"]["request"], doc["snapshot"]["request"]):
                raise HTTPException(
                    409,
                    "Session observations are immutable. Use a new session for a new recording.",
                )
            if can_refresh_report(existing, doc):
                revision = existing["revision"]
                existing["snapshot"]["report"] = doc["snapshot"]["report"]
                existing["revision"] = revision + 1
                self.save(session_id, existing, revision)
            return existing
        self._call(
            "POST", json={"session_id": session_id, "user_id": self.user_id, **doc}
        )
        return doc

    @record_fallback
    def save(self, session_id, doc, revision):
        headers = self.headers
        self.headers = {**headers, "Prefer": "return=representation"}
        try:
            rows = self._call(
                "PATCH",
                params={
                    "user_id": f"eq.{self.user_id}",
                    "session_id": f"eq.{session_id}",
                    "revision": f"eq.{revision}",
                },
                json=doc,
            )
        finally:
            self.headers = headers
        if not rows:
            raise HTTPException(
                409, "Coaching changed in another tab. Reload and retry."
            )
