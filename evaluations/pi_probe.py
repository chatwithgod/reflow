"""Plan or run one bounded, read-only Pi OpenAI OAuth probe. No API keys."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

import run as execution
from pi_events import PiEvents

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
PROMPT = 'Use the read tool exactly once to read probe.txt in the current workspace. Reply only with the entire file content. Do not use other tools or inspect other paths.'


def credential_for_probe(data, timeout, now=None):
    """Use fresh Pi-owned public OAuth access; never copy a renewable session."""
    now = time.time() if now is None else now
    value = data.get('openai') if isinstance(data, dict) else None
    if not isinstance(value, dict) or value.get('type') != 'oauth':
        raise ValueError('pi_public_oauth_required')
    if not isinstance(value.get('access'), str) or not value['access'] or value['access'].startswith('sk-'):
        raise ValueError('oauth_access_required')
    expires = value.get('expires')
    if type(expires) not in (int, float) or not math.isfinite(expires) or expires / 1000 <= now + timeout + 420:
        raise ValueError('fresh_oauth_access_required')
    if not isinstance(value.get('clientId'), str) or not value['clientId'] or value['clientId'] == 'dynamic_agent_client':
        raise ValueError('issued_pi_client_required')
    scopes = value.get('scopes')
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes) or not {'resource.invoke', 'chatgpt.tokens.use.direct'}.issubset(scopes):
        raise ValueError('chatgpt_plan_permission_required')
    return {'type': 'oauth', 'access': value['access'], 'refresh': '', 'expires': expires,
            'clientId': value['clientId'], 'scopes': list(scopes)}


def check_catalog(credential, model):
    """One account metadata request, no inference; retain no catalog or credentials."""
    request = urllib.request.Request('https://api.openai.com/v1/models',
        headers={'Authorization': 'Bearer ' + credential['access']})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read(1 << 20))
            models = data.get('models') if isinstance(data, dict) else None
            available = isinstance(models, list) and any(isinstance(item, dict) and
                item.get('slug') == model and item.get('visibility') == 'list' for item in models)
            return {'status': 'pass' if available else 'model_not_verified', 'http_status': response.status,
                    'metadata_requests': 1, 'model_available': available, 'inference_requests': 0}
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        return {'status': 'http_error', 'http_status': status, 'metadata_requests': 1,
                'inference_requests': 0, 'rate_limit_detected': status == 429}
    except Exception as error:
        return {'status': 'catalog_error', 'error_type': type(error).__name__, 'metadata_requests': 1, 'inference_requests': 0}


def probe(args, report, credential, upstream):
    record = {'mode': 'synthetic' if args.synthetic_upstream else 'live', 'trial_concurrency': 1,
              'model': args.model, 'effort': 'high', 'timeout_seconds': args.timeout,
              'max_continue': 1, 'provider_retries': 0, 'agent_retries': 0}
    proxy = agent = listener = reader = None
    with tempfile.TemporaryDirectory(prefix='trial-', dir=report) as temporary:
        profile = Path(temporary).resolve()
        assert profile.is_relative_to(report.resolve())
        env = execution.trial_env(profile)
        work, pi_home = profile/'workspace', profile/'pi'
        work.mkdir()
        pi_home.mkdir()
        expected = 'REFLOW_PI_PROBE_' + secrets.token_hex(16)
        fixture = work/'probe.txt'
        fixture.write_text(expected+'\n', encoding='utf-8')
        fixture_hash = hashlib.sha256(fixture.read_bytes()).hexdigest()
        (pi_home/'auth.json').write_text(json.dumps({'openai': credential}), encoding='utf-8')
        (pi_home/'settings.json').write_text(json.dumps({'transport': 'sse', 'cacheWarming': 'off',
            'compaction': {'enabled': False}, 'retry': {'enabled': False, 'maxRetries': 0, 'provider': {'maxRetries': 0}}}), encoding='utf-8')
        env.update(PI_CODING_AGENT_DIR=str(pi_home), PI_OFFLINE='1', PI_TELEMETRY='0')
        try:
            proxy, endpoint, listener = execution.start_proxy(args.reflow, 1, env, upstream=upstream)
            env['REFLOW_URL'] = endpoint
            command = [str(args.node), str(args.pi_cli), '--offline', '--print', '--mode', 'json', '--no-session',
                '--no-extensions', '--no-mcp', '--no-skills', '--no-prompt-templates', '--no-themes', '--no-context-files',
                '--extension', str(args.adapter_dir/'reflow-openai.ts'), '--extension', str(HERE/'pi_probe_guard.ts'),
                '--tools', 'read', '--provider', 'openai', '--model', args.model, '--thinking', 'high', PROMPT]
            started = time.monotonic()
            agent = subprocess.Popen(command, cwd=work, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **execution.spawn_options())
            observations = PiEvents(expected, lambda: execution.read_metrics(endpoint, timeout=0.2), started,
                                    lambda: execution.stop(agent))
            parse_counts = {'non_json_lines': 0}
            def consume():
                while True:
                    raw = agent.stdout.readline(1 << 20)
                    if not raw:
                        return
                    try:
                        event = json.loads(raw)
                        if not isinstance(event, dict):
                            raise ValueError()
                    except (ValueError, UnicodeDecodeError):
                        parse_counts['non_json_lines'] += 1
                        continue
                    observations.observe(event)
            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            timed_out = False
            try:
                agent.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                execution.stop(agent)
            reader.join(timeout=5)
            record.update(status='timeout' if timed_out else 'finished' if agent.returncode == 0 else 'agent_error',
                exit_code=agent.returncode, elapsed_seconds=round(time.monotonic()-started, 3),
                reader_finished=not reader.is_alive(), **observations.summary(), **parse_counts)
            metrics = execution.read_metrics(endpoint)
            record['upstream_metrics'] = metrics
            record['fixture_unchanged'] = fixture.is_file() and hashlib.sha256(fixture.read_bytes()).hexdigest() == fixture_hash
            record['workspace_extra_files'] = len([path for path in work.iterdir() if path.name != 'probe.txt'])
            if record['rate_limit_detected']:
                record['status'] = 'rate_limited'
            usage = record['client_reported_usage']
            record['client_usage_including_cache'] = {'input_tokens': usage['input']+usage['cacheRead']+usage['cacheWrite'],
                'output_tokens': usage['output'], 'cached_tokens': usage['cacheRead'], 'reasoning_tokens': usage['reasoning']}
            record['usage_complete'] = bool(metrics and metrics['usage_complete'] and
                metrics['requests'] == metrics['completed'] == metrics['usage_reports'] and
                record['usage_reports'] == record['assistant_messages'] and record['invalid_usage_reports'] == 0)
            record['client_usage_within_upstream_totals'] = bool(record['usage_complete'] and all(
                value <= metrics[key] for key, value in record['client_usage_including_cache'].items()) and
                usage['reasoning'] == metrics['reasoning_tokens'])
            diagnostic = record['event_diagnostics']
            record['read_tool_roundtrip_passed'] = bool(record['status'] == 'finished' and record['agent_ends'] == 1
                and record['final_stop_reason'] == 'stop' and record['tool_starts'] == record['tool_ends'] == 1
                and record['tool_failures'] == record['unexpected_tools'] == record['error_events'] == 0
                and record['fixture_read_matched'] and record['final_fixture_matched'] and record['fixture_unchanged']
                and record['workspace_extra_files'] == 0 and record['reader_finished'] and not record['event_trace_truncated']
                and record['guard_observations_valid'] and record['guard'] == {'allowed': 1, 'blocked': 0}
                and record['client_usage_within_upstream_totals'] and metrics['requests'] >= 2
                and all(metrics[key] == 0 for key in ('failed', 'parse_errors', 'unsupported_responses', 'tool_tracking_drops'))
                and diagnostic['counter_probe_errors'] == diagnostic['tool_id_tracking_drops'] == diagnostic['unfinished_tracked_tools'] == 0)
            record['continuation_tool_finish_observed'] = bool(record['read_tool_roundtrip_passed']
                and metrics.get('continuations', 0) > 0 and metrics.get('continued_tool_results', 0) > 0)
            record['real_account_continuation_tool_finish_observed'] = record['mode'] == 'live' and record['continuation_tool_finish_observed']
        except Exception as error:
            record.update(status='probe_error', error_type=type(error).__name__, read_tool_roundtrip_passed=False)
        finally:
            execution.stop(agent)
            execution.stop(proxy)
            if reader: reader.join(timeout=5)
            if listener: listener.join(timeout=5)
            if agent is not None: agent.stdout.close()
            if proxy is not None: proxy.stderr.close()
    record['remaining_trial_profiles'] = len(list(report.glob('trial-*')))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--run-live', action='store_true')
    mode.add_argument('--synthetic-upstream')
    parser.add_argument('--auth-file', type=Path)
    parser.add_argument('--node', type=Path, default=Path(shutil.which('node') or 'node'))
    parser.add_argument('--pi-cli', type=Path, default=ROOT/'.tools/native-clients/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js')
    parser.add_argument('--adapter-dir', type=Path, default=ROOT/'adapters/pi')
    parser.add_argument('--reflow', type=Path, required=True)
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    if not 30 <= args.timeout <= 180:
        parser.error('timeout must be 30..180')
    if args.run_live and not args.auth_file:
        parser.error('live execution needs an explicit Pi OAuth credential file')
    upstream = 'https://api.openai.com/v1'
    if args.synthetic_upstream:
        value = urlparse(args.synthetic_upstream)
        if value.scheme != 'http' or value.hostname not in ('127.0.0.1', 'localhost', '::1') or value.username or value.password or value.path != '/v1' or value.query or value.fragment:
            parser.error('synthetic upstream must be a loopback HTTP /v1 endpoint')
        upstream = args.synthetic_upstream
    for name in ('node', 'pi_cli', 'reflow', 'adapter_dir'):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    report = ROOT/'build/pi-probes'/datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    report.mkdir(parents=True, exist_ok=False)
    plan = {'kind': 'single_pi_oauth_read_probe', 'provider': 'openai', 'model': args.model, 'effort': 'high',
        'trial_concurrency': 1, 'timeout_seconds': args.timeout, 'max_continue': 1, 'max_sessions': 1,
        'provider_retries': 0, 'agent_retries': 0, 'cache_warming': 'off', 'native_subagents_enabled': False,
        'permitted_tools': ['one read of generated probe.txt'], 'refresh_token_copied': False,
        'api_key_used': False, 'live_execution': args.run_live, 'synthetic_execution': bool(args.synthetic_upstream),
        'source_sha256': {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (HERE/'pi_probe.py', HERE/'pi_events.py', HERE/'pi_probe_guard.ts', HERE/'run.py')},
        'adapter_sha256': {name: hashlib.sha256((args.adapter_dir/name).read_bytes()).hexdigest()
            for name in ('reflow-openai.ts', 'lib/openai-transport.mjs')},
        'binary_sha256': {name: hashlib.sha256(getattr(args, name).read_bytes()).hexdigest() for name in ('node', 'pi_cli', 'reflow')},
        'result': None, 'credential_read': False}
    auth_digest = credential = None
    if args.run_live:
        try:
            raw = args.auth_file.read_bytes()
            auth_digest = hashlib.sha256(raw).hexdigest()
            plan['credential_read'] = True
            credential = credential_for_probe(json.loads(raw.decode('utf-8-sig')), args.timeout)
            plan['model_catalog'] = check_catalog(credential, args.model)
            if plan['model_catalog']['status'] != 'pass':
                credential = None
                plan['preflight_status'] = 'catalog_not_ready'
        except Exception as error:
            plan.update(preflight_status='credential_not_ready', preflight_error_type=type(error).__name__)
            credential = None
    elif args.synthetic_upstream:
        credential = credential_for_probe({'openai': {'type': 'oauth', 'access': 'synthetic-pi-public-oauth',
            'refresh': 'synthetic-refresh-must-not-be-copied', 'expires': (time.time()+3600)*1000,
            'clientId': 'synthetic-public-client', 'scopes': ['resource.invoke', 'chatgpt.tokens.use.direct']}}, args.timeout)
    if credential is not None:
        plan['result'] = probe(args, report, credential, upstream)
    if auth_digest is not None:
        plan['source_auth_unchanged'] = args.auth_file.is_file() and hashlib.sha256(args.auth_file.read_bytes()).hexdigest() == auth_digest
    plan['real_account_inference_requests'] = ((plan['result'].get('upstream_metrics') or {}).get('requests', 0)
        if args.run_live and plan['result'] else 0)
    (report/'results.json').write_text(json.dumps(plan, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'report': report.relative_to(ROOT).as_posix(), 'status': plan['result']['status'] if plan['result'] else plan.get('preflight_status', 'planned'),
                      'live_execution': args.run_live, 'credential_read': plan['credential_read']}))


if __name__ == '__main__':
    main()
