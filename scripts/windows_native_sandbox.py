"""Explicit elevated sandbox setup on disposable hosted Windows CI only.

Codex 0.165.0's official setup/uninstall own the accounts, ACLs and firewall.
This module never configures a local workstation, copies sandbox credentials,
or switches to full access. Its public evidence contains fixed labels/counts.
"""
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_FIELDS = ('users', 'groups', 'firewall_rules', 'installation_keys',
                   'hidden_users', 'services', 'wfp_provider', 'wfp_sublayer')
NETWORK_REACHABLE = b'REFLOW_NETWORK_REACHABLE'
NETWORK_BLOCKED = b'REFLOW_NETWORK_BLOCKED'
NETWORK_GATES = ('local_listener_reachable_without_sandbox', 'local_listener_blocked_in_sandbox',
                 'local_listener_reachable_after_sandbox')


def require(condition, code):
    if not condition:
        raise RuntimeError(code)


def eligible(env, platform, product_type, profile):
    require(platform == 'win32' and product_type == 3, 'hosted_windows_server_required')
    expected = {'GITHUB_ACTIONS': 'true', 'RUNNER_ENVIRONMENT': 'github-hosted',
                'RUNNER_OS': 'Windows', 'GITHUB_REPOSITORY': 'chatwithgod/reflow',
                'GITHUB_WORKFLOW': 'Native client fixtures'}
    require(all(env.get(key) == value for key, value in expected.items()), 'hosted_native_ci_required')
    require(env.get('GITHUB_EVENT_NAME') in ('push', 'pull_request', 'workflow_dispatch')
            and env.get('GITHUB_RUN_ID', '').isdigit(), 'ci_run_identity_missing')
    require(Path(env.get('GITHUB_WORKSPACE', '')).resolve() == ROOT, 'ci_workspace_mismatch')
    root = Path(env.get('RUNNER_TEMP', ''))
    require(root.is_absolute() and root.is_dir(), 'runner_temp_missing')
    require(profile.resolve().parent == root.resolve() and profile.name.startswith('rf-native-ci-'),
            'ci_profile_outside_runner_temp')


def wfp_resources():
    """Query only the pinned upstream provider/sublayer GUIDs; no WFP changes."""
    api = ctypes.WinDLL('fwpuclnt.dll')
    ptr = ctypes.c_void_p
    api.FwpmEngineOpen0.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ptr, ptr, ctypes.POINTER(ptr)]
    api.FwpmEngineOpen0.restype = ctypes.c_uint32
    api.FwpmEngineClose0.argtypes = [ptr]
    api.FwpmFreeMemory0.argtypes = [ctypes.POINTER(ptr)]
    handle = ptr()
    require(api.FwpmEngineOpen0(None, 10, None, None, ctypes.byref(handle)) == 0, 'wfp_snapshot_open_failed')
    result = {}
    try:
        for label, method, key, missing in (
            ('wfp_provider', 'FwpmProviderGetByKey0', '2e31d31c-3948-4753-9117-e5d1a6496f41', 0x80320005),
            ('wfp_sublayer', 'FwpmSubLayerGetByKey0', 'e65054fd-4d32-4c7c-95ef-621f0cf6431a', 0x80320007),
        ):
            fn = getattr(api, method)
            fn.argtypes, fn.restype = [ptr, ptr, ctypes.POINTER(ptr)], ctypes.c_uint32
            guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID(key).bytes_le)
            data = ptr()
            code = fn(handle, ctypes.byref(guid), ctypes.byref(data))
            try:
                require(code in (0, missing, 0x80320008), 'wfp_snapshot_query_failed')
                result[label] = int(code == 0)
            finally:
                if data:
                    api.FwpmFreeMemory0(ctypes.byref(data))
    finally:
        api.FwpmEngineClose0(handle)
    return result


SNAPSHOT_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$names = @('CodexSandboxOffline', 'CodexSandboxOnline')
$rules = @('codex_sandbox_offline_block_outbound', 'codex_sandbox_offline_block_inbound',
  'codex_sandbox_offline_block_loopback_tcp', 'codex_sandbox_offline_block_loopback_udp',
  'codex_sandbox_offline_allow_loopback_proxy')
$installation = 'HKLM:\SOFTWARE\OpenAI\Codex\WindowsSandboxService'
$hidden = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon\SpecialAccounts\UserList'
$hiddenCount = 0
if (Test-Path -LiteralPath $hidden) {
  $hiddenKey = Get-Item -LiteralPath $hidden
  $hiddenCount = @($hiddenKey.GetValueNames() | Where-Object { $_ -in $names }).Count
}
$firewallMask = 0
$firewallBits = @{ Domain = 1; Private = 2; Public = 4 }
$firewallProfiles = @(Get-NetFirewallProfile)
$sandboxRules = @(Get-NetFirewallRule -PolicyStore ActiveStore | Where-Object { $_.DisplayName -in $rules })
foreach ($profile in $firewallProfiles) {
  if (-not $firewallBits.ContainsKey([string]$profile.Name)) { throw 'unknown_firewall_profile' }
  if ($profile.Enabled -eq $true) { $firewallMask = $firewallMask -bor $firewallBits[[string]$profile.Name] }
}
@{
  user = $identity.Name
  administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  users = @(Get-LocalUser | Where-Object { $_.Name -in $names }).Count
  groups = @(Get-LocalGroup | Where-Object { $_.Name -eq 'CodexSandboxUsers' }).Count
  firewall_rules = $sandboxRules.Count
  enabled_firewall_rules = @($sandboxRules | Where-Object Enabled -eq $true).Count
  firewall_service_running = [int]((Get-Service -Name MpsSvc).Status -eq 'Running')
  installation_keys = [int](Test-Path -LiteralPath $installation)
  hidden_users = $hiddenCount
  services = @(Get-Service -Name '*codex*sandbox*').Count
  enabled_firewall_profiles = @($firewallProfiles | Where-Object Enabled -eq $true).Count
  firewall_profile_mask = $firewallMask
} | ConvertTo-Json -Compress
'''


class Operations:
    def __init__(self, codex, pwsh, profile, env, observe):
        self.codex, self.pwsh, self.profile, self.env, self.observe = codex, pwsh, profile, env, observe

    def guard(self):
        version = sys.getwindowsversion() if sys.platform == 'win32' else None
        eligible(os.environ, sys.platform, version.product_type if version else None, self.profile)

    def snapshot(self):
        # Raw identity stays in memory for --user; only numeric fields are exported.
        process = subprocess.run([self.pwsh, '-NoProfile', '-NonInteractive', '-Command', SNAPSHOT_SCRIPT],
                                 env=self.env, cwd=self.profile, capture_output=True, timeout=45)
        require(process.returncode == 0, 'windows_sandbox_snapshot_failed')
        data = json.loads(process.stdout.decode('utf-8-sig'))
        data.update(wfp_resources())
        return data

    def setup(self, user):
        result = self.observe([str(self.codex), 'sandbox', 'setup', '--elevated', '--user', user,
                               '--codex-home', self.env['CODEX_HOME']], self.env, self.profile, timeout=120)
        require(result['status'] == 'pass', 'windows_elevated_setup_failed')
        home = Path(self.env['CODEX_HOME'])
        require((home / '.sandbox/setup_marker.json').is_file()
                and (home / '.sandbox-secrets/sandbox_users.json').is_file(), 'windows_setup_artifacts_missing')

    def uninstall(self):
        return self.observe([str(self.codex), 'sandbox', 'uninstall'], self.env, self.profile, timeout=120)

    def marker(self):
        # The setup marker has no credentials. Never read .sandbox-secrets.
        data = json.loads((Path(self.env['CODEX_HOME']) / '.sandbox/setup_marker.json').read_text(encoding='utf-8'))
        require(type(data.get('version')) is int and type(data.get('allow_local_binding')) is bool
                and isinstance(data.get('proxy_ports'), list), 'invalid_setup_marker')
        return {'version': data['version'], 'allow_local_binding': data['allow_local_binding'],
                'proxy_port_count': len(data['proxy_ports'])}


def public_snapshot(data):
    fields = (*RESOURCE_FIELDS, 'enabled_firewall_profiles', 'firewall_profile_mask',
              'enabled_firewall_rules', 'firewall_service_running')
    require(all(type(data.get(key)) is int and 0 <= data[key] < 1000 for key in fields), 'invalid_host_snapshot')
    return {key: data[key] for key in fields}


@contextmanager
def provision(ops, record, env):
    """Cleanup also runs after partial setup and a failing native test."""
    ops.guard()
    before = ops.snapshot()
    record.update(status='preparing', before=public_snapshot(before), backend='elevated',
                  max_native_clients=1, model_calls=0, host_configuration_modified=False)
    require(before.get('administrator') is True, 'elevated_ci_token_required')
    require(all(before[key] == 0 for key in RESOURCE_FIELDS), 'existing_sandbox_resources_refused')
    user = before.get('user')
    require(isinstance(user, str) and user and not any(c in user for c in '\r\n\0'), 'ci_user_missing')
    record['host_configuration_modified'] = True
    try:
        ops.setup(user)
        record['setup_completed'] = True
        record['after_setup'] = public_snapshot(ops.snapshot())
        record['setup_marker'] = ops.marker()
        # Each sequential fixture provisions its own isolated CODEX_HOME. No
        # sandbox credential is copied or reused after another setup rotates it.
        yield {**env, 'REFLOW_NATIVE_WINDOWS_SANDBOX': 'elevated',
               'REFLOW_NATIVE_WINDOWS_SETUP_READY': '1', 'REFLOW_NATIVE_WINDOWS_USER': user,
               'REFLOW_NATIVE_WINDOWS_ROOT': str(ops.profile)}
        record['status'] = 'pass'
    except BaseException:
        record['status'] = 'fail'
        raise
    finally:
        # Official uninstall removes global sandbox accounts/rules. It does not
        # restore ACLs; this is why the entry point requires an ephemeral runner.
        record['cleanup'] = ops.uninstall()
        after = public_snapshot(ops.snapshot())
        record['after'] = after
        record['resources_removed'] = all(after[key] == 0 for key in RESOURCE_FIELDS)
        record['firewall_profile_state_unchanged'] = after['firewall_profile_mask'] == before['firewall_profile_mask']
        record['acl_restoration_claimed'] = False
        if not (record['cleanup']['status'] == 'pass' and record['resources_removed']
                and record['firewall_profile_state_unchanged']):
            record['status'] = 'fail'
            raise RuntimeError('windows_sandbox_cleanup_failed')


def capture_control(command, **kwargs):
    """Capture fixed markers in memory; terminate the whole control on timeout."""
    kwargs.pop('capture_output')
    timeout = kwargs.pop('timeout')
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
                               **kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        process.communicate(timeout=5)
        raise RuntimeError('network_control_timed_out') from None
    finally:
        process.stdout.close()
        process.stderr.close()


def network_observation(result):
    """Keep only exit status, lengths and a fixed marker/error vocabulary."""
    stdout, stderr = result.stdout or b'', result.stderr or b''
    text = (stdout + stderr).decode('utf-8', errors='replace').lower()
    signals = {
        'permission_denied': ('permission denied', 'access denied', 'access is denied'),
        'process_launch_error': ('failed to spawn', 'failed to launch', 'failed to start'),
        'language_mode': ('constrainedlanguage', 'constrained language', 'methodinvocationnotsupportedinconstrainedlanguage'),
        'configuration_error': ('error loading config', 'invalid value', 'unrecognized subcommand'),
        'sandbox_error': ('windows sandbox failed', 'sandbox setup failed'),
    }
    return {'exit_code': result.returncode, 'stdout_bytes': len(stdout), 'stderr_bytes': len(stderr),
            'reachable_marker': stdout.strip() == NETWORK_REACHABLE,
            'blocked_marker': stdout.strip() == NETWORK_BLOCKED,
            'matching_output': {key: 1 for key, needles in signals.items() if any(n in text for n in needles)}}


def sandbox_identity(codex, helper, work, env, run=capture_control):
    """Export a fixed account class, never a username or SID."""
    child = [str(helper), '--identity']
    command = [str(codex), '-c', 'windows.sandbox="elevated"', 'sandbox', '--include-managed-config',
               '--permission-profile', ':workspace', '-C', str(work), '--', *child]
    observations = {}
    for label, argv in (('outside', child), ('sandbox', command)):
        result = run(argv, env=env, cwd=work, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        kinds = {b'REFLOW_IDENTITY_OFFLINE': 'offline', b'REFLOW_IDENTITY_ONLINE': 'online',
                 b'REFLOW_IDENTITY_OTHER': 'other'}
        observations[label] = {'exit_code': result.returncode,
                               'identity_class': kinds.get((result.stdout or b'').strip(), 'unknown')}
    return {'controls': observations,
            'offline_identity_verified': observations['outside'] == {'exit_code': 0, 'identity_class': 'other'}
            and observations['sandbox'] == {'exit_code': 0, 'identity_class': 'offline'}}


def network_boundary(codex, helper, work, env, run=capture_control):
    """Require connect/block/connect using one fixed native TCP helper."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(4)
        port = listener.getsockname()[1]
        child = [str(helper), f'127.0.0.1:{port}']
        options = {'env': env, 'cwd': work, 'stdin': subprocess.DEVNULL, 'capture_output': True, 'timeout': 30}
        reachable = network_observation(run(child, **options))
        positive = reachable['exit_code'] == 0 and reachable['reachable_marker']
        record = dict.fromkeys(NETWORK_GATES, False)
        record['controls'] = {'before': reachable}
        if not positive:
            return record
        command = [str(codex), '-c', 'windows.sandbox="elevated"', 'sandbox', '--include-managed-config',
                   '--permission-profile', ':workspace', '-C', str(work), '--', *child]
        blocked = network_observation(run(command, **options))
        after = network_observation(run(child, **options))
        record['controls'].update(sandbox=blocked, after=after)
        record.update(local_listener_reachable_without_sandbox=True,
                      local_listener_blocked_in_sandbox=blocked['exit_code'] == 42 and blocked['blocked_marker'],
                      local_listener_reachable_after_sandbox=after['exit_code'] == 0 and after['reachable_marker'])
        return record
