import copy
import io
import json
import unittest
from unittest import mock
import urllib.error

from pi_events import PiEvents
from pi_probe import credential_for_probe, check_catalog


class PiCredentialTests(unittest.TestCase):
    def valid(self):
        return {'openai': {'type': 'oauth', 'access': 'SYNTHETIC_PRIVATE_ACCESS', 'refresh': 'SYNTHETIC_PRIVATE_REFRESH',
            'expires': 4000000, 'clientId': 'synthetic-issued', 'scopes': ['resource.invoke', 'chatgpt.tokens.use.direct']}}

    def test_only_fresh_scoped_pi_oauth_is_copied_without_refresh(self):
        original = self.valid()
        saved = copy.deepcopy(original)
        result = credential_for_probe(original, 180, now=1000)
        self.assertEqual(result['refresh'], '')
        self.assertEqual(original, saved)
        self.assertIsNot(result['scopes'], original['openai']['scopes'])

    def test_api_key_codex_storage_expiry_and_missing_scope_are_rejected(self):
        bad = [{}, {'auth_mode': 'chatgpt', 'tokens': {'access_token': 'SYNTHETIC_PRIVATE_ACCESS'}}]
        for key, value in [('type', 'api_key'), ('access', 'sk-synthetic-offline'), ('expires', 1001000),
                           ('expires', True), ('clientId', 'dynamic_agent_client'), ('scopes', []), ('scopes', [{}])]:
            item = self.valid()
            item['openai'][key] = value
            bad.append(item)
        for item in bad:
            with self.assertRaises(ValueError) as failure:
                credential_for_probe(item, 180, now=1000)
            self.assertNotIn('PRIVATE', str(failure.exception))

    def test_catalog_keeps_only_availability_and_status(self):
        response = io.BytesIO(json.dumps({'models': [{'slug': 'gpt-6.1-sol', 'visibility': 'list',
                                                    'private_metadata': 'SYNTHETIC_PRIVATE'}]}).encode())
        response.status = 200
        with mock.patch('urllib.request.urlopen', return_value=response) as fetch:
            result = check_catalog({'access': 'SYNTHETIC_PRIVATE_ACCESS'}, 'gpt-6.1-sol')
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result['status'], 'pass')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_catalog_rate_limit_is_not_retried(self):
        error = urllib.error.HTTPError('https://api.openai.com/v1/models', 429, 'SYNTHETIC_PRIVATE', {}, None)
        with mock.patch('urllib.request.urlopen', side_effect=error) as fetch:
            result = check_catalog({'access': 'SYNTHETIC_PRIVATE_ACCESS'}, 'gpt-6.1-sol')
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(result['rate_limit_detected'])
        self.assertNotIn('PRIVATE', json.dumps(result))


class PiEventTests(unittest.TestCase):
    def collector(self):
        stopped = []
        metrics = dict.fromkeys(('requests', 'completed', 'continuations', 'continued_tool_responses',
                                 'continued_tool_calls', 'continued_tool_results', 'tool_tracking_drops'), 0)
        return PiEvents('SYNTHETIC_PRIVATE', lambda: metrics, 0, lambda: stopped.append(True), clock=lambda: 0), stopped

    def test_only_numbers_and_fixture_booleans_survive_tool_and_message_events(self):
        events, stopped = self.collector()
        events.observe({'type': 'reflow_probe_guard', 'version': 1, 'allowed': 1, 'blocked': 0})
        events.observe({'type': 'tool_execution_start', 'toolCallId': 'SYNTHETIC_PRIVATE_ID', 'toolName': 'read',
                        'args': {'path': 'SYNTHETIC_PRIVATE_PATH'}})
        events.observe({'type': 'tool_execution_end', 'toolCallId': 'SYNTHETIC_PRIVATE_ID', 'toolName': 'read',
                        'isError': False, 'result': {'content': [{'type': 'text', 'text': 'SYNTHETIC_PRIVATE'}]}})
        events.observe({'type': 'message_end', 'message': {'role': 'assistant', 'stopReason': 'stop',
            'content': [{'type': 'text', 'text': 'SYNTHETIC_PRIVATE'}],
            'usage': {'input': 2, 'output': 3, 'cacheRead': 4, 'cacheWrite': 0, 'reasoning': 1}}})
        events.observe({'type': 'agent_end', 'messages': ['SYNTHETIC_PRIVATE']})
        result = events.summary()
        self.assertTrue(result['fixture_read_matched'] and result['final_fixture_matched'])
        self.assertEqual(result['client_reported_usage']['input'], 2)
        self.assertEqual(result['event_diagnostics']['unfinished_tracked_tools'], 0)
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertFalse(stopped)

    def test_failed_tool_and_rate_limit_stop_immediately(self):
        events, stopped = self.collector()
        events.observe({'type': 'tool_execution_end', 'toolName': 'read', 'isError': True})
        self.assertTrue(stopped)
        events.observe({'type': 'message_end', 'message': {'role': 'assistant', 'stopReason': 'error',
            'errorMessage': '429 rate_limit SYNTHETIC_PRIVATE'}})
        self.assertTrue(events.summary()['rate_limit_detected'])
        self.assertNotIn('PRIVATE', json.dumps(events.summary()))

    def test_bad_guard_or_incomplete_usage_is_not_accepted(self):
        events, stopped = self.collector()
        events.observe({'type': 'reflow_probe_guard', 'version': True, 'allowed': 1, 'blocked': 0})
        events.observe({'type': 'message_end', 'message': {'role': 'assistant', 'stopReason': 'stop',
            'usage': {'input': 1}, 'content': []}})
        self.assertFalse(events.summary()['guard_observations_valid'])
        self.assertEqual(events.summary()['invalid_usage_reports'], 1)
        events.observe({'type': 'reflow_probe_guard', 'version': 1, 'allowed': 0, 'blocked': 1})
        self.assertTrue(stopped)
