import unittest
from unittest.mock import patch, Mock
from fastapi import HTTPException
from server.coaching_store import CoachingStore


class StoreTests(unittest.TestCase):
    def store(self):
        return CoachingStore(
            "https://example.test", "publishable", "user-jwt", "user-1"
        )

    def response(self, data):
        response = Mock()
        response.content = b"json"
        response.json.return_value = data
        return response

    def test_reads_are_scoped_to_the_authenticated_user_and_use_rls_token(self):
        with patch(
            "server.coaching_store.requests.request", return_value=self.response([])
        ) as call:
            self.assertIsNone(self.store().get("other-session"))
            self.assertEqual(call.call_args.kwargs["params"]["user_id"], "eq.user-1")
            self.assertEqual(
                call.call_args.kwargs["headers"]["Authorization"], "Bearer user-jwt"
            )

    def test_update_uses_optimistic_revision_and_reports_conflict(self):
        with patch(
            "server.coaching_store.requests.request", return_value=self.response([])
        ) as call:
            with self.assertRaises(HTTPException) as error:
                self.store().save("s1", {"revision": 4}, 3)
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(call.call_args.kwargs["params"]["revision"], "eq.3")

    def test_cannot_overwrite_original_observations_for_an_existing_session(self):
        store = self.store()
        with patch.object(
            store, "get", return_value={"snapshot": {"request": {"segments": [1]}}}
        ):
            with self.assertRaises(HTTPException) as error:
                store.create("s1", {"snapshot": {"request": {"segments": [2]}}})
            self.assertEqual(error.exception.status_code, 409)
