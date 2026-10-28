"""Verify extracted native packages with pinned CLIs and synthetic login only."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CLIENT_TESTS = ('TestCodexNativeLoginOffline', 'TestCodexAppServerOffline',
                'TestCodexPluginInstallAndStdioOffline', 'TestPiOAuthOffline')
TARGETS = {
    ('win32', 'x64'): ('windows/amd64', 'x86_64-pc-windows-msvc'),
    ('win32', 'arm64'): ('windows/arm64', 'aarch64-pc-windows-msvc'),
    ('linux', 'x64'): ('linux/amd64', 'x86_64-unknown-linux-musl'),
    ('linux', 'arm64'): ('linux/arm64', 'aarch64-unknown-linux-musl'),
    ('darwin', 'x64'): ('darwin/amd64', 'x86_64-apple-darwin'),
    ('darwin', 'arm64'): ('darwin/arm64', 'aarch64-apple-darwin'),
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def command_path(value):
    found = shutil.which(value)
    require(found is not None, f'Required executable is missing: {value}')
    return str(Path(found).resolve(strict=True))


def isolated_env(profile, compiler=''):
    keep = {'PATH', 'SYSTEMROOT', 'SYSTEMDRIVE', 'WINDIR', 'COMSPEC', 'PATHEXT',
            'PROGRAMDATA', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE'}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    for key, child in {'HOME': 'home', 'USERPROFILE': 'home', 'APPDATA': 'appdata',
                       'LOCALAPPDATA': 'localappdata', 'TEMP': 'temp', 'TMP': 'temp', 'TMPDIR': 'temp',
                       'CODEX_HOME': 'codex', 'PI_CODING_AGENT_DIR': 'pi'}.items():
        path = profile / child
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update(GOENV='off', GOWORK='off', GOTOOLCHAIN='local',
               GOPATH=str(ROOT / '.tools/gopath'), GOMODCACHE=str(ROOT / '.tools/gopath/pkg/mod'),
               GOCACHE=str(ROOT / '.tools/gocache'), NO_PROXY='127.0.0.1,localhost',
               PI_OFFLINE='1', PI_TELEMETRY='0')
    if compiler:
        env['CC'] = command_path(compiler)
    return env


def go_result(log, returncode, required):
    counts = Counter()
    passed = set()
    package_passed = False
    bad = False
    for line in log.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        action, test = event.get('Action'), event.get('Test')
        if action == 'fail' or (test and action == 'skip'):
            bad = True
        if test and action in ('pass', 'skip', 'fail'):
            counts[action] += 1
        if action == 'pass':
            if test:
                passed.add(test)
            else:
                package_passed = True
    result = {'exit_code': returncode, 'tests': {key: counts[key] for key in ('pass', 'skip', 'fail')},
              'required_tests': list(required), 'missing_tests': sorted(set(required) - passed),
              'passed_names': sorted(passed), 'package_passed': package_passed}
    result['status'] = 'pass' if returncode == 0 and not bad and package_passed and not result['missing_tests'] else 'fail'
    return result


def extract_package(archive_path, destination, executable, expected_hash):
    destination.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        require(archive.testzip() is None, 'Archive CRC check failed')
        for entry in archive.infolist():
            relative = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            require(not relative.is_absolute() and '..' not in relative.parts and '\\' not in entry.filename
                    and ':' not in entry.filename and not stat.S_ISLNK(mode), 'Unsafe archive member')
            target = destination.joinpath(*relative.parts)
            require(target.resolve().is_relative_to(destination.resolve()), 'Archive member escapes destination')
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                output.write(archive.read(entry))
            if entry.filename == executable:
                require(mode & 0o111 == 0o111, 'Archive is missing executable permission bits')
                if os.name != 'nt':
                    target.chmod(0o755)
    binary = destination / executable
    require(binary.is_file() and digest(binary) == expected_hash, 'Extracted binary hash mismatch')
    return binary


def run_checks(args, report, summary):
    go, node, pwsh = map(command_path, (args.go_exe, args.node_exe, args.pwsh_exe))
    clients = args.clients_dir.resolve(strict=True)
    manifest_source = ROOT / 'ci/native-clients/package.json'
    lock_source = ROOT / 'ci/native-clients/package-lock.json'
    require(digest(clients / 'package-lock.json') == digest(lock_source), 'Installed dependency lock differs from the tracked lock')
    dependencies = read_json(manifest_source)['dependencies']
    for name, version in dependencies.items():
        require(read_json(clients / 'node_modules' / name / 'package.json')['version'] == version,
                f'Installed client version differs from the pin: {name}')
    # No inherited account, provider key, user configuration, or HTTP proxy.
    temporary_root = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix='rf-native-ci-', dir=temporary_root) as temporary:
        profile = Path(temporary).resolve()
        require(profile.parent == temporary_root, 'Isolated profile escaped the temporary directory')
        env = isolated_env(profile, args.compiler)
        identity = json.loads(subprocess.check_output(
            [node, '-p', 'JSON.stringify({platform:process.platform,arch:process.arch,version:process.version})'],
            cwd=profile, env=env, text=True))
        target, triple = TARGETS[(identity['platform'], identity['arch'])]
        go_target = '/'.join(subprocess.check_output([go, 'env', 'GOHOSTOS', 'GOHOSTARCH'], env=env, text=True).split())
        require(go_target == target, 'Node and Go do not target the same native platform')
        package = clients / 'node_modules/@openai' / f"codex-{identity['platform']}-{identity['arch']}"
        binary_name = 'codex.exe' if os.name == 'nt' else 'codex'
        codex = package / 'vendor' / triple / 'bin' / binary_name
        host = codex.with_name('codex-code-mode-host.exe' if os.name == 'nt' else 'codex-code-mode-host')
        require(codex.is_file() and host.is_file(), 'Pinned native Codex or Code Mode host is missing')
        pi = clients / 'node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js'
        require(pi.is_file(), 'Pinned Pi CLI entry point is missing')
        hashes_before = {'codex': digest(codex), 'code_mode_host': digest(host)}
        version = subprocess.check_output([str(codex), '--version'], cwd=profile, env=env, text=True).strip()
        require(version == 'codex-cli ' + dependencies['@openai/codex'], 'Native Codex version does not match the pin')
        summary.update(platform=target, node=identity, codex_version=version,
                       pi_version=dependencies['@earendil-works/pi-coding-agent'], client_sha256=hashes_before)

        dist = ROOT / 'dist' / (ROOT / 'VERSION').read_text().strip()
        before = set(dist.glob('*/manifest.json'))
        with (report / 'build.log').open('w', encoding='utf-8') as log:
            result = subprocess.run([pwsh, '-NoProfile', '-File', str(ROOT / 'scripts/build.ps1'),
                                     '-GoExe', go, '-PythonExe', sys.executable, '-CurrentPlatform', '-WithCodexPlugin'],
                                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        require(result.returncode == 0, f'Native package build failed; see {report / "build.log"}')
        created = set(dist.glob('*/manifest.json')) - before
        require(len(created) == 1, 'Expected exactly one newly built manifest')
        manifest_path = created.pop()
        entries = read_json(manifest_path)
        require(len(entries) == 2 and {entry['kind'] for entry in entries} == {'standalone', 'codex-plugin'},
                'Expected standalone and plugin packages')
        extracted = {}
        summary['packages'] = []
        for entry in entries:
            require(entry['platform'] == target, 'Package platform differs from this runner')
            reflow_name = 'reflow.exe' if os.name == 'nt' else 'reflow'
            expected_binary = reflow_name if entry['kind'] == 'standalone' else 'plugins/reflow/bin/' + reflow_name
            require(entry['binary_path'] == expected_binary, 'Unexpected packaged binary location')
            archive = manifest_path.parent / entry['archive']
            require(archive.parent == manifest_path.parent and digest(archive) == entry['sha256'], 'Archive hash mismatch')
            destination = profile / entry['kind']
            extracted[entry['kind']] = extract_package(archive, destination, entry['binary_path'], entry['binary_sha256'])
            summary['packages'].append({**entry, 'source_archive': archive.relative_to(ROOT).as_posix(),
                                        'archive_hash_verified': True, 'extracted_binary_verified': True})
        require(digest(extracted['standalone']) == digest(extracted['codex-plugin']), 'Standalone and plugin binaries differ')
        env.update(REFLOW_CODEX_BIN=str(codex), REFLOW_NODE_BIN=node, REFLOW_PI_CLI=str(pi),
                   REFLOW_PROXY_BIN=str(extracted['standalone']), REFLOW_PLUGIN_MARKETPLACE=str(profile / 'codex-plugin'),
                   GOPROXY='off')
        for phase, race, tagged, required in [('native', False, False, CLIENT_TESTS),
                                              ('race', True, False, CLIENT_TESTS),
                                              ('write', False, True, ('TestCodexNativeWriteProbe',))]:
            command = [go, 'test', '-p=1', '-parallel=1', '-json', '-count=1', '-timeout=5m']
            if race:
                command += ['-race']
            if tagged:
                command += ['-tags', 'native_write_probe']
            command += ['-run', '^(' + '|'.join(required) + ')$', './integration']
            phase_env = {**env, 'CGO_ENABLED': '1' if race else '0'}
            log_path = report / (phase + '.jsonl')
            print(f'Native client phase: {phase}; one client at a time; synthetic login only.', flush=True)
            with log_path.open('w', encoding='utf-8') as log:
                result = subprocess.run(command, cwd=ROOT, env=phase_env, stdout=log, stderr=subprocess.STDOUT, timeout=420)
            summary['checks'][phase] = go_result(log_path, result.returncode, required)
            summary['checks'][phase]['log_sha256'] = digest(log_path)
            require(summary['checks'][phase]['status'] == 'pass', f'Native phase {phase} failed; see {log_path}')
        summary['client_binaries_unchanged'] = hashes_before == {'codex': digest(codex), 'code_mode_host': digest(host)}
        require(summary['client_binaries_unchanged'], 'A native client binary changed during verification')
        for entry in summary['packages']:
            require(digest(extracted[entry['kind']]) == entry['binary_sha256'], 'A Reflow binary changed during verification')
            entry['runtime_tested'] = True
    summary['isolated_profile_removed'] = not profile.exists()
    require(summary['isolated_profile_removed'], 'Isolated profile was not removed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--go-exe', default='go')
    parser.add_argument('--node-exe', default='node')
    parser.add_argument('--pwsh-exe', default='pwsh')
    parser.add_argument('--compiler', default='')
    parser.add_argument('--clients-dir', type=Path, default=ROOT / '.tools/native-clients')
    args = parser.parse_args()
    report = ROOT / 'build/native-client-ci' / datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    report.mkdir(parents=True)
    sources = ['scripts/check-native-clients.py', 'scripts/build.ps1', 'scripts/archive.py',
               'ci/native-clients/package.json', 'ci/native-clients/package-lock.json',
               '.github/workflows/native-clients.yml', 'adapters/pi/reflow.ts',
               'plugins/codex/plugin.json', 'plugins/codex/mcp.json', 'go.mod', 'go.sum', 'VERSION']
    sources += [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / 'integration').glob('*.go'))]
    summary = {'status': 'running', 'created_utc': datetime.now(timezone.utc).isoformat(),
               'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'source_sha256': {name: digest(ROOT / name) for name in sources},
               'checks': {}, 'max_native_clients': 1, 'synthetic_auth': True, 'model_calls': 0,
               'existing_login_read': False, 'production_modified': False,
               'desktop_dot_ui_tested': False, 'scope': 'native extracted packages and local fixture upstreams only'}
    print(f'Native client evidence: {report}', flush=True)
    try:
        run_checks(args, report, summary)
        summary['status'] = 'pass'
    except Exception as error:
        summary.update(status='fail', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        (report / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
