#!/usr/bin/env python3
"""Check a separate Reflow process before pinned, unchanged Magpie using local fixtures."""
import argparse
import collections
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
BASE = 'bca0d6d69a806ae941bf9a5a6fafe4c7e03322b9'
PROBE = Path('internal/gateway/reflow_external_probe_test.go')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--magpie', type=Path, required=True)
    parser.add_argument('--go', type=Path, required=True)
    parser.add_argument('--compiler', type=Path)
    parser.add_argument('--phase', choices=('normal', 'race', 'negative', 'standard', 'all'), default='all')
    args = parser.parse_args()
    host, go = args.magpie.resolve(strict=True), args.go.resolve(strict=True)
    fixture = ROOT / 'scripts/testdata/magpie/reflow_external_probe_test.go'
    def git(*values):
        return subprocess.check_output(['git', *values], cwd=host).decode('utf-8').strip()
    if git('rev-parse', 'HEAD') != BASE or git('diff', '--name-only') or git('diff', '--cached', '--name-only'):
        raise RuntimeError('Magpie must be an unchanged isolated checkout at the pinned base')
    untracked = git('ls-files', '--others', '--exclude-standard').splitlines()
    if any(name != PROBE.as_posix() for name in untracked):
        raise RuntimeError('Unexpected untracked files in the Magpie checkout')
    target = host / PROBE
    if target.exists() and target.read_bytes() != fixture.read_bytes():
        raise RuntimeError('Existing probe differs; review it before replacing anything')
    target.write_bytes(fixture.read_bytes())
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    report = ROOT / 'build/magpie-external-ci' / stamp
    report.mkdir(parents=True, exist_ok=False)
    binary = report / ('reflow.exe' if os.name == 'nt' else 'reflow')
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PROGRAMDATA',
        'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE'}}
    env.update(GOPATH=str(ROOT/'.tools/gopath'), GOMODCACHE=str(ROOT/'.tools/gopath/pkg/mod'),
               GOCACHE=str(ROOT/'.tools/magpie-gocache'), GOTOOLCHAIN='local', GOENV='off',
               GOWORK='off', GOPROXY='off', CGO_ENABLED='0',
               GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='core.longpaths', GIT_CONFIG_VALUE_0='true')
    if args.compiler:
        env['CC'] = str(args.compiler.resolve(strict=True))
    locks = {name: digest(host/name) for name in ('go.mod', 'go.sum')}
    summary = {'magpie_base': BASE, 'magpie_tree': git('rev-parse', 'HEAD^{tree}'),
               'reflow_head': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
               'runner_sha256': digest(Path(__file__)), 'probe_sha256': digest(fixture),
               'runtime_source_sha256': {str(p.relative_to(ROOT)).replace('\\','/'): digest(p)
                                         for folder in ('core', 'proxy', 'cmd/reflow', 'internal/version')
                                         for p in sorted((ROOT/folder).glob('*.go')) if not p.name.endswith('_test.go')},
               'status': 'running', 'checks': {}, 'test_concurrency': 1, 'model_calls': 0,
               'synthetic_auth': True, 'existing_login_read': False, 'production_modified': False,
               'magpie_runtime_modified': False, 'native_codex_or_pi_client_used': False,
               'upstream_transport': 'HTTP with synthetic ChatGPT accounts', 'raw_output_persisted': False}
    print(json.dumps({'report': str(report.relative_to(ROOT)), 'phase': args.phase}), flush=True)

    def run(command, cwd, phase, timeout=300):
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **options)
        try:
            raw, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
            else:
                import signal
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=15)
            raise RuntimeError('isolated_process_timeout')
        counts, markers = collections.Counter(), collections.Counter()
        events, numeric, build_errors, diagnostics = [], [], [], []
        for line in raw.decode('utf-8', errors='replace').splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                for marker in ('magpie profile requires an explicit --upstream gateway URL',
                               'unknown upstream profile; choose standard or magpie'):
                    if marker in line:
                        markers[marker] += 1
                if re.search(r'\.go:\d+:', line):
                    build_errors.append(line.replace(str(ROOT), '<reflow-checkout>').replace(str(host), '<magpie-checkout>'))
                continue
            action = event.get('Action')
            if action in ('pass', 'skip', 'fail'):
                events.append({k:event[k] for k in ('Time','Action','Package','Test','Elapsed') if k in event})
                if event.get('Test'):
                    counts[action] += 1
            output = event.get('Output', '')
            if 'REFLOW_EXTERNAL_HTTP_ERROR' in output or 'external_turn_not_completed events=' in output:
                diagnostics.append({'test':event.get('Test'), 'values':dict(re.findall(r'(status|events|backend|gateway|missing_parent|incomplete|error)=(\d+|true|false)',output))})
            for marker in ('upstream_account_changed', 'continuation_identity_changed',
                           'external_first_status', 'external_turn_not_completed', 'external_socket_read_failed',
                           'hidden_round_did_not_start', 'hidden_upstream_was_not_canceled',
                           'history_calls', 'account_failure_not_stopped', 'unknown_account_status',
                           'unexpected_numeric_metrics', 'backend_requests', 'reflow_ready_timeout',
                           'reflow_exited_before_ready', 'reflow_process_did_not_exit', 'reflow_stderr_reader_did_not_exit',
                           'socket_interrupt_contract_failed', 'canceled_turn_exposed_tool', 'reflow_child_data_race',
                           'hidden_socket_round_ended_before_interrupt', 'socket_cancel_terminal_missing'):
                if marker in output:
                    markers[marker] += 1
            if action == 'build-output' and re.search(r'\.go:\d+:', output):
                build_errors.append(output.strip().replace(str(ROOT), '<reflow-checkout>').replace(str(host), '<magpie-checkout>'))
            match = re.search(r'REFLOW_EXTERNAL_COUNTS requests=(\d+) continuation=(\d+) tool_executions=(\d+) tool_results=(\d+) account_changes=(\d+)', output)
            if match:
                numeric.append(dict(zip(('requests','continuation','tool_executions','tool_results','account_changes'), map(int,match.groups()))))
        result = {'exit_code': process.returncode, 'test_items': {k:counts[k] for k in ('pass','skip','fail')},
                  'markers':dict(markers), 'numeric_cases':numeric, 'build_errors':build_errors,
                  'events':events, 'diagnostics':diagnostics, 'command':command, 'output_bytes':len(raw),
                  'output_sha256':hashlib.sha256(raw).hexdigest()}
        summary['checks'][phase] = result
        (report/(phase+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps({'phase':phase, **{k:result[k] for k in ('exit_code','test_items','markers','build_errors','diagnostics')}}),flush=True)
        return result

    code = 1
    try:
        with tempfile.TemporaryDirectory(prefix='rf-magpie-external-') as temporary:
            home = Path(temporary)
            for key,sub in {'HOME':'','USERPROFILE':'','APPDATA':'appdata','LOCALAPPDATA':'localappdata',
                            'XDG_CONFIG_HOME':'config','XDG_CACHE_HOME':'cache','XDG_DATA_HOME':'data',
                            'TEMP':'temp','TMP':'temp'}.items():
                directory=home/sub;directory.mkdir(parents=True,exist_ok=True);env[key]=str(directory)
            built = run([str(go),'build','-mod=readonly','-trimpath','-buildvcs=false','-o',str(binary),'./cmd/reflow'],ROOT,'build')
            if built['exit_code']:
                raise RuntimeError('reflow_build_failed')
            summary['binary_sha256'] = digest(binary)
            for label, arguments, marker in (
                ('profile_requires_gateway',['--upstream-profile','magpie'],'magpie profile requires an explicit --upstream gateway URL'),
                ('profile_rejects_unknown',['--upstream-profile','unknown'],'unknown upstream profile; choose standard or magpie')):
                guarded = run([str(binary),*arguments],ROOT,label,timeout=10)
                if guarded['exit_code'] != 1 or guarded['markers'].get(marker) != 1:
                    raise RuntimeError('upstream_profile_guard_failed')
            phases = ('normal','race','negative','standard') if args.phase == 'all' else (args.phase,)
            binaries = {str(binary): digest(binary)}
            for phase in phases:
                race = phase == 'race'
                env['CGO_ENABLED'] = '1' if race else '0'
                active_binary = binary
                if race:
                    active_binary = report / ('reflow-race.exe' if os.name == 'nt' else 'reflow-race')
                    built = run([str(go),'build','-race','-mod=readonly','-trimpath','-buildvcs=false','-o',str(active_binary),'./cmd/reflow'],ROOT,'build-race')
                    if built['exit_code']:
                        raise RuntimeError('reflow_race_build_failed')
                    binaries[str(active_binary)] = digest(active_binary)
                selection = '^TestExternalReflowMagpie$'
                if phase == 'negative': selection = '^TestExternalReflowMagpie/native_http$'
                if phase == 'standard': selection = '^TestExternalReflowMagpie/(native_http|native_ws)$'
                command=[str(go),'test','-mod=readonly','-tags','nogui reflow_external_probe','-p=1','-parallel=1',
                         '-count=1','-timeout=3m','-json']
                if race: command.append('-race')
                command += ['-run',selection,'./internal/gateway','-args','-reflow-probe-bin',str(active_binary)]
                if phase == 'negative': command.append('-reflow-probe-drop-pin')
                if phase == 'standard': command.append('-reflow-probe-standard-profile')
                result = run(command,host,phase)
                if phase == 'negative':
                    if result['exit_code'] == 0 or not result['markers'].get('upstream_account_changed'):
                        raise RuntimeError('account_pin_negative_control_not_observed')
                elif phase == 'standard':
                    if (result['exit_code'] == 0 or result['test_items'] != {'pass':0,'skip':0,'fail':3}
                            or not any(d['values'].get('missing_parent') == 'true' for d in result['diagnostics'])
                            or result['markers'].get('external_turn_not_completed', 0) != 2):
                        raise RuntimeError('standard_profile_compatibility_failures_not_observed')
                elif result['exit_code'] or result['test_items'] != {'pass':8,'skip':0,'fail':0}:
                    raise RuntimeError('external_chain_check_failed')
            summary['binary_hashes'] = binaries
            summary['binary_unchanged'] = all(digest(Path(path)) == value for path, value in binaries.items())
        summary['isolated_home_removed'] = not home.exists()
        summary['module_files_unchanged'] = locks == {name:digest(host/name) for name in locks}
        summary['magpie_tracked_files_unchanged'] = not git('diff','--name-only') and not git('diff','--cached','--name-only')
        if not all(summary[k] for k in ('binary_unchanged','isolated_home_removed','module_files_unchanged','magpie_tracked_files_unchanged')):
            raise RuntimeError('verification_boundary_changed')
        summary['status'], code = 'pass', 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        summary.update(status='fail', error_type=type(error).__name__)
        if isinstance(error, RuntimeError): summary['error_marker'] = str(error)
    finally:
        (report/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8',newline='\n')
        print(json.dumps({'status':summary['status'],'report':str(report.relative_to(ROOT)),'error_marker':summary.get('error_marker')}),flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
