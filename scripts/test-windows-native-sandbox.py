"""Failure controls for CI sandbox orchestration; never provision a host."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import windows_native_sandbox as sandbox

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_ci_preflight', ROOT / 'evaluations/client_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
spec = importlib.util.spec_from_file_location('native_ci', ROOT / 'scripts/check-native-clients.py')
native_ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native_ci)


class FakeOperations:
    def __init__(self, profile):
        self.profile = profile
        self.calls = []
        self.fail_setup = self.fail_cleanup = self.change_firewall = False
        self.state = {key: 0 for key in sandbox.RESOURCE_FIELDS}
        self.state.update(user='synthetic-private-owner', administrator=True, enabled_firewall_profiles=3,
                          firewall_profile_mask=7, enabled_firewall_rules=0, firewall_service_running=1)

    def guard(self):
        self.calls.append('guard')

    def snapshot(self):
        self.calls.append('snapshot')
        return copy.deepcopy(self.state)

    def setup(self, user):
        self.calls.append('setup')
        self.state['users'] = 2
        if self.fail_setup:
            raise RuntimeError('partial_setup_failed')

    def uninstall(self):
        self.calls.append('uninstall')
        if self.fail_cleanup:
            return {'status': 'fail'}
        self.state.update({key: 0 for key in sandbox.RESOURCE_FIELDS})
        if self.change_firewall:
            self.state['enabled_firewall_profiles'] = 0
            self.state['firewall_profile_mask'] = 0
        return {'status': 'pass'}

    def marker(self):
        self.calls.append('marker')
        return {'version': 5, 'allow_local_binding': False, 'proxy_port_count': 0}


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ops = FakeOperations(Path(self.temp.name))
        self.record = {}

    def test_cleanup_after_success_and_private_identity_not_exported(self):
        with sandbox.provision(self.ops, self.record, {'PATH': 'synthetic'}) as env:
            self.assertEqual(env['REFLOW_NATIVE_WINDOWS_SANDBOX'], 'elevated')
            self.assertEqual(env['REFLOW_NATIVE_WINDOWS_SETUP_READY'], '1')
            self.assertNotIn('uninstall', self.ops.calls)
        self.assertEqual(self.ops.calls, ['guard', 'snapshot', 'setup', 'snapshot', 'marker', 'uninstall', 'snapshot'])
        self.assertTrue(self.record['resources_removed'])
        self.assertEqual(self.record['status'], 'pass')
        self.assertNotIn('synthetic-private-owner', json.dumps(self.record))

    def test_partial_setup_is_cleaned(self):
        self.ops.fail_setup = True
        with self.assertRaisesRegex(RuntimeError, 'partial_setup_failed'):
            with sandbox.provision(self.ops, self.record, {}):
                self.fail('test must not start after setup failure')
        self.assertIn('uninstall', self.ops.calls)
        self.assertEqual(self.record['status'], 'fail')
        self.assertTrue(self.record['resources_removed'])

    def test_test_failure_is_cleaned_and_preserved(self):
        with self.assertRaisesRegex(RuntimeError, 'five_write_tests_failed'):
            with sandbox.provision(self.ops, self.record, {}):
                raise RuntimeError('five_write_tests_failed')
        self.assertEqual(self.record['status'], 'fail')
        self.assertTrue(self.record['resources_removed'])

    def test_cleanup_failure_cannot_pass(self):
        self.ops.fail_cleanup = True
        with self.assertRaisesRegex(RuntimeError, 'cleanup_failed'):
            with sandbox.provision(self.ops, self.record, {}):
                pass
        self.assertEqual(self.record['status'], 'fail')
        self.assertFalse(self.record['resources_removed'])

    def test_changed_global_firewall_cannot_pass(self):
        self.ops.change_firewall = True
        with self.assertRaisesRegex(RuntimeError, 'cleanup_failed'):
            with sandbox.provision(self.ops, self.record, {}):
                pass
        self.assertFalse(self.record['firewall_profile_state_unchanged'])

    def test_existing_resources_never_modified_or_uninstalled(self):
        for field in sandbox.RESOURCE_FIELDS:
            with self.subTest(field=field):
                ops = FakeOperations(self.ops.profile)
                ops.state[field] = 1
                with self.assertRaisesRegex(RuntimeError, 'existing_sandbox_resources_refused'):
                    with sandbox.provision(ops, {}, {}):
                        self.fail('existing install must be preserved')
                self.assertEqual(ops.calls, ['guard', 'snapshot'])

    def test_non_admin_never_set_up(self):
        self.ops.state['administrator'] = False
        with self.assertRaisesRegex(RuntimeError, 'elevated_ci_token_required'):
            with sandbox.provision(self.ops, self.record, {}):
                pass
        self.assertEqual(self.ops.calls, ['guard', 'snapshot'])


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.profile = self.root / 'rf-native-ci-synthetic'
        self.profile.mkdir()
        self.env = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted', 'RUNNER_OS': 'Windows',
                    'GITHUB_REPOSITORY': 'chatwithgod/reflow', 'GITHUB_WORKFLOW': 'Native client fixtures',
                    'GITHUB_EVENT_NAME': 'push', 'GITHUB_RUN_ID': '123', 'RUNNER_TEMP': str(self.root),
                    'GITHUB_WORKSPACE': str(ROOT)}

    def test_disposable_runner_allowed(self):
        sandbox.eligible(self.env, 'win32', 3, self.profile)

    def test_local_workstation_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'hosted_windows_server_required'):
            sandbox.eligible(self.env, 'win32', 1, self.profile)

    def test_non_windows_refused(self):
        with self.assertRaises(RuntimeError):
            sandbox.eligible(self.env, 'linux', 3, self.profile)

    def test_missing_or_wrong_ci_identity_refused(self):
        for key in self.env:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                sandbox.eligible({**self.env, key: 'incorrect'}, 'win32', 3, self.profile)

    def test_profile_outside_runner_temp_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'profile_outside_runner_temp'):
            sandbox.eligible(self.env, 'win32', 3, self.root)


class NetworkTests(unittest.TestCase):
    def probe(self, results):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            return results.pop(0)

        result = sandbox.network_boundary(Path('codex'), Path('tcp-probe'), Path('.'), {}, run=run)
        return result, calls

    def test_real_block_marker_required(self):
        result, calls = self.probe([subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE),
                                    subprocess.CompletedProcess([], 42, sandbox.NETWORK_BLOCKED),
                                    subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE)])
        self.assertTrue(all(result[key] for key in sandbox.NETWORK_CHECKS))
        self.assertEqual(calls[0][-1], calls[1][-1])
        self.assertEqual(calls[0], calls[2])
        self.assertIn('windows.sandbox="elevated"', calls[1])
        self.assertIn(':workspace', calls[1])

    def test_sandbox_start_error_is_not_network_isolation(self):
        result, _ = self.probe([subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE),
                               subprocess.CompletedProcess([], 1, b'failed to start'),
                               subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE)])
        self.assertFalse(result['local_listener_blocked_in_sandbox'])

    def test_reachable_network_is_not_isolation(self):
        result, _ = self.probe([subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE),
                               subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE),
                               subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE)])
        self.assertFalse(result['local_listener_blocked_in_sandbox'])

    def test_missing_positive_control_stops(self):
        result, calls = self.probe([subprocess.CompletedProcess([], 42, sandbox.NETWORK_BLOCKED)])
        self.assertFalse(any(result[key] for key in sandbox.NETWORK_CHECKS))
        self.assertEqual(len(calls), 1)

    def test_listener_must_still_work_after_block(self):
        result, _ = self.probe([subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE),
                               subprocess.CompletedProcess([], 42, sandbox.NETWORK_BLOCKED),
                               subprocess.CompletedProcess([], 42, sandbox.NETWORK_BLOCKED)])
        self.assertFalse(all(result[key] for key in sandbox.NETWORK_CHECKS))

    def test_diagnostics_keep_no_output_text(self):
        data = sandbox.network_observation(subprocess.CompletedProcess([], 1,
            b'private-body-canary', b'failed to start private-path-canary'))
        self.assertEqual(data['matching_output'], {'process_launch_error': 1})
        self.assertNotIn('canary', json.dumps(data))

    def test_identity_requires_offline_account(self):
        for marker, expected in ((b'fixture\\CodexSandboxOffline', True), (b'fixture\\CodexSandboxOnline', False),
                                 (b'private-account-canary', False), (b'fixture\\CodexSandboxOffline\nextra', False)):
            with self.subTest(marker=marker):
                results = [subprocess.CompletedProcess([], 0, b'fixture\\runner'),
                           subprocess.CompletedProcess([], 0, marker)]
                result = sandbox.sandbox_identity(Path('codex'), Path('probe'), Path('.'), {},
                                                  run=lambda *args, **kwargs: results.pop(0))
                self.assertEqual(result['offline_identity_verified'], expected)
                self.assertNotIn('canary', json.dumps(result))

    def test_known_loopback_limit_is_not_reported_as_isolation(self):
        result, _ = self.probe([subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE)] * 3)
        acceptance = sandbox.network_acceptance(result)
        self.assertEqual(acceptance['status'], 'known_loopback_limitation')
        self.assertFalse(acceptance['loopback_isolation_verified'])
        self.assertFalse(result['local_listener_blocked_in_sandbox'])

    def test_verified_block_has_distinct_acceptance(self):
        result, _ = self.probe([subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE),
                               subprocess.CompletedProcess([], 42, sandbox.NETWORK_BLOCKED),
                               subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE)])
        acceptance = sandbox.network_acceptance(result)
        self.assertEqual(acceptance['status'], 'blocked')
        self.assertTrue(acceptance['loopback_isolation_verified'])

    def test_known_limit_does_not_accept_broken_controls_or_unknown_exit(self):
        base, _ = self.probe([subprocess.CompletedProcess([], 0, sandbox.NETWORK_REACHABLE)] * 3)
        for label in ('before', 'after', 'sandbox'):
            with self.subTest(label=label):
                result = copy.deepcopy(base)
                result['controls'][label]['exit_code'] = 1
                with self.assertRaises(RuntimeError):
                    sandbox.network_acceptance(result)


class FilesystemTests(unittest.TestCase):
    def test_invalid_backend_rejected_before_process(self):
        with patch.object(preflight.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(ValueError, 'unsupported_windows_sandbox'):
                preflight.filesystem_probe(None, None, None, {}, None, None, windows_sandbox='disabled')
            spawn.assert_not_called()

    def test_both_backends_keep_workspace_and_boundary_checks(self):
        for backend in ('mxc', 'elevated'):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as temporary:
                profile = Path(temporary).resolve()
                work = profile / 'work'
                work.mkdir()
                (work / 'native-probe.txt').write_bytes(b'REFLOW_NATIVE_PREFLIGHT_OK\n')
                requests = []

                class Input:
                    def write(self, value):
                        requests.append(json.loads(value))

                    def flush(self): pass
                    def close(self): pass

                class Process:
                    stdin = Input()
                    stdout = io.BytesIO(b'{"id":1,"result":{}}\n{"id":2,"result":{}}\n{"id":3,"error":{}}\n')

                    def wait(self, **kwargs): return 0

                with patch.object(preflight.subprocess, 'Popen', return_value=Process()):
                    result = preflight.filesystem_probe(profile / 'codex', profile, work,
                        {'SYSTEMROOT': str(profile)}, lambda: {}, lambda _: None, windows_sandbox=backend)
                self.assertTrue(result['native_filesystem_write_verified'])
                self.assertTrue(result['out_of_workspace_write_blocked'])
                policies = [item['params']['sandbox'] for item in requests if item['method'] == 'fs/writeFile']
                self.assertEqual(len(policies), 2)
                for policy in policies:
                    self.assertEqual(policy['windowsSandboxLevel'], backend)
                    self.assertEqual(policy['permissions']['network'], 'restricted')
                    entries = policy['permissions']['file_system']['entries']
                    self.assertEqual([x['path']['path'] for x in entries if x['access'] == 'write'], [work.as_uri()])


class WriteGateTests(unittest.TestCase):
    def result(self, changed=None, action='pass'):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / 'test.jsonl'
            events = [{'Action': action if name == changed else 'pass', 'Test': name}
                      for name in native_ci.WRITE_TESTS if not (name == changed and action == 'missing')]
            events.append({'Action': 'pass'})
            log.write_text('\n'.join(json.dumps(item) for item in events), encoding='utf-8')
            return native_ci.go_result(log, 0, native_ci.WRITE_TESTS)

    def test_all_five_cases_and_parent_required(self):
        self.assertEqual(len(native_ci.WRITE_TESTS), 6)
        self.assertEqual(self.result()['status'], 'pass')
        for name in native_ci.WRITE_TESTS:
            with self.subTest(name=name):
                self.assertEqual(self.result(name, 'missing')['status'], 'fail')

    def test_skip_or_failure_cannot_turn_green(self):
        for action in ('skip', 'fail'):
            with self.subTest(action=action):
                self.assertEqual(self.result(native_ci.WRITE_TESTS[-1], action)['status'], 'fail')


if __name__ == '__main__':
    unittest.main(verbosity=2)
