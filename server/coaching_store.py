"""Authenticated, RLS-scoped durable coaching store; no process-global user state."""

import requests
from fastapi import HTTPException


class CoachingStore:
    def __init__(self, url, key, token, user_id):
        self.url = url.rstrip("/") + "/rest/v1/coaching_sessions"
        self.user_id = user_id
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if not url or not key or not token or not user_id:
            raise HTTPException(503, "Coaching storage is not configured.")

    def _call(self, method, **kwargs):
        try:
            response = requests.request(
                method, self.url, headers=self.headers, timeout=(3, 10), **kwargs
            )
            response.raise_for_status()
            return response.json() if response.content else []
        except (requests.RequestException, ValueError) as error:
            raise HTTPException(
                503,
                "Coaching could not be saved. Check the coaching migration and retry.",
            ) from error

    def get(self, session_id):
        rows = self._call(
            "GET",
            params={
                "user_id": f"eq.{self.user_id}",
                "session_id": f"eq.{session_id}",
                "select": "*",
                "limit": "1",
            },
        )
        return self._doc(rows[0]) if rows else None

    @staticmethod
    def _doc(row):
        return {
            k: row[k]
            for k in ("snapshot", "state", "practices", "messages", "revision")
        }

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
        return [self._doc(row) for row in rows]

    def create(self, session_id, doc):
        existing = self.get(session_id)
        if existing:
            if existing["snapshot"]["request"] != doc["snapshot"]["request"]:
                raise HTTPException(
                    409,
                    "Session observations are immutable. Use a new session for a new recording.",
                )
            return existing
        self._call(
            "POST", json={"session_id": session_id, "user_id": self.user_id, **doc}
        )
        return doc

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
