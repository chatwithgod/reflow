"""Offline failure controls for the privileged CI orchestration; no sudo or accounts."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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
        self.compile_failure = False
        self.positive_control_failure = False
        self.profile_load_attempted = False
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
        passed = self.packages_sufficient or self.loaded == control.PROFILE_NAMES and not self.positive_control_failure
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
        self.profile_load_attempted = True
        if self.partial_load_failure:
            self.loaded = {'bwrap'}
            raise control.ControlError('profile_add_failed')
        self.loaded = set(control.PROFILE_NAMES)

    def compile_profile(self):
        self.calls.append('compile')
        control.require(not self.compile_failure, 'profile_compile_failed')

    def remove_profile(self):
        self.calls.append('remove')
        if not self.fail_cleanup:
            self.loaded.clear()
        return 1 if self.fail_cleanup else 0

    def boundaries(self):
        self.calls.append('boundaries')
        return self.boundary_result


class ControlTests(unittest.TestCase):
    def test_compile_preflight_has_no_privilege_or_kernel_load_and_keeps_strict_flags(self):
        with tempfile.TemporaryDirectory(prefix='rf-profile-args-') as temporary:
            profile = Path(temporary) / 'synthetic-profile'
            profile.write_bytes(b'synthetic profile content for argument capture only')
            ops = control.RunnerOperations({})
            ops.profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
            calls = {}
            ops.command = lambda label, argv, **kwargs: calls.setdefault(label, argv)
            ops.loaded_profile_names = lambda: set()
            with patch.object(control, 'PROFILE', profile):
                ops.compile_profile()
                ops.load_profile()
            preflight, load = calls['profile_compile'], calls['profile_add']
            self.assertNotIn('sudo', preflight)
            self.assertIn('--skip-kernel-load', preflight)
            self.assertIn('--skip-cache', preflight)
            self.assertIn('--Werror=rule-not-enforced', preflight)
            self.assertIn('--warn=rule-not-enforced', preflight)
            self.assertEqual([item for item in preflight if item.startswith(('--Werror', '--warn'))],
                             [item for item in load if item.startswith(('--Werror', '--warn'))])
            self.assertEqual(preflight[-1], load[-1])

    def test_abi4_warning_exception_rejects_extra_unknown_or_changed_output(self):
        def warning(name, strict=False):
            prefix = 'Warning converted to Error' if strict else 'Warning'
            return f'{prefix} from profile {name} ({control.PROFILE}): io_uring rules not enforced\n'.encode()
        strict = subprocess.CompletedProcess([], 1, b'', warning('bwrap', True))
        allowed = subprocess.CompletedProcess([], 0, b'', warning('bwrap') + warning('unpriv_bwrap'))
        self.assertTrue(control.exact_abi4_warning(strict, strict=True))
        self.assertTrue(control.exact_abi4_warning(allowed, strict=False))
        cases = [
            subprocess.CompletedProcess([], 0, b'UNKNOWN_CANARY', allowed.stderr),
            subprocess.CompletedProcess([], 1, b'', allowed.stderr),
            subprocess.CompletedProcess([], 0, b'', warning('bwrap') * 2),
            subprocess.CompletedProcess([], 0, b'', warning('bwrap')),
            subprocess.CompletedProcess([], 0, b'', allowed.stderr + b'UNKNOWN_CANARY\n'),
            subprocess.CompletedProcess([], 0, b'', allowed.stderr.replace(b'io_uring', b'userns')),
            subprocess.CompletedProcess([], 0, b'', allowed.stderr.replace(str(control.PROFILE).encode(), b'/untrusted')),
            subprocess.CompletedProcess([], 0, b'', allowed.stderr.replace(b'unpriv_bwrap', b'OTHER_CANARY')),
        ]
        for result in cases:
            with self.subTest(case=cases.index(result)):
                self.assertFalse(control.exact_abi4_warning(result, strict=False))

    def test_abi4_kernel_features_require_userns_stacking_and_capabilities(self):
        with tempfile.TemporaryDirectory(prefix='rf-abi-features-') as temporary:
            root = Path(temporary)
            values = {'namespaces/mask': 'userns_create\n', 'domain/stack': 'yes\n', 'caps/mask': 'chown sys_admin\n'}
            for name, value in values.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding='ascii')
            observation = control.abi4_kernel_features(root)
            self.assertEqual(observation, {'userns_create': True, 'profile_stacking': True,
                                          'sys_admin_capability': True, 'io_uring_feature_present': False})
            for name, field in [('namespaces/mask', 'userns_create'), ('domain/stack', 'profile_stacking'), ('caps/mask', 'sys_admin_capability')]:
                (root / name).write_text('no\n', encoding='ascii')
                self.assertFalse(control.abi4_kernel_features(root)[field])
                (root / name).write_text(values[name], encoding='ascii')
            (root / 'io_uring').mkdir()
            self.assertTrue(control.abi4_kernel_features(root)['io_uring_feature_present'])
            (root / 'namespaces/mask').unlink()
            with self.assertRaisesRegex(control.ControlError, 'kernel_feature_unavailable'):
                control.abi4_kernel_features(root)

    def test_abi4_identity_rejects_different_files_versions_overrides_or_features(self):
        class File:
            def __init__(self, data=b'fixed public fixture'):
                self.data, self.uid, self.mode, self.symlink = data, 0, 0o100644, False
            def is_file(self): return True
            def is_symlink(self): return self.symlink
            def read_bytes(self): return self.data
            def stat(self): return SimpleNamespace(st_uid=self.uid, st_mode=self.mode)
        file = File()
        identities = {'profile': (file, hashlib.sha256(file.data).hexdigest())}
        report = {'package_versions_after': dict.fromkeys(('apparmor', 'apparmor-profiles', 'apparmor-utils'), control.APPARMOR_VERSION)}
        features = {'userns_create': True, 'profile_stacking': True, 'sys_admin_capability': True, 'io_uring_feature_present': False}
        ops = control.RunnerOperations(report, allow_abi4_io_uring=True)
        with patch.object(control, 'ABI4_IDENTITIES', identities), patch.object(control, 'OPTIONAL_PROFILE_INCLUDES', ()), \
                patch.object(control, 'abi4_kernel_features', return_value=features):
            ops.verify_abi4_identity_and_features()
            for attribute, bad in [('uid', 1000), ('mode', 0o100666), ('symlink', True), ('data', b'changed')]:
                old = getattr(file, attribute)
                setattr(file, attribute, bad)
                with self.assertRaises(control.ControlError):
                    ops.verify_abi4_identity_and_features()
                setattr(file, attribute, old)
            for key in ('userns_create', 'profile_stacking', 'sys_admin_capability'):
                features[key] = False
                with self.assertRaisesRegex(control.ControlError, 'abi4_required_kernel_feature_missing'):
                    ops.verify_abi4_identity_and_features()
                features[key] = True
            report['package_versions_after']['apparmor'] = 'different'
            with self.assertRaisesRegex(control.ControlError, 'abi4_package_version_changed'):
                ops.verify_abi4_identity_and_features()
            report['package_versions_after']['apparmor'] = control.APPARMOR_VERSION
            override = SimpleNamespace(exists=lambda: True, is_symlink=lambda: False)
            with patch.object(control, 'OPTIONAL_PROFILE_INCLUDES', (override,)):
                with self.assertRaisesRegex(control.ControlError, 'abi4_local_profile_override_present'):
                    ops.verify_abi4_identity_and_features()

    def test_abi4_compatibility_requires_strict_failure_then_exact_compile_and_load_warnings(self):
        with tempfile.TemporaryDirectory(prefix='rf-abi-profile-') as temporary:
            profile = Path(temporary) / 'profile'
            profile.write_bytes(b'public fixture')
            ops = control.RunnerOperations({}, allow_abi4_io_uring=True)
            ops.profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
            ops.verify_abi4_identity_and_features = lambda: None
            ops.loaded_profile_names = lambda: set()
            calls = []
            def command(label, argv, **kwargs):
                calls.append((label, argv))
                strict = label == 'profile_compile'
                names = ['bwrap'] if strict else sorted(control.PROFILE_NAMES)
                prefix = 'Warning converted to Error' if strict else 'Warning'
                stderr = ''.join(f'{prefix} from profile {name} ({profile}): io_uring rules not enforced\n' for name in names).encode()
                return subprocess.CompletedProcess(argv, 1 if strict else 0, b'', stderr)
            ops.command = command
            with patch.object(control, 'PROFILE', profile):
                with self.assertRaisesRegex(control.ControlError, 'abi4_preflight_required'):
                    ops.load_profile()
                self.assertFalse(ops.profile_load_attempted)
                ops.compile_profile()
                self.assertTrue(ops.abi4_preflight_verified)
                ops.load_profile()
            self.assertEqual([label for label, _ in calls], ['profile_compile', 'profile_compile_abi4_compat', 'profile_add'])
            self.assertIn('--Werror=rule-not-enforced', calls[0][1])
            for _, argv in calls[1:]:
                self.assertNotIn('--Werror=rule-not-enforced', argv)
            self.assertNotIn('sudo', calls[1][1])
            self.assertIn('--skip-kernel-load', calls[1][1])
            self.assertTrue(ops.profile_load_attempted)

    def test_abi4_unexpected_preflight_stops_before_load(self):
        with tempfile.TemporaryDirectory(prefix='rf-abi-negative-') as temporary:
            profile = Path(temporary) / 'profile'
            profile.write_bytes(b'public fixture')
            for stage in ('strict', 'compatible'):
                ops = control.RunnerOperations({}, allow_abi4_io_uring=True)
                ops.profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
                ops.verify_abi4_identity_and_features = lambda: None
                calls = []
                def command(label, argv, **kwargs):
                    calls.append(label)
                    if stage == 'compatible' and label == 'profile_compile':
                        return subprocess.CompletedProcess(argv, 1, b'',
                            f'Warning converted to Error from profile bwrap ({profile}): io_uring rules not enforced\n'.encode())
                    return subprocess.CompletedProcess(argv, 0, b'', b'UNRECOGNIZED_WARNING_CANARY')
                ops.command = command
                with patch.object(control, 'PROFILE', profile), self.assertRaises(control.ControlError):
                    ops.compile_profile()
                self.assertFalse(ops.abi4_preflight_verified)
                self.assertFalse(ops.profile_load_attempted)
                self.assertNotIn('CANARY', json.dumps(ops.report))
                self.assertNotIn('profile_add', calls)

    def test_rejection_before_add_does_not_remove_profiles_owned_by_someone_else(self):
        ops, report = FakeOperations(), {}
        def refusal():
            ops.loaded = set(control.PROFILE_NAMES)
            raise control.ControlError('refuse_to_replace_existing_profiles')
        ops.load_profile = refusal
        with self.assertRaisesRegex(control.ControlError, 'refuse_to_replace_existing_profiles'):
            control.execute_control(ops, report)
        self.assertFalse(report['profile_load_attempted'])
        self.assertNotIn('remove', ops.calls)
        self.assertEqual(ops.loaded, control.PROFILE_NAMES)

    def test_abi4_full_control_keeps_native_gates_and_cleans_unexpected_load_warning(self):
        with tempfile.TemporaryDirectory(prefix='rf-abi-flow-') as temporary:
            profile = Path(temporary) / 'profile'
            profile.write_bytes(b'fixed public fixture')
            for bad_load_warning in (False, True):
                fake, report = FakeOperations(), {}
                ops = control.RunnerOperations(report, allow_abi4_io_uring=True)
                ops.profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
                for name in ('guard', 'settings', 'native', 'install_packages', 'host', 'profile_identity', 'boundaries'):
                    setattr(ops, name, getattr(fake, name))
                ops.verify_abi4_identity_and_features = lambda: None
                ops.loaded_profile_names = lambda: set(fake.loaded)
                stages = []
                def command(label, argv, **kwargs):
                    stages.append(label)
                    if label == 'profile_remove':
                        fake.loaded.clear()
                        return subprocess.CompletedProcess(argv, 0, b'', b'')
                    if label == 'profile_add':
                        fake.loaded = set(control.PROFILE_NAMES)
                        if bad_load_warning:
                            return subprocess.CompletedProcess(argv, 0, b'', b'UNEXPECTED_LOAD_CANARY')
                    strict = label == 'profile_compile'
                    names = ['bwrap'] if strict else sorted(control.PROFILE_NAMES)
                    prefix = 'Warning converted to Error' if strict else 'Warning'
                    warnings = ''.join(f'{prefix} from profile {name} ({profile}): io_uring rules not enforced\n' for name in names).encode()
                    return subprocess.CompletedProcess(argv, 1 if strict else 0, b'', warnings)
                ops.command = command
                with patch.object(control, 'PROFILE', profile):
                    if bad_load_warning:
                        with self.assertRaisesRegex(control.ControlError, 'abi4_load_warning_unexpected'):
                            control.execute_control(ops, report)
                        self.assertNotIn('candidate', report)
                        self.assertFalse(report['profile_positive_control_verified'])
                    else:
                        control.execute_control(ops, report)
                        self.assertEqual(report['outcome'], 'profile_candidate_passed')
                        self.assertEqual(report['candidate']['checks']['write']['tests'], control.WRITE_PASS)
                        self.assertTrue(report['profile_reversal_reproduced'])
                        self.assertEqual(set(report['boundaries']), control.BOUNDARIES)
                self.assertIn('profile_remove', stages)
                self.assertFalse(fake.loaded)
                self.assertTrue(report['added_profiles_removed'])
                self.assertNotIn('CANARY', json.dumps(report))

    @unittest.skipUnless(sys.platform == 'linux' and Path(control.PARSER).is_file(),
                         'ABI compile fixture requires the Linux parser')
    def test_real_parser_abi4_warning_with_synthetic_kernel_features_never_loads_policy(self):
        abi_path, expected_hash = control.ABI4_IDENTITIES['abi']
        if not abi_path.is_file() or hashlib.sha256(abi_path.read_bytes()).hexdigest() != expected_hash:
            self.skipTest('the pinned Ubuntu ABI 4.0 file is not installed')
        abi = abi_path.read_text(encoding='ascii')
        with tempfile.TemporaryDirectory(prefix='rf-abi-compile-only-') as temporary:
            root = Path(temporary)
            profile = root / 'two-profile-fixture'
            profile.write_text('abi <abi/4.0>,\nprofile bwrap { allow io_uring, }\n'
                               'profile unpriv_bwrap { allow io_uring, }\n', encoding='ascii')
            kernel = root / 'synthetic-kernel-features'
            for kernel_has_io_uring in (False, True):
                kernel.write_text(abi + ('io_uring {mask {sqpoll override_creds\n}\n}\n' if kernel_has_io_uring else ''), encoding='ascii')
                for strict in (True, False):
                    flags = control.PROFILE_WARNING_FLAGS if strict else control.ABI4_COMPAT_FLAGS
                    argv = [control.PARSER, '--skip-kernel-load', '--skip-cache', '--jobs=1',
                            '--kernel-features=' + str(kernel), *flags, str(profile)]
                    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
                    with patch.object(control, 'PROFILE', profile):
                        self.assertTrue(control.exact_abi4_warning(result, strict=strict),
                                        f'kernel_io_uring={kernel_has_io_uring}, strict={strict}, code={result.returncode}, stdout_bytes={len(result.stdout)}, stderr_bytes={len(result.stderr)}')

    @unittest.skipUnless(sys.platform == 'linux' and Path(control.PARSER).is_file(),
                         'AppArmor argument check requires the Linux parser')
    def test_real_parser_accepts_strict_warning_flags_without_loading_policy(self):
        result = subprocess.run([control.PARSER, *control.PROFILE_WARNING_FLAGS, '--help=warn'],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'rule-not-enforced', result.stdout + result.stderr)

    def test_profile_warning_labels_ignore_filename_and_remove_contents(self):
        output = (b'Warning converted to Error from profile bwrap (/private/USERNS_HEADER_CANARY): '
                  b'io_uring rules not enforced CONTENT_CANARY\n')
        labels = control.profile_diagnostics(output)
        self.assertEqual(labels, {'warning_as_error': 1, 'rule_not_enforced': 1, 'io_uring': 1})
        self.assertNotIn('CANARY', json.dumps(labels))
        self.assertEqual(control.profile_diagnostics(b'raw userns CONTENT_CANARY\n'), {})
        unix = control.profile_diagnostics(b'Warning converted to Error from profile bwrap (stdin): unix rules not enforced\n')
        self.assertEqual(unix, {'warning_as_error': 1, 'rule_not_enforced': 1, 'unix_socket': 1})
        caps = control.profile_diagnostics(b'Warning converted to Error from profile bwrap (stdin): capabilities not enforced\n')
        self.assertEqual(caps, {'warning_as_error': 1, 'rule_not_enforced': 1, 'capability': 1})

    def test_compile_failure_does_not_attempt_privileged_load(self):
        ops, report = FakeOperations(), {}
        ops.compile_failure = True
        with self.assertRaisesRegex(control.ControlError, 'profile_compile_failed'):
            control.execute_control(ops, report)
        self.assertIn('compile', ops.calls)
        self.assertNotIn('load', ops.calls)
        self.assertNotIn('remove', ops.calls)
        self.assertNotIn('profile_reversal_reproduced', report)

    def test_failed_positive_control_cannot_be_reported_as_reversal(self):
        ops, report = FakeOperations(), {}
        ops.positive_control_failure = True
        with self.assertRaisesRegex(control.ControlError, 'unexpected_direct_sandbox_result'):
            control.execute_control(ops, report)
        self.assertIn('remove', ops.calls)
        self.assertFalse(report['profile_positive_control_verified'])
        self.assertFalse(report['profile_reversal_tested'])
        self.assertFalse(report['profile_reversal_reproduced'])

    @unittest.skipUnless(sys.platform == 'linux' and shutil.which('dpkg-query'),
                         'real dpkg private-database fixture requires Linux')
    def test_real_dpkg_query_uses_only_a_private_status_database(self):
        with tempfile.TemporaryDirectory(prefix='rf-dpkg-fixture-') as temporary:
            database = Path(temporary).resolve()
            (database / 'status').write_text(
                'Package: bubblewrap\nStatus: unknown ok not-installed\nArchitecture: amd64\n\n'
                'Package: apparmor\nStatus: install ok installed\nArchitecture: amd64\n'
                'Version: 1.0-1\nMaintainer: Reflow Fixture <fixture@example.invalid>\n'
                'Description: synthetic dpkg status fixture\n\n'
                'Package: apparmor-utils\nStatus: deinstall ok config-files\nArchitecture: amd64\n'
                'Version: 1.0-1\nMaintainer: Reflow Fixture <fixture@example.invalid>\n'
                'Description: synthetic removed-package fixture\n\n', encoding='utf-8')
            ops = control.RunnerOperations({})
            command = ops.command

            def private_query(label, argv, **kwargs):
                self.assertIn('/usr/bin/dpkg-query', argv)
                self.assertNotIn('sudo', argv)
                self.assertEqual(argv.count('--admindir=/var/lib/dpkg'), 1)
                argv = ['--admindir=' + str(database) if value == '--admindir=/var/lib/dpkg' else value for value in argv]
                return command(label, argv, **kwargs)

            ops.command = private_query
            self.assertEqual(ops.package_versions('package_versions_before', complete=False), {'apparmor': '1.0-1'})
            states = ops.report['package_states_before']
            self.assertEqual(states['bubblewrap']['state'], 'not-installed')
            self.assertIsNone(states['bubblewrap']['version'])
            self.assertEqual(states['apparmor-utils']['state'], 'config-files')
            self.assertEqual(states['apparmor-profiles']['state'], 'not-found')
            with self.assertRaisesRegex(control.ControlError, 'package_install_incomplete'):
                ops.package_versions('package_versions_after', complete=True)

    def test_missing_and_uninstalled_package_states_are_valid(self):
        missing = control.package_observation(1, b'')
        self.assertEqual(missing['state'], 'not-found')
        self.assertIsNone(missing['version'])
        for status in (b'un ', b'pn ', b'rc '):
            with self.subTest(status=status):
                item = control.package_observation(0, status + b'\t\n')
                self.assertNotEqual(item['state'], 'installed')
                self.assertIsNone(item['version'])

    def test_installed_and_held_package_versions_are_preserved(self):
        for status in (b'ii ', b'hi '):
            item = control.package_observation(0, status + b'\t1:0.9.0-1build1\n')
            self.assertEqual(item['state'], 'installed')
            self.assertEqual(item['error'], 'none')
            self.assertEqual(item['version'], '1:0.9.0-1build1')
        with self.assertRaisesRegex(control.ControlError, 'installed_package_version_missing'):
            control.package_observation(0, b'ii \t\n')

    def test_fatal_and_malformed_package_queries_fail_without_copying_content(self):
        bad = [(2, b''), (1, b'CONTENT_CANARY'), (0, b''), (0, b'ii \t1.0\nextra'),
               (0, b'ii \t1.0\textra'), (0, b'bad\t1.0\n'), (0, b'ii \tTOKEN_CANARY\n'),
               (0, b'ii \t/path/private\n'), (0, b'ii \t\xff\n'), (0, b'x' * 1025)]
        for exit_code, output in bad:
            with self.subTest(exit_code=exit_code, output_size=len(output)), self.assertRaises(control.ControlError) as error:
                control.package_observation(exit_code, output)
            self.assertNotIn('CANARY', str(error.exception))
            self.assertNotIn('/path/private', str(error.exception))

    def test_per_package_collection_tolerates_absence_only_before_setup(self):
        ops = control.RunnerOperations({})
        calls = []
        replies = {'bubblewrap': (0, b'un \t\n'), 'apparmor': (0, b'ii \t4.0.1-0ubuntu1\n'),
                   'apparmor-profiles': (1, b''), 'apparmor-utils': (0, b'rc \t4.0.1-0ubuntu1\n')}

        def command(label, argv, **kwargs):
            calls.append(argv)
            exit_code, output = replies[argv[-1]]
            return subprocess.CompletedProcess(argv, exit_code, output, b'')

        ops.command = command
        versions = ops.package_versions('package_versions_before', complete=False)
        self.assertEqual(versions, {'apparmor': '4.0.1-0ubuntu1'})
        self.assertEqual(len(calls), 4)
        self.assertEqual(set(ops.report['package_states_before']), set(control.DISTRO_PACKAGES))
        self.assertTrue(all('/usr/bin/dpkg-query' in argv and 'sudo' not in argv and '--no-pager' in argv for argv in calls))
        with self.assertRaisesRegex(control.ControlError, 'package_install_incomplete'):
            ops.package_versions('package_versions_after', complete=True)

    def test_complete_package_collection_rejects_reinstall_required(self):
        ops = control.RunnerOperations({})
        broken = False

        def command(label, argv, **kwargs):
            status = b'iiR' if broken and argv[-1] == 'apparmor' else b'ii '
            return subprocess.CompletedProcess(argv, 0, status + b'\t1.0-1\n', b'')

        ops.command = command
        self.assertEqual(len(ops.package_versions('package_versions_after', complete=True)), 4)
        broken = True
        with self.assertRaisesRegex(control.ControlError, 'package_install_incomplete'):
            ops.package_versions('package_versions_after', complete=True)

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
        self.assertEqual(ops.calls, ['guard', 'baseline', 'install', 'identity', 'compile', 'load', 'candidate', 'boundaries', 'remove'])
        self.assertEqual(report['outcome'], 'profile_candidate_passed')
        self.assertTrue(report['added_profiles_removed'])
        self.assertTrue(report['profile_reversal_reproduced'])
        self.assertTrue(report['profile_positive_control_verified'])
        self.assertTrue(report['profile_reversal_tested'])
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
        self.assertFalse(report['profile_reversal_reproduced'])

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
