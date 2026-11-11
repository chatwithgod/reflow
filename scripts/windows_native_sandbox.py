"""Explicit elevated sandbox setup on disposable hosted Windows CI only.

Codex 0.165.0's official setup/uninstall own the accounts, ACLs and firewall.
This module never configures a local workstation, copies sandbox credentials,
or switches to full access. Its public evidence contains fixed labels/counts.
"""
from contextlib import contextmanager
import base64
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
foreach ($profile in $firewallProfiles) {
  if (-not $firewallBits.ContainsKey([string]$profile.Name)) { throw 'unknown_firewall_profile' }
  if ($profile.Enabled -eq $true) { $firewallMask = $firewallMask -bor $firewallBits[[string]$profile.Name] }
}
@{
  user = $identity.Name
  administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  users = @(Get-LocalUser | Where-Object { $_.Name -in $names }).Count
  groups = @(Get-LocalGroup | Where-Object { $_.Name -eq 'CodexSandboxUsers' }).Count
  firewall_rules = @(Get-NetFirewallRule -PolicyStore ActiveStore | Where-Object { $_.DisplayName -in $rules }).Count
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


def public_snapshot(data):
    fields = (*RESOURCE_FIELDS, 'enabled_firewall_profiles', 'firewall_profile_mask')
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


def network_boundary(codex, pwsh, work, env, run=capture_control):
    """Same fixed command must connect outside the sandbox and be blocked inside."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(4)
        port = listener.getsockname()[1]
        script = r'''
$ErrorActionPreference = 'Stop'
$client = [Net.Sockets.TcpClient]::new()
try {
  $pending = $client.BeginConnect('127.0.0.1', PORT, $null, $null)
  if (-not $pending.AsyncWaitHandle.WaitOne(2000)) { Write-Output 'REFLOW_NETWORK_BLOCKED'; exit 42 }
  $client.EndConnect($pending)
  Write-Output 'REFLOW_NETWORK_REACHABLE'; exit 0
} catch [Net.Sockets.SocketException] {
  Write-Output 'REFLOW_NETWORK_BLOCKED'; exit 42
} finally { $client.Dispose() }
'''.replace('PORT', str(port))
        payload = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
        child = [pwsh, '-NoProfile', '-NonInteractive', '-EncodedCommand', payload]
        options = {'env': env, 'cwd': work, 'stdin': subprocess.DEVNULL, 'capture_output': True, 'timeout': 30}
        reachable = run(child, **options)
        positive = reachable.returncode == 0 and reachable.stdout.strip() == NETWORK_REACHABLE
        if not positive:
            return {'local_listener_reachable_without_sandbox': False, 'local_listener_blocked_in_sandbox': False}
        command = [str(codex), '-c', 'windows.sandbox="elevated"', 'sandbox', '--include-managed-config',
                   '--permission-profile', ':workspace', '-C', str(work), '--', *child]
        blocked = run(command, **options)
        return {'local_listener_reachable_without_sandbox': True,
                'local_listener_blocked_in_sandbox': blocked.returncode == 42 and blocked.stdout.strip() == NETWORK_BLOCKED}
