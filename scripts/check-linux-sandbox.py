"""Opt-in control on a disposable GitHub Ubuntu runner; no real account calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
PROFILE = Path('/usr/share/apparmor/extra-profiles/bwrap-userns-restrict')
PARSER = '/usr/sbin/apparmor_parser'
PROFILE_NAMES = {'bwrap', 'unpriv_bwrap'}
DISTRO_PACKAGES = ('bubblewrap', 'apparmor', 'apparmor-profiles', 'apparmor-utils')
SETTINGS = ('kernel/apparmor_restrict_unprivileged_userns',
            'kernel/unprivileged_userns_clone', 'user/max_user_namespaces')
PASS = {'pass': 10, 'skip': 0, 'fail': 0}
WRITE_PASS = {'pass': 6, 'skip': 0, 'fail': 0}
WRITE_FAIL = {'pass': 0, 'skip': 0, 'fail': 6}
BOUNDARIES = {'workspace_write_verified', 'outside_workspace_write_blocked',
              'local_listener_reachable_without_sandbox', 'local_listener_blocked_in_sandbox'}
PACKAGE_STATES = {'n': 'not-installed', 'c': 'config-files', 'H': 'half-installed', 'U': 'unpacked',
                  'F': 'half-configured', 'W': 'triggers-awaited', 't': 'triggers-pending', 'i': 'installed'}
PACKAGE_SELECTIONS = {'u': 'unknown', 'i': 'install', 'h': 'hold', 'r': 'remove', 'p': 'purge'}
PROFILE_WARNING_FLAGS = ('--warn=rule-not-enforced', '--Werror=rule-not-enforced')
ABI4_COMPAT_FLAGS = ('--warn=rule-not-enforced',)
APPARMOR_VERSION = '4.0.1really4.0.1-0ubuntu0.24.04.9'
ABI4_IDENTITIES = {
    'profile': (PROFILE, '11d39094f044f0cda0febb3ad517b830301da6b2ce929664af09ee9e4dd264f9'),
    'abi': (Path('/etc/apparmor.d/abi/4.0'), 'e510bb8f6788b45e48de2f859a6f94a7b8416cbac5a1051814cfce925fa911bd'),
    'parser_config': (Path('/etc/apparmor/parser.conf'), 'f8586f1c3bfd7abac6a182c1b45d22a8397c0db5a737b54bc8f9fc48da53d5bd'),
    'parser': (Path(PARSER), '85e67b4ebc2559cc84c7d256d14890b8a7521e0278aedd544e13a3204a387d05'),
}
APPARMOR_FEATURES = Path('/sys/kernel/security/apparmor/features')
OPTIONAL_PROFILE_INCLUDES = (Path('/etc/apparmor.d/local/bwrap-userns-restrict'),
                             Path('/etc/apparmor.d/local/unpriv_bwrap'))
PROFILE_MESSAGE_SIGNALS = {
    'rule_not_enforced': ('not enforced', 'not supported'),
    'user_namespace': ('userns', 'user namespace'),
    'io_uring': ('io_uring', 'io uring'),
    'message_queue': ('mqueue', 'message queue'),
    'dbus': ('dbus',),
    'network': ('network', 'af_unix'),
    'unix_socket': ('unix rules', 'unix socket'),
    'mount': ('mount', 'pivot_root'),
    'file': ('file rule', 'file permission'),
    'capability': ('capability', 'capabilities'),
    'signal': ('signal rule',),
    'ptrace': ('ptrace',),
    'policy_abi': ('abi',),
}


class ControlError(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise ControlError(code)


def eligible(env, system, machine, release, uid, workspace):
    """Fail before commands on local machines, forks, PRs or implicit runs."""
    require(system == 'Linux' and machine == 'x86_64' and uid != 0, 'host_not_supported')
    require(release.get('ID') == 'ubuntu' and release.get('VERSION_ID') == '24.04', 'ubuntu_2404_required')
    expected = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                'RUNNER_OS': 'Linux', 'GITHUB_REPOSITORY': 'chatwithgod/reflow',
                'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_WORKFLOW': 'Linux sandbox prerequisite control',
                'REFLOW_ALLOW_EPHEMERAL_RUNNER_SETUP': '1'}
    require(all(env.get(key) == value for key, value in expected.items()), 'explicit_hosted_dispatch_required')
    require(env.get('GITHUB_RUN_ID', '').isdigit(), 'run_identity_missing')
    require(env.get('GITHUB_WORKSPACE') == str(workspace), 'workspace_mismatch')


def valid_native(data, exit_code, *, allow_write_failure=False):
    require(data.get('platform') == 'linux/amd64' and data.get('model_calls') == 0
            and data.get('max_native_clients') == 1 and data.get('synthetic_auth') is True
            and data.get('existing_login_read') is False, 'unexpected_native_scope')
    require(data.get('codex_version') == 'codex-cli 0.165.0' and data.get('pi_version') == '1.4.0',
            'unexpected_native_versions')
    checks = data.get('checks', {})
    for phase in ('native', 'race'):
        item = checks.get(phase, {})
        require(item.get('status') == 'pass' and item.get('tests') == PASS
                and item.get('missing_tests') == [] and item.get('package_passed') is True,
                'native_protocol_gate_failed')
    write = checks.get('write', {})
    if exit_code == 0:
        require(data.get('status') == 'pass' and write.get('status') == 'pass'
                and write.get('tests') == WRITE_PASS and write.get('missing_tests') == []
                and write.get('package_passed') is True and data.get('client_binaries_unchanged') is True
                and data.get('isolated_profile_removed') is True, 'native_write_gate_failed')
        return True
    require(exit_code == 1 and allow_write_failure and data.get('status') == 'fail' and write.get('status') == 'fail'
            and write.get('tests') == WRITE_FAIL, 'unexpected_baseline_failure')
    host = data.get('host_diagnostics', {})
    markers = host.get('native_sandbox_command', {}).get('matching_output', {})
    require(markers.get('bubblewrap') == markers.get('operation_not_permitted') == 1,
            'baseline_not_namespace_failure')
    return False


def validate_host(host, original_settings, *, sandbox_pass):
    require(host.get('kernel_settings') == original_settings and host.get('uid_is_root') is False,
            'global_host_policy_changed')
    controls = host.get('namespace_controls', {})
    require(set(controls) == {'user', 'user_mount', 'user_network'}, 'namespace_control_missing')
    require(all(value.get('status') == 'fail' and not value.get('timed_out')
                and value.get('matching_output', {}).get('uid_gid_mapping') == 1
                for value in controls.values()), 'unshare_restriction_changed')
    command = host.get('native_sandbox_command', {})
    require(command.get('status') == ('pass' if sandbox_pass else 'fail')
            and command.get('workspace_marker_verified') is sandbox_pass and not command.get('timed_out'),
            'unexpected_direct_sandbox_result')


def validate_boundaries(boundaries):
    require(set(boundaries) == BOUNDARIES and all(value is True for value in boundaries.values()),
            'sandbox_boundary_failed')


def package_observation(exit_code, output):
    """Interpret one dpkg query; absent or uninstalled packages are not malformed."""
    require(exit_code in (0, 1), 'package_query_fatal')
    if exit_code == 1:
        require(output == b'', 'package_query_partial_output')
        return {'state': 'not-found', 'selection': None, 'error': None, 'version': None}
    require(len(output) <= 1024, 'package_metadata_too_large')
    try:
        lines = output.decode('ascii').splitlines()
    except UnicodeDecodeError:
        raise ControlError('package_metadata_encoding') from None
    require(len(lines) == 1 and lines[0].count('\t') == 1, 'package_metadata_shape')
    status, version = lines[0].split('\t')
    require(len(status) == 3 and status[0] in PACKAGE_SELECTIONS and status[1] in PACKAGE_STATES
            and status[2] in (' ', 'R'), 'package_status_invalid')
    require(len(version) <= 128 and all(char.isalnum() or char in '.+~:-' for char in version),
            'package_version_invalid')
    state = PACKAGE_STATES[status[1]]
    require(state != 'installed' or bool(version), 'installed_package_version_missing')
    return {'state': state, 'selection': PACKAGE_SELECTIONS[status[0]],
            'error': 'none' if status[2] == ' ' else 'reinstall-required', 'version': version or None}


def profile_diagnostics(output):
    """Classify warning bodies only; filenames can themselves contain userns."""
    counts = {}
    for line in output.decode('utf-8', errors='replace').lower().splitlines():
        converted = line.startswith('warning converted to error from profile ')
        if not converted and not line.startswith('warning from profile '):
            if line.startswith('apparmor parser error'):
                counts['parser_error'] = counts.get('parser_error', 0) + 1
            continue
        _, separator, body = line.partition('): ')
        if not separator:
            continue
        if converted:
            counts['warning_as_error'] = counts.get('warning_as_error', 0) + 1
        for name, markers in PROFILE_MESSAGE_SIGNALS.items():
            matched = bool(re.search(r'\babi\b', body)) if name == 'policy_abi' else any(marker in body for marker in markers)
            if matched:
                counts[name] = counts.get(name, 0) + 1
    return counts


def exact_abi4_warning(result, *, strict):
    """Only accept the complete, known vendor warning; do not accept arbitrary text."""
    prefix = 'Warning converted to Error' if strict else 'Warning'
    names = {'bwrap'} if strict else PROFILE_NAMES
    expected = {f'{prefix} from profile {name} ({PROFILE}): io_uring rules not enforced'.encode()
                for name in names}
    lines = result.stderr.splitlines()
    return result.returncode == (1 if strict else 0) and result.stdout == b'' \
        and len(lines) == len(expected) and set(lines) == expected


def abi4_kernel_features(root):
    def read(relative):
        try:
            with (root / relative).open('rb') as stream:
                data = stream.read(65537)
            require(len(data) <= 65536, 'kernel_feature_too_large')
            return data.decode('ascii').strip()
        except (OSError, UnicodeError):
            raise ControlError('kernel_feature_unavailable') from None
    userns = 'userns_create' in read('namespaces/mask').split()
    stacking = read('domain/stack') == 'yes'
    caps = read('caps/mask').split()
    # The modern feature file names capabilities; old numeric forms are not guessed.
    capability = 'sys_admin' in caps
    return {'userns_create': userns, 'profile_stacking': stacking,
            'sys_admin_capability': capability, 'io_uring_feature_present': (root / 'io_uring').exists()}


def execute_control(ops, report):
    """An expected baseline failure is data; final native and boundary gates stay mandatory."""
    ops.guard()
    original = ops.settings()
    require(original.get(SETTINGS[0]) == 1 and original.get(SETTINGS[1]) == 1, 'restriction_baseline_required')
    report['original_kernel_settings'] = original
    baseline, exit_code = ops.native('baseline')
    report['baseline'] = baseline
    if valid_native(baseline, exit_code, allow_write_failure=True):
        report['outcome'] = 'baseline_passed_no_setup_needed'
        report['boundaries'] = ops.boundaries()
        validate_boundaries(report['boundaries'])
        require(ops.settings() == original, 'global_host_policy_changed')
        return
    validate_host(baseline['host_diagnostics'], original, sandbox_pass=False)
    load_attempted = False
    positive_control_verified = False
    try:
        ops.install_packages()
        report['packages_installed'] = True
        after_packages = ops.host()
        report['after_packages'] = after_packages
        packages_fixed_it = after_packages['native_sandbox_command']['status'] == 'pass'
        validate_host(after_packages, original, sandbox_pass=packages_fixed_it)
        if not packages_fixed_it:
            report['profile'] = ops.profile_identity()
            require(ops.loaded_profile_names() == set(), 'refuse_to_replace_existing_profiles')
            ops.compile_profile()
            try:
                ops.load_profile()
            finally:
                load_attempted = ops.profile_load_attempted
                report['profile_load_attempted'] = load_attempted
            require(ops.loaded_profile_names() == PROFILE_NAMES, 'profile_load_incomplete')
            report['after_profile'] = ops.host()
            validate_host(report['after_profile'], original, sandbox_pass=True)
            positive_control_verified = True
        candidate, exit_code = ops.native('candidate')
        report['candidate'] = candidate
        valid_native(candidate, exit_code)
        validate_host(candidate['host_diagnostics'], original, sandbox_pass=True)
        report['boundaries'] = ops.boundaries()
        validate_boundaries(report['boundaries'])
        report['outcome'] = 'distro_packages_sufficient' if packages_fixed_it else 'profile_candidate_passed'
    finally:
        # --add never replaces pre-existing definitions. Remove only the known
        # definitions from this attempted add, including a partially loaded file.
        if load_attempted:
            report['profile_removal_exit_code'] = ops.remove_profile()
            report['added_profiles_removed'] = ops.loaded_profile_names() == set()
            require(report['added_profiles_removed'], 'profile_cleanup_failed')
            report['after_profile_removal'] = ops.host()
            validate_host(report['after_profile_removal'], original, sandbox_pass=False)
            report['profile_positive_control_verified'] = positive_control_verified
            report['profile_reversal_tested'] = positive_control_verified
            report['profile_reversal_reproduced'] = positive_control_verified
        report['global_kernel_settings_unchanged'] = ops.settings() == original
        require(report['global_kernel_settings_unchanged'], 'global_host_policy_changed')


def load_native_helpers():
    spec = importlib.util.spec_from_file_location('native_fixture_helpers', ROOT / 'scripts/check-native-clients.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RunnerOperations:
    def __init__(self, report, *, allow_abi4_io_uring=False):
        self.report = report
        self.allow_abi4_io_uring = allow_abi4_io_uring
        self.abi4_preflight_verified = False
        self.profile_load_attempted = False
        self.native_helpers = load_native_helpers()
        self.codex = ROOT / '.tools/native-clients/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex'

    def guard(self):
        eligible(os.environ, platform.system(), platform.machine(),
                 platform.freedesktop_os_release() if sys.platform == 'linux' else {},
                 os.geteuid() if hasattr(os, 'geteuid') else -1, ROOT)

    def command(self, label, argv, timeout=60, *, checked=True):
        process = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   **self.native_helpers.probe_spawn_options())
        try:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.native_helpers.stop_probe_process(process)
                process.communicate(timeout=10)
                self.report.setdefault('commands', []).append({'stage': label, 'timed_out': True})
                raise ControlError(label + '_timed_out')
            result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
        finally:
            self.native_helpers.stop_probe_process(process)
            process.stdout.close()
            process.stderr.close()
        observation = {
            'stage': label, 'exit_code': result.returncode,
            'stdout_bytes': len(result.stdout), 'stderr_bytes': len(result.stderr)}
        if label in ('profile_compile', 'profile_compile_abi4_compat', 'profile_add', 'profile_remove'):
            observation['matching_output'] = profile_diagnostics(result.stdout + b'\n' + result.stderr)
        self.report.setdefault('commands', []).append(observation)
        if checked:
            require(result.returncode == 0, label + '_failed')
        return result

    def settings(self):
        return {key: int((Path('/proc/sys') / key).read_text().strip()) for key in SETTINGS}

    def native(self, phase):
        folder = ROOT / 'build/native-client-ci'
        before = set(folder.glob('*/summary.json'))
        result = self.command(phase, [sys.executable, str(ROOT / 'scripts/check-native-clients.py')],
                              timeout=1500, checked=False)
        new = set(folder.glob('*/summary.json')) - before
        require(len(new) == 1, 'native_summary_missing')
        path = new.pop()
        data = json.loads(path.read_text(encoding='utf-8'))
        require(data['source_commit'] == self.report['source_commit'], 'native_source_changed')
        self.report.setdefault('native_reports', {})[phase] = {
            'path': path.relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        # Do not copy arbitrary exception text into the control summary.
        keys = ('status', 'platform', 'model_calls', 'max_native_clients', 'synthetic_auth',
                'existing_login_read', 'codex_version', 'pi_version', 'checks', 'host_diagnostics',
                'client_binaries_unchanged', 'isolated_profile_removed')
        return {key: data[key] for key in keys if key in data}, result.returncode

    def install_packages(self):
        self.report['package_versions_before'] = self.package_versions('package_versions_before', complete=False)
        self.command('apt_update', ['sudo', '-n', 'apt-get', 'update'], timeout=300)
        self.command('apt_install', ['sudo', '-n', 'env', 'DEBIAN_FRONTEND=noninteractive',
                                    'apt-get', 'install', '--yes', '--no-install-recommends',
                                    'bubblewrap', 'apparmor-profiles', 'apparmor-utils'], timeout=300)
        self.report['package_versions_after'] = self.package_versions('package_versions_after', complete=True)
        info = Path('/usr/bin/bwrap').stat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o6022,
                'system_bwrap_permissions_unexpected')
        found = shutil.which('bwrap')
        require(found is not None and Path(found).resolve() == Path('/usr/bin/bwrap').resolve(),
                'system_bwrap_not_first_on_path')
        self.report['system_bwrap_sha256'] = hashlib.sha256(Path('/usr/bin/bwrap').read_bytes()).hexdigest()

    def package_versions(self, label, *, complete):
        require(label in ('package_versions_before', 'package_versions_after'), 'package_stage_invalid')
        states = {}
        self.report[label.replace('_versions_', '_states_')] = states
        versions = {}
        # Query separately so an absent package does not hide successful rows.
        # These are unprivileged reads from the system package database, without
        # a pager or locale-dependent presentation fields.
        for name in DISTRO_PACKAGES:
            result = self.command(label + '_' + name, [
                '/usr/bin/env', 'LC_ALL=C', 'LANGUAGE=C', 'DPKG_COLORS=never',
                '/usr/bin/dpkg-query', '--admindir=/var/lib/dpkg', '--no-pager', '--show',
                '--showformat=${db:Status-Abbrev}\t${Version}\n', name], checked=False)
            item = package_observation(result.returncode, result.stdout)
            states[name] = item
            if item['state'] == 'installed' and item['error'] == 'none':
                versions[name] = item['version']
        if complete:
            require(set(versions) == set(DISTRO_PACKAGES), 'package_install_incomplete')
        return versions

    def profile_identity(self):
        require(PROFILE.is_file() and not PROFILE.is_symlink(), 'distro_profile_missing')
        info = PROFILE.stat()
        require(info.st_uid == 0 and not info.st_mode & 0o022, 'distro_profile_not_root_owned')
        names = self.command('profile_names', [PARSER, '--names', str(PROFILE)]).stdout.decode().splitlines()
        require(set(names) == PROFILE_NAMES, 'unexpected_profile_names')
        self.profile_hash = hashlib.sha256(PROFILE.read_bytes()).hexdigest()
        return {'sha256': self.profile_hash, 'profile_names': sorted(PROFILE_NAMES),
                'source': 'Ubuntu apparmor-profiles package; unmodified vendor file'}

    def loaded_profile_names(self):
        result = self.command('loaded_profiles', ['sudo', '-n', 'cat', '/sys/kernel/security/apparmor/profiles'])
        names = {line.rsplit(' (', 1)[0] for line in result.stdout.decode().splitlines()}
        return names & PROFILE_NAMES

    def compile_profile(self):
        require(hashlib.sha256(PROFILE.read_bytes()).hexdigest() == self.profile_hash, 'profile_changed')
        argv = [PARSER, '--skip-kernel-load', '--skip-cache', '--jobs=1', *PROFILE_WARNING_FLAGS, str(PROFILE)]
        if not self.allow_abi4_io_uring:
            self.command('profile_compile', argv)
            return
        self.verify_abi4_identity_and_features()
        strict = self.command('profile_compile', argv, checked=False)
        require(exact_abi4_warning(strict, strict=True), 'abi4_strict_warning_unexpected')
        compatible = self.command('profile_compile_abi4_compat',
            [PARSER, '--skip-kernel-load', '--skip-cache', '--jobs=1', *ABI4_COMPAT_FLAGS, str(PROFILE)], checked=False)
        require(exact_abi4_warning(compatible, strict=False), 'abi4_compile_warning_unexpected')
        self.abi4_preflight_verified = True
        self.report['abi4_io_uring_exception'] = {
            'explicitly_enabled': True, 'strict_preflight_failed_as_expected': True,
            'compatibility_compile_passed': True, 'exact_vendor_warnings': 2,
            'rule_not_enforced_Werror_omitted_in_compatibility_commands': True,
        }

    def verify_abi4_identity_and_features(self):
        versions = self.report.get('package_versions_after', {})
        require(all(versions.get(name) == APPARMOR_VERSION for name in ('apparmor', 'apparmor-profiles', 'apparmor-utils')),
                'abi4_package_version_changed')
        identities = {}
        for label, (path, expected) in ABI4_IDENTITIES.items():
            require(path.is_file() and not path.is_symlink(), 'abi4_vendor_file_missing')
            info = path.stat()
            require(info.st_uid == 0 and not info.st_mode & 0o022, 'abi4_vendor_file_not_root_owned')
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            require(digest == expected, 'abi4_vendor_file_changed')
            identities[label] = digest
        require(not any(path.exists() or path.is_symlink() for path in OPTIONAL_PROFILE_INCLUDES),
                'abi4_local_profile_override_present')
        features = abi4_kernel_features(APPARMOR_FEATURES)
        require(features['userns_create'] and features['profile_stacking'] and features['sys_admin_capability'],
                'abi4_required_kernel_feature_missing')
        self.report['abi4_vendor_sha256'] = identities
        self.report['abi4_kernel_features'] = features

    def load_profile(self):
        require(hashlib.sha256(PROFILE.read_bytes()).hexdigest() == self.profile_hash, 'profile_changed')
        require(self.loaded_profile_names() == set(), 'refuse_to_replace_existing_profiles')
        if not self.allow_abi4_io_uring:
            self.profile_load_attempted = True
            self.command('profile_add', ['sudo', '-n', PARSER, '--add', '--skip-cache', '--jobs=1',
                                         *PROFILE_WARNING_FLAGS, str(PROFILE)])
            return
        require(self.abi4_preflight_verified, 'abi4_preflight_required')
        self.verify_abi4_identity_and_features()
        self.profile_load_attempted = True
        result = self.command('profile_add', ['sudo', '-n', PARSER, '--add', '--skip-cache', '--jobs=1',
                                              *ABI4_COMPAT_FLAGS, str(PROFILE)], checked=False)
        require(exact_abi4_warning(result, strict=False), 'abi4_load_warning_unexpected')
        self.report['abi4_io_uring_exception']['load_returned_success_with_exact_warnings'] = True

    def remove_profile(self):
        require(hashlib.sha256(PROFILE.read_bytes()).hexdigest() == self.profile_hash, 'profile_changed')
        return self.command('profile_remove', ['sudo', '-n', PARSER, '--remove', '--skip-cache',
                                               '--jobs=1', str(PROFILE)], checked=False).returncode

    def host(self):
        with tempfile.TemporaryDirectory(prefix='rf-linux-control-') as temporary:
            profile = Path(temporary).resolve()
            env = self.native_helpers.isolated_env(profile)
            return self.native_helpers.host_diagnostics(self.codex, profile, env)

    def boundaries(self):
        """Positive write plus rejected sibling write and loopback connection; no auth."""
        helpers = self.native_helpers
        # Keep the denied target outside the checkout AND /tmp. The built-in
        # workspace policy may legitimately allow temporary-directory writes.
        with tempfile.TemporaryDirectory(prefix='rf-linux-boundary-', dir=ROOT.parent) as temporary:
            profile = Path(temporary).resolve()
            require(profile.parent == ROOT.parent.resolve(), 'boundary_profile_escaped_parent')
            work = profile / 'work'
            work.mkdir()
            env = helpers.isolated_env(profile)
            base = [str(self.codex), '-c', 'cli_auth_credentials_store="file"', 'sandbox',
                    '--include-managed-config', '--permission-profile', ':workspace', '-C', str(work), '--']
            marker = work / 'inside.txt'
            positive = helpers.command_observation(base + ['/bin/sh', '-c', 'printf OK > inside.txt'], env, work)
            inside = positive['exit_code'] == 0 and not positive['timed_out'] \
                and marker.is_file() and marker.read_bytes() == b'OK'
            require(inside, 'positive_boundary_control_failed')
            outside = profile / 'outside.txt'
            negative = helpers.command_observation(base + ['/bin/sh', '-c',
                'if printf DENIED > "$1"; then exit 0; else exit 17; fi', 'sh', str(outside)], env, work)
            write_blocked = negative['exit_code'] == 17 and not negative['timed_out'] and not outside.exists()
            accepted = []
            connected = threading.Event()
            stop = threading.Event()
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                listener.listen()
                listener.settimeout(0.1)
                port = listener.getsockname()[1]

                def accept():
                    while not stop.is_set():
                        try:
                            connection, _ = listener.accept()
                            with connection:
                                accepted.append(1)
                                connected.set()
                        except socket.timeout:
                            pass

                thread = threading.Thread(target=accept, daemon=True)
                thread.start()
                code = ('import socket,sys\ntry:\n s=socket.create_connection(("127.0.0.1",int(sys.argv[1])),2)\n'
                        ' s.close()\nexcept OSError:\n sys.exit(17)\n')
                command = [sys.executable, '-c', code, str(port)]
                try:
                    reachable = helpers.command_observation(command, env, work)
                    require(reachable['exit_code'] == 0 and not reachable['timed_out'] and connected.wait(2),
                            'listener_positive_control_failed')
                    blocked = helpers.command_observation(base + command, env, work)
                finally:
                    stop.set()
                    thread.join(timeout=2)
                    require(not thread.is_alive(), 'listener_cleanup_failed')
                network_blocked = reachable['exit_code'] == 0 and blocked['exit_code'] == 17 \
                    and not reachable['timed_out'] and not blocked['timed_out'] and len(accepted) == 1
            return {'workspace_write_verified': inside, 'outside_workspace_write_blocked': write_blocked,
                    'local_listener_reachable_without_sandbox': reachable['exit_code'] == 0,
                    'local_listener_blocked_in_sandbox': network_blocked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check-only', action='store_true')
    mode.add_argument('--execute-approved-runner-control', action='store_true')
    args = parser.parse_args()
    if args.check_only:
        print(json.dumps({'status': 'plan_only', 'packages': ['bubblewrap', 'apparmor-profiles', 'apparmor-utils'],
                          'profile_names': sorted(PROFILE_NAMES), 'global_sysctl_changes': False,
                          'model_calls': 0, 'host_changes_executed': False,
                          'abi4_io_uring_exception_default': False}))
        return
    report = {'status': 'running', 'model_calls': 0, 'existing_login_read': False,
              'max_native_clients': 1, 'production_modified': False, 'packages_installed': False,
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
    report['source_sha256'] = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                              ('scripts/check-linux-sandbox.py', 'scripts/test-linux-sandbox-control.py',
                               'scripts/check-native-clients.py', '.github/workflows/linux-sandbox-control.yml',
                               '.github/workflows/native-clients.yml', '.github/workflows/offline.yml')}
    folder = ROOT / 'build/linux-sandbox-control' / datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    folder.mkdir(parents=True, exist_ok=False)
    try:
        exception = os.environ.get('REFLOW_ALLOW_ABI4_IO_URING_WARNING', '0')
        require(exception in ('0', '1'), 'invalid_abi4_exception_option')
        report['abi4_io_uring_exception_requested'] = exception == '1'
        execute_control(RunnerOperations(report, allow_abi4_io_uring=exception == '1'), report)
        report['status'] = 'pass'
    except Exception as error:
        report.update(status='fail', error_type=type(error).__name__,
                      error_code=str(error) if isinstance(error, ControlError) else 'control_execution_failed')
    finally:
        (folder / 'summary.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'status': report['status'], 'outcome': report.get('outcome'),
                          'error_code': report.get('error_code'), 'model_calls': 0}), flush=True)
    raise SystemExit(0 if report['status'] == 'pass' else 1)


if __name__ == '__main__':
    main()
