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


    def test_missing_table_has_a_specific_setup_code(self):
        import requests
        response = Mock()
        response.status_code = 404
        response.json.return_value = {"code": "PGRST205"}
        error = requests.HTTPError(response=response)
        with patch("server.coaching_store.requests.request", side_effect=error):
            with self.assertRaises(HTTPException) as raised:
                self.store()._call("GET")
        self.assertEqual(raised.exception.detail["code"], "coaching_schema_missing")

    def test_unavailable_report_can_refresh_before_coaching_begins(self):
        original = {'snapshot': {'request': {'segments': [1]}, 'report': {'synthesisStatus': 'unavailable'}, 'recordedAt': 'original'},
                    'state': {'stage': 'session_review'}, 'messages': [], 'practices': [], 'revision': 3}
        incoming = {'snapshot': {'request': {'segments': [1]}, 'report': {'synthesisStatus': 'generated'}, 'recordedAt': 'new'}}
        store = self.store()
        with patch.object(store, 'get', return_value=original), patch.object(store, 'save') as save:
            result = store.create('s1', incoming)
        self.assertEqual(result['snapshot']['report']['synthesisStatus'], 'generated')
        self.assertEqual(result['snapshot']['recordedAt'], 'original')
        self.assertEqual(result['snapshot']['request'], {'segments': [1]})
        self.assertEqual(result['revision'], 4)
        save.assert_called_once_with('s1', result, 3)

    def test_report_retry_preserves_active_coaching_and_its_original_snapshot(self):
        for extra in ({'messages': [{'message': 'Review started'}]}, {'practices': [{'id': 'practice'}]}, {'state': {'stage': 'recording'}}):
            with self.subTest(extra=extra):
                original = {'snapshot': {'request': {'segments': [1]}, 'report': {'synthesisStatus': 'unavailable'}},
                            'state': {'stage': 'session_review'}, 'messages': [], 'practices': [], 'revision': 3, **extra}
                incoming = {'snapshot': {'request': {'segments': [1]}, 'report': {'synthesisStatus': 'generated'}}}
                store = self.store()
                with patch.object(store, 'get', return_value=original), patch.object(store, 'save') as save:
                    result = store.create('s1', incoming)
                self.assertEqual(result['snapshot']['report']['synthesisStatus'], 'unavailable')
                save.assert_not_called()

    def test_personalized_report_upgrade_preserves_active_practice_and_recording(self):
        original={'snapshot':{'request':{'segments':[1],'language':'ko'},'report':{'synthesisStatus':'generated'}},
                  'state':{'stage':'practice_created','selectedFindingId':'pitch'},'practices':[{'id':'p','findingId':'pitch'}],
                  'messages':[{'text':'Saved conversation'}],'revision':3}
        incoming={'snapshot':{'request':{'segments':[1],'language':'en'},'report':{
            'practiceDefinitionVersion':'personalized-experiments-v2','synthesisStatus':'generated','language':'en','priorities':[{'id':'pitch'}]}}}
        store=self.store()
        with patch.object(store,'get',return_value=original),patch.object(store,'save'):
            result=store.create('s1',incoming)
        self.assertEqual(result['snapshot']['report'],incoming['snapshot']['report'])
        self.assertEqual(result['practices'],[{'id':'p','findingId':'pitch'}])
        self.assertEqual(result['messages'],[{'text':'Saved conversation'}])
        self.assertEqual(result['snapshot']['request'],{'segments':[1],'language':'ko'})
