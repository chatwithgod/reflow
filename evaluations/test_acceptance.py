"""Reject false acceptance and prove the sampling loop does not overrun its stop."""
import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import acceptance
import run as evaluation


def example(continued=True):
    return {
        'mode': 'live', 'status': 'finished', 'exit_code': 0, 'completed_turns': 1,
        'artifact_changed': True, 'model_evidence_valid': True,
        'score': {'status': 'scored', 'total': 18, 'passed': 18, 'failed': []},
        'tool_failure_events': 0, 'error_events': 0, 'rate_limit_detected': False,
        'event_trace_truncated': False,
        'event_trace': [{'kind': 'command_execution', 'event': 'item.started'},
                        {'kind': 'command_execution', 'event': 'item.completed', 'status': 'completed', 'exit_code': 0}],
        'workspace_fixture': {'unchanged': True, 'reader_unchanged': True},
        'event_diagnostics': {'counter_probes': 2, 'counter_probes_disabled': False,
                             'counter_probe_errors': 0, 'tool_id_tracking_drops': 0, 'unfinished_tracked_tools': 0},
        'client_reported_usage': {'input_tokens': 10, 'cached_input_tokens': 5, 'output_tokens': 8, 'reasoning_output_tokens': 6},
        'upstream_metrics': {'fold_diagnostics_valid': True, 'diagnostics_version': 1, 'usage_complete': True,
            'requests': 3, 'completed': 3, 'usage_reports': 3, 'failed': 0, 'parse_errors': 0,
            'unsupported_responses': 0, 'tool_tracking_drops': 0, 'input_tokens': 12, 'cached_tokens': 6,
            'output_tokens': 10, 'reasoning_tokens': 6, 'continuations': int(continued),
            'continued_tool_responses': int(continued), 'continued_tool_calls': int(continued), 'continued_tool_results': int(continued)},
    }


class AcceptanceTests(unittest.TestCase):
    def test_matching_failed_tool_is_never_accepted(self):
        for change in ('tool_failure_events', 'error_events', 'rate_limit_detected'):
            with self.subTest(change=change):
                record = example()
                record[change] = 1
                self.assertEqual(acceptance.stop_reason(record), 'non_clean_trial')
        record = example()
        record['event_trace'][1]['exit_code'] = 1
        self.assertEqual(acceptance.stop_reason(record), 'non_clean_trial')

    def test_missing_evidence_or_changed_helpers_prevents_success(self):
        for section, field in [('upstream_metrics', 'usage_complete'), ('upstream_metrics', 'fold_diagnostics_valid'),
                               ('workspace_fixture', 'reader_unchanged'), ('workspace_fixture', 'unchanged')]:
            with self.subTest(field=field):
                record = example()
                record[section][field] = False
                self.assertEqual(acceptance.stop_reason(record), 'non_clean_trial')
        record = example()
        record['event_trace'] = record['event_trace'][:1]
        self.assertEqual(acceptance.stop_reason(record), 'non_clean_trial')
        self.assertEqual(acceptance.stop_reason({}), 'non_clean_trial')

    def test_no_continuation_or_no_matched_return_is_not_acceptance(self):
        self.assertIsNone(acceptance.stop_reason(example(False)))
        record = example()
        record['upstream_metrics']['continued_tool_results'] = 0
        self.assertIsNone(acceptance.stop_reason(record))

    def test_loop_stops_on_first_clean_continuation(self):
        self.check_loop([example(False), example()], expected=2, reason='continuation_acceptance_observed')

    def test_loop_stops_after_an_error_without_another_call(self):
        record = example()
        record['tool_failure_events'] = 1
        self.check_loop([record], expected=1, reason='non_clean_trial')

    def test_loop_runs_only_predeclared_samples_when_none_triggers(self):
        self.check_loop([example(False)] * 3, expected=3, reason=None)

    def check_loop(self, records, expected, reason):
        with tempfile.TemporaryDirectory(prefix='reflow-sampling-loop-') as temporary:
            root = Path(temporary)
            auth = root / 'synthetic-auth.json'
            auth.write_text(json.dumps({'auth_mode': 'chatgpt', 'tokens': {'access_token': 'synthetic-evaluation-token'}}), encoding='utf-8')
            args = ['run.py', '--run-live', '--codex', sys.executable, '--reflow', sys.executable,
                    '--auth-file', str(auth), '--model', 'synthetic-model', '--tasks', 'scheduler',
                    '--conditions', 'on', '--repeats', '3', '--max-continue', '1', '--timeout', '180',
                    '--interval-seconds', '30', '--workspace-smoke-check', '--fixed-workspace-commands',
                    '--stop-on-continuation-success']
            with mock.patch.object(evaluation, 'ROOT', root), mock.patch.object(sys, 'argv', args), \
                 mock.patch.object(evaluation, 'execution_preflight', return_value={'status': 'pass'}), \
                 mock.patch.object(evaluation, 'run_trial', side_effect=copy.deepcopy(records)) as calls, \
                 mock.patch.object(evaluation.time, 'sleep') as sleeps, contextlib.redirect_stdout(io.StringIO()):
                evaluation.main()
            self.assertEqual(calls.call_count, expected)
            self.assertEqual(sleeps.call_count, expected - 1)
            self.assertTrue(all(call.args == (30,) for call in sleeps.call_args_list))
            paths = list((root / 'build/evaluations').glob('*/results.json'))
            self.assertEqual(len(paths), 1)
            report = json.loads(paths[0].read_text(encoding='utf-8'))
            self.assertEqual(len(report['trials']), 3)
            self.assertEqual(len(report['results']), expected)
            self.assertEqual(report.get('stop_reason'), reason)
