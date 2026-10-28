"""Offline failure controls for the privileged CI orchestration; no sudo or accounts."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('linux_control', ROOT / 'scripts/check-linux-sandbox.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
EVIDENCE = json.loads((ROOT / 'docs/evidence/native-ci-fourth-run-2026-10-29.json').read_text())


def native(pass_write=False):
    result = copy.deepcopy(EVIDENCE['native_ci']['platforms']['ubuntu'])
    result.update(model_calls=0, max_native_clients=1, synthetic_auth=True, existing_login_read=False)
    if pass_write:
        mac = EVIDENCE['native_ci']['platforms']['macos']
        result.update(status='pass', checks=copy.deepcopy(mac['checks']),
                      client_binaries_unchanged=True, isolated_profile_removed=True)
        result['host_diagnostics']['native_sandbox_command'].update(
            status='pass', exit_code=0, matching_output={}, workspace_marker_verified=True)
    return result


class FakeOperations:
    def __init__(self):
        self.baseline = native()
        self.candidate = native(True)
        self.calls = []
        self.loaded = set()
        self.installed = False
        self.packages_sufficient = False
        self.fail_guard = False
        self.partial_load_failure = False
        self.fail_cleanup = False
        self.change_global_policy = False
        self.boundary_result = dict.fromkeys(control.BOUNDARIES, True)

    def guard(self):
        self.calls.append('guard')
        control.require(not self.fail_guard, 'explicit_hosted_dispatch_required')

    def settings(self):
        result = copy.deepcopy(self.baseline['host_diagnostics']['kernel_settings'])
        if self.installed and self.change_global_policy:
            result[control.SETTINGS[0]] = 0
        return result

    def native(self, phase):
        self.calls.append(phase)
        result = self.baseline if phase == 'baseline' else self.candidate
        return copy.deepcopy(result), 0 if result['status'] == 'pass' else 1

    def install_packages(self):
        self.calls.append('install')
        self.installed = True

    def host(self):
        passed = self.packages_sufficient or self.loaded == control.PROFILE_NAMES
        result = native(passed)['host_diagnostics']
        result['kernel_settings'] = self.settings()
        return result

    def profile_identity(self):
        self.calls.append('identity')
        return {'profile_names': sorted(control.PROFILE_NAMES), 'sha256': 'synthetic'}

    def loaded_profile_names(self):
        return set(self.loaded)

    def load_profile(self):
        self.calls.append('load')
        if self.partial_load_failure:
            self.loaded = {'bwrap'}
            raise control.ControlError('profile_add_failed')
        self.loaded = set(control.PROFILE_NAMES)

    def remove_profile(self):
        self.calls.append('remove')
        if not self.fail_cleanup:
            self.loaded.clear()
        return 1 if self.fail_cleanup else 0

    def boundaries(self):
        self.calls.append('boundaries')
        return self.boundary_result


class ControlTests(unittest.TestCase):
    def test_hosted_dispatch_guard_rejects_local_fork_pr_and_implicit_runs(self):
        workspace = ROOT
        env = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted', 'RUNNER_OS': 'Linux',
               'GITHUB_REPOSITORY': 'chatwithgod/reflow', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
               'GITHUB_WORKFLOW': 'Linux sandbox prerequisite control',
               'REFLOW_ALLOW_EPHEMERAL_RUNNER_SETUP': '1', 'GITHUB_RUN_ID': '42',
               'GITHUB_WORKSPACE': str(workspace)}
        release = {'ID': 'ubuntu', 'VERSION_ID': '24.04'}
        control.eligible(env, 'Linux', 'x86_64', release, 1001, workspace)
        for key, value in [('GITHUB_ACTIONS', 'false'), ('RUNNER_ENVIRONMENT', 'self-hosted'),
                           ('GITHUB_REPOSITORY', 'fork/reflow'), ('GITHUB_EVENT_NAME', 'push'),
                           ('GITHUB_EVENT_NAME', 'pull_request'), ('REFLOW_ALLOW_EPHEMERAL_RUNNER_SETUP', '0'),
                           ('GITHUB_RUN_ID', ''), ('GITHUB_WORKSPACE', '/different')]:
            with self.subTest(key=key, value=value), self.assertRaises(control.ControlError):
                control.eligible({**env, key: value}, 'Linux', 'x86_64', release, 1001, workspace)
        for system, machine, uid in [('Windows', 'AMD64', 1001), ('Linux', 'aarch64', 1001), ('Linux', 'x86_64', 0)]:
            with self.subTest(system=system, machine=machine, uid=uid), self.assertRaises(control.ControlError):
                control.eligible(env, system, machine, release, uid, workspace)

    def test_guard_failure_runs_no_test_or_package_command(self):
        ops = FakeOperations()
        ops.fail_guard = True
        with self.assertRaises(control.ControlError):
            control.execute_control(ops, {})
        self.assertEqual(ops.calls, ['guard'])

    def test_expected_failure_then_profile_success_and_reversal(self):
        ops, report = FakeOperations(), {}
        control.execute_control(ops, report)
        self.assertEqual(ops.calls, ['guard', 'baseline', 'install', 'identity', 'load', 'candidate', 'boundaries', 'remove'])
        self.assertEqual(report['outcome'], 'profile_candidate_passed')
        self.assertTrue(report['added_profiles_removed'])
        self.assertTrue(report['profile_reversal_reproduced'])
        self.assertTrue(report['global_kernel_settings_unchanged'])

    def test_already_passing_baseline_changes_nothing(self):
        ops, report = FakeOperations(), {}
        ops.baseline = native(True)
        control.execute_control(ops, report)
        self.assertEqual(ops.calls, ['guard', 'baseline', 'boundaries'])
        self.assertEqual(report['outcome'], 'baseline_passed_no_setup_needed')

    def test_packages_alone_can_pass_without_manual_profile_change(self):
        ops, report = FakeOperations(), {}
        ops.packages_sufficient = True
        control.execute_control(ops, report)
        self.assertEqual(ops.calls, ['guard', 'baseline', 'install', 'candidate', 'boundaries'])
        self.assertEqual(report['outcome'], 'distro_packages_sufficient')

    def test_other_baseline_failure_is_not_tolerated(self):
        for mutation in ('protocol', 'skip', 'model', 'signal'):
            ops = FakeOperations()
            if mutation == 'protocol':
                ops.baseline['checks']['native']['status'] = 'fail'
            elif mutation == 'skip':
                ops.baseline['checks']['write']['tests'] = {'pass': 0, 'skip': 1, 'fail': 5}
            elif mutation == 'model':
                ops.baseline['model_calls'] = 1
            else:
                ops.baseline['host_diagnostics']['native_sandbox_command']['matching_output'] = {}
            with self.subTest(mutation=mutation), self.assertRaises(control.ControlError):
                control.execute_control(ops, {})
            self.assertNotIn('install', ops.calls)

    def test_missing_positive_assertions_cannot_pass(self):
        for key in ('client_binaries_unchanged', 'isolated_profile_removed'):
            candidate = native(True)
            candidate.pop(key)
            with self.subTest(key=key), self.assertRaises(control.ControlError):
                control.valid_native(candidate, 0)
        with self.assertRaises(control.ControlError):
            control.valid_native(native(), 137, allow_write_failure=True)

    def test_existing_profile_is_not_replaced_or_removed(self):
        ops = FakeOperations()
        ops.loaded = {'bwrap'}
        with self.assertRaisesRegex(control.ControlError, 'refuse_to_replace'):
            control.execute_control(ops, {})
        self.assertNotIn('load', ops.calls)
        self.assertNotIn('remove', ops.calls)
        self.assertEqual(ops.loaded, {'bwrap'})

    def test_partial_load_is_removed(self):
        ops, report = FakeOperations(), {}
        ops.partial_load_failure = True
        with self.assertRaisesRegex(control.ControlError, 'profile_add_failed'):
            control.execute_control(ops, report)
        self.assertIn('remove', ops.calls)
        self.assertEqual(ops.loaded, set())
        self.assertTrue(report['added_profiles_removed'])

    def test_original_candidate_write_failure_still_fails(self):
        ops = FakeOperations()
        ops.candidate = native()
        with self.assertRaises(control.ControlError):
            control.execute_control(ops, {})
        self.assertIn('remove', ops.calls)
        self.assertNotIn('boundaries', ops.calls)

    def test_boundary_failure_or_missing_check_fails_and_cleans_up(self):
        for outcome in ({}, {'workspace_write_verified': True}, dict.fromkeys(control.BOUNDARIES, False)):
            ops = FakeOperations()
            ops.boundary_result = outcome
            with self.subTest(outcome=outcome), self.assertRaisesRegex(control.ControlError, 'sandbox_boundary_failed'):
                control.execute_control(ops, {})
            self.assertIn('remove', ops.calls)

    def test_cleanup_failure_is_not_success(self):
        ops = FakeOperations()
        ops.fail_cleanup = True
        with self.assertRaisesRegex(control.ControlError, 'profile_cleanup_failed'):
            control.execute_control(ops, {})

    def test_changed_global_restriction_stops_before_profile_add(self):
        ops, report = FakeOperations(), {}
        ops.change_global_policy = True
        with self.assertRaisesRegex(control.ControlError, 'global_host_policy_changed'):
            control.execute_control(ops, report)
        self.assertNotIn('load', ops.calls)
        self.assertFalse(report['global_kernel_settings_unchanged'])

    def test_command_summary_does_not_retain_output_or_canaries(self):
        report = {}
        ops = control.RunnerOperations(report)
        with self.assertRaisesRegex(control.ControlError, '^redaction_failed$'):
            ops.command('redaction', [sys.executable, '-c',
                'import sys; print("CONTENT_CANARY"); print("TOKEN_CANARY", file=sys.stderr); sys.exit(2)'])
        serialized = json.dumps(report)
        self.assertNotIn('CONTENT_CANARY', serialized)
        self.assertNotIn('TOKEN_CANARY', serialized)
        self.assertEqual(report['commands'][0]['exit_code'], 2)

    def test_timeout_terminates_local_test_child(self):
        report = {}
        ops = control.RunnerOperations(report)
        with self.assertRaisesRegex(control.ControlError, '^timeout_control_timed_out$'):
            ops.command('timeout_control', [sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.1)
        self.assertEqual(report['commands'], [{'stage': 'timeout_control', 'timed_out': True}])


if __name__ == '__main__':
    unittest.main(verbosity=2)
