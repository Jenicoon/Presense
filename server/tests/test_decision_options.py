import unittest
from unittest.mock import patch
from agent.decision_agent import AgentState, _decision_view, _validate_action, _segment_result
from agent.session_analyzer import analyze_session
from agent.report_agent import luxia_decide_action
from server.tests.test_feedback_selection import measured_request

class DecisionOptionTests(unittest.TestCase):
    def state(self):
        request=measured_request(1)
        summary,candidates=analyze_session(request)
        return AgentState(request=request,summary=summary,candidates=candidates)

    def test_every_advertised_action_passes_server_validation(self):
        state=self.state();view=_decision_view(state,None)
        options=view['availableActions']
        self.assertTrue(options)
        for option in options:self.assertEqual(_validate_action(option['proposal'],state,None),option['proposal'])

    def test_provider_selects_exact_proposal_and_cannot_rewrite_windows(self):
        state=self.state();context=_decision_view(state,None)
        selected=next(option for option in context['availableActions'] if option['proposal']['action']=='analyze_segment')
        with patch('agent.report_agent._luxia_json',return_value={'actionId':selected['id'],'segmentIds':['invented']}):
            self.assertEqual(luxia_decide_action(context),selected['proposal'])
        with patch('agent.report_agent._luxia_json',return_value={'actionId':'invented'}):
            with self.assertRaises(ValueError):luxia_decide_action(context)

    def test_finish_selection_is_owned_by_the_chosen_valid_option(self):
        state=self.state();context=_decision_view(state,None)
        option=next(o for o in context['availableActions'] if o['proposal']['action']=='finish')
        with patch('agent.report_agent._luxia_json',return_value={'actionId':option['id'],'priorityCandidateIds':['invented']}):
            proposal=luxia_decide_action(context)
        self.assertEqual(proposal,option['proposal'])
        _validate_action(proposal,state,None)

    def test_plain_rationale_is_ignored_but_second_json_object_is_rejected(self):
        from agent.report_agent import _parse_json_object
        self.assertEqual(_parse_json_object('{"actionId":"tool-0"}\nThis is the next useful check.'),{'actionId':'tool-0'})
        with self.assertRaises(ValueError):_parse_json_object('{"actionId":"tool-0"} {"actionId":"other"}')
