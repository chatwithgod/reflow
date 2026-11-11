"""Test a real CPA process against a local, synthetic Codex upstream.

Only the explicitly supplied executable and plugin DLL are read. A fresh
temporary config/auth/plugin directory and two loopback listeners are used;
production config, account records and services are never opened or changed.
No real provider endpoint or credential is configured. This is an offline
integration test, not evidence of successful live OpenAI or Codex Desktop use.
"""

import argparse
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

from native_smoke import round_events, wire
from fixture_websocket import FixtureWebSocket, LoopbackWebSocketClient, accept_key


FIXTURE_KEY = "isolated-fixture-only"
MODEL = "gpt-6-luna"
MODEL_ALIASES = [MODEL, "gpt-6-sol", "gpt-6-astra", "gpt-7-fixture", "lab/gpt-6-sol", "gpt-4o", "fixture-alias"]
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def local_request(url, body=None, method=None):
    if not url.startswith("http://127.0.0.1:"):
        raise ValueError("only loopback HTTP requests are allowed")
    request = urllib.request.Request(
        url, data=wire(body) if body is not None else None,
        headers={"Authorization": f"Bearer {FIXTURE_KEY}", "Content-Type": "application/json"},
        method=method,
    )
    with OPENER.open(request, timeout=15) as response:
        return response.status, response.headers, response.read()


class FixtureUpstream(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), FixtureHandler)
        self.control_lines = False
        self.rounds = [round_events(1, reasoning=0)]
        self.calls = []
        self.transports = []
        self.ws_connections = 0


class FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def next_round(self, body, transport):
        index = len(self.server.calls)
        self.server.calls.append(body)
        self.server.transports.append(transport)
        if index >= len(self.server.rounds):
            raise ValueError("unexpected additional fixture request")
        return self.server.rounds[index]

    def do_GET(self):
        if self.path != "/responses" or self.headers.get("Upgrade", "").lower() != "websocket":
            self.send_error(404)
            return
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept_key(self.headers["Sec-WebSocket-Key"]))
        self.end_headers()
        self.close_connection = True
        self.server.ws_connections += 1
        peer = FixtureWebSocket(self.rfile, self.wfile, masked=False)
        try:
            while True:
                raw = peer.receive()
                if raw is None:
                    return
                body = json.loads(raw)
                assert body["type"] == "response.create", "unexpected fixture WS request"
                events = self.next_round(body, "websocket")
                for event in events:
                    peer.send(wire(event))
        except (EOFError, BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if self.path != "/responses":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            events = self.next_round(body, "http")
        except ValueError:
            self.send_error(500, "unexpected additional fixture request")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            if self.server.control_lines:
                self.wfile.write(b": fixture heartbeat\n\nretry: 1000\n\nid: fixture\n\n")
            for event in events:
                if self.server.control_lines:
                    self.wfile.write(b"event: " + event["type"].encode() + b"\n")
                self.wfile.write(b"data: " + wire(event) + b"\n\n")
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@contextmanager
def isolated_cpa(executable, library, root, *, auto_models=False):
    upstream = FixtureUpstream()
    upstream.diagnostic_log = root / "cpa.stdout.log"
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    upstream_url = f"http://127.0.0.1:{upstream.server_port}"
    port = unused_port()
    base_url = f"http://127.0.0.1:{port}"
    auth = root / "auth"
    plugins = root / "plugins"
    auth.mkdir()
    platform_plugins = plugins / "windows" / "amd64"
    platform_plugins.mkdir(parents=True)
    shutil.copy2(library, platform_plugins / "codexreflow.dll")
    model_mappings = "\n".join(f"      - name: {MODEL}\n        alias: {alias}" for alias in MODEL_ALIASES)
    # Auto mode is tested with JUST the host enabled flag: no model_mode,
    # models, exclusions, continuation budget or marker supplied to the DLL.
    plugin_config = "      enabled: false\n"
    if not auto_models:
        plugin_config += f"      debug_log: true\n      models: [{MODEL}]\n      max_continue: 3\n"
    # Use supported legacy spellings so no user config or account directory is
    # inherited. The only upstream URL is the fixture listener above.
    config = f"""host: 127.0.0.1
port: {port}
auth-dir: {json.dumps(auth.as_posix())}
api-keys: [{FIXTURE_KEY}]
proxy-url: ""
request-retry: 0
debug: true
logging-to-file: false
request-log: false
disable-image-generation: true
remote-management:
  allow-remote: false
  secret-key: {FIXTURE_KEY}
  disable-control-panel: true
  disable-auto-update-panel: true
codex-api-key:
  - api-key: {FIXTURE_KEY}
    base-url: {upstream_url}
    websockets: true
    models:
{model_mappings}
plugins:
  enabled: true
  dir: {json.dumps(plugins.as_posix())}
  configs:
    codexreflow:
{plugin_config}
"""
    config_path = root / "config.yaml"
    config_path.write_text(config, encoding="utf-8")
    env = os.environ.copy()
    for key in list(env):
        if key.upper().endswith("_PROXY"):
            env.pop(key)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["HOME"] = env["USERPROFILE"] = str(root)
    process = None
    try:
        with (root / "cpa.stdout.log").open("wb") as log:
            process = subprocess.Popen(
                [str(executable), "--config", str(config_path)], cwd=root, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"isolated CPA exited with code {process.returncode}")
                try:
                    _, headers, _ = local_request(base_url + "/v0/management/plugins")
                    break
                except (OSError, urllib.error.URLError):
                    if time.monotonic() > deadline:
                        raise RuntimeError("isolated CPA startup timed out")
                    time.sleep(0.25)
            yield base_url, upstream, headers
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


def set_enabled(base_url, enabled):
    management = base_url + "/v0/management"
    local_request(management + "/plugins/codexreflow/enabled", {"enabled": enabled}, "PATCH")
    deadline = time.monotonic() + 15
    while True:
        _, _, raw = local_request(management + "/plugins")
        data = json.loads(raw)
        entries = data if isinstance(data, list) else data.get("plugins", [])
        plugin = next((item for item in entries if item.get("id") == "codexreflow"), None)
        if plugin and plugin.get("enabled") == enabled and plugin.get("effective_enabled") == enabled:
            return
        if time.monotonic() > deadline:
            raise RuntimeError("isolated plugin did not reach requested effective state")
        time.sleep(0.15)


def run_case(base_url, upstream, *, enabled, controls, continuation=False, tool=False, websocket=False,
             model=MODEL, intercepted=None, no_state=False, budget_limit=False):
    set_enabled(base_url, enabled)
    upstream.control_lines = controls
    upstream.calls = []
    upstream.transports = []
    upstream.rounds = [round_events(1, reasoning=0, tool=tool)]
    if continuation:
        upstream.rounds = [round_events(1, reasoning=516, tentative=True), round_events(2, reasoning=30)]
    if no_state:
        upstream.rounds = [round_events(1, reasoning=516)]
        upstream.rounds[0][-1]["response"]["output"][0].pop("encrypted_content")
    if budget_limit:
        upstream.rounds = [round_events(number, reasoning=516, tentative=number < 4) for number in range(1, 5)]
    body = {
        "model": model, "stream": True,
        "input": [{"role": "user", "content": "synthetic fixture only"}],
        "instructions": "synthetic fixture only",
        "reasoning": {"effort": "low"},
    }
    events = []
    if websocket:
        with LoopbackWebSocketClient(base_url.replace("http:", "ws:") + "/v1/responses", FIXTURE_KEY) as peer:
            peer.send(wire({**body, "type": "response.create"}))
            for _ in range(100):
                raw = peer.receive()
                if raw is None:
                    raise AssertionError("fixture WS closed before terminal")
                event = json.loads(raw)
                events.append(event)
                if event.get("type") in ("response.completed", "response.failed", "response.incomplete"):
                    break
        status = 200  # separate 101 handshake is asserted by the fixture client
        assert upstream.transports and set(upstream.transports) == {"websocket"}, "WS silently fell back to HTTP"
    else:
        status, _, data = local_request(base_url + "/v1/responses", body)
        for line in data.splitlines():
            if line.startswith(b"data:"):
                payload = line[5:].strip()
                if payload != b"[DONE]":
                    events.append(json.loads(payload))
        assert upstream.transports and set(upstream.transports) == {"http"}
    terminals = [event for event in events if event.get("type") in
                 ("response.completed", "response.failed", "response.incomplete")]
    assert status == 200 and len(terminals) == 1, "missing or duplicated terminal event"
    terminal = terminals[0]
    output = terminal.get("response", {}).get("output", [])
    completed = terminal["type"] == "response.completed"
    intercepted = enabled if intercepted is None else intercepted
    if completed:
        expected_type = "function_call" if tool else "message"
        assert output and output[-1]["type"] == expected_type, "final output was lost or changed"
        if tool:
            assert output[-1]["call_id"] == "call_fixture_1" and output[-1]["arguments"] == '{"q":"中文"}'
        else:
            assert output[-1]["content"][0]["text"] == "fixture answer 中文", "answer text was lost or changed"
    has_plugin_metadata = "proxy_rounds" in terminal.get("response", {}).get("metadata", {})
    if has_plugin_metadata:
        from diagnostic_assertions import assert_log_run
        assert_log_run(upstream.diagnostic_log, terminal)
    if completed:
        assert has_plugin_metadata == intercepted, "plugin selection did not match expectations"
        # Every public alias maps to the fixture's original native model.
        # Automatic matching must leave native alias resolution to CPA.
        assert all(call["model"] == MODEL for call in upstream.calls), "native model resolution was changed"
    if intercepted and completed:
        assert [event["sequence_number"] for event in events] == list(range(len(events)))
        assert len([event for event in events if event["type"] == "response.created"]) == 1
        assert terminal["response"]["id"] == "resp_1"
        assert len(terminal["response"]["metadata"]["proxy_rounds"]) == len(upstream.calls), "plugin was bypassed"
        if continuation:
            assert terminal["response"]["usage"]["output_tokens_details"]["reasoning_tokens"] == 546
            assert terminal["response"]["metadata"]["proxy_billed_usage"]["input_tokens"] == 2000
            assert all("discard me" not in json.dumps(event) for event in events)
        if no_state:
            assert len(upstream.calls) == 1, "516 without encrypted reasoning must not trigger extra calls"
        if budget_limit:
            assert len(upstream.calls) == 4, "default three-continuation limit was not enforced"
            assert all("discard me" not in json.dumps(event) for event in events)
    return {
        "enabled": enabled, "control_lines": controls, "continuation": continuation, "tool": tool,
        "downstream_transport": "websocket" if websocket else "http",
        "model": model, "intercepted": has_plugin_metadata,
        "no_encrypted_state": no_state, "default_budget_limit": budget_limit,
        "upstream_transports": list(upstream.transports),
        "terminal": terminal["type"],
        "reason": terminal.get("response", {}).get("incomplete_details", {}).get("reason"),
        "upstream_requests": len(upstream.calls), "events": len(events),
        "answer_preserved": completed and bool(output),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("library", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--keep-directory", type=Path)
    parser.add_argument("--reproduce", action="store_true", help="require the known old control-line failure")
    parser.add_argument("--auto-models", action="store_true", help="test zero-config automatic selection and legacy overrides")
    parser.add_argument("--cpa-version", choices=("8.0.13", "8.0.15", "8.0.16"), default="8.0.13")
    args = parser.parse_args()
    if args.reproduce and args.auto_models:
        raise ValueError("old framing reproduction and new auto-selection tests are separate baselines")
    if not args.executable.is_file() or not args.library.is_file():
        raise ValueError("executable and plugin must be existing local files")
    manager = tempfile.TemporaryDirectory(prefix="codexreflow-isolated-")
    root = Path(manager.name).resolve()
    # TemporaryDirectory performs a recursive cleanup. Check its absolute
    # target before using it; it must be our owned, uniquely named temp dir.
    if root.parent != Path(tempfile.gettempdir()).resolve() or not root.name.startswith("codexreflow-isolated-"):
        raise RuntimeError("unexpected isolated temporary directory")
    try:
        with isolated_cpa(args.executable.resolve(), args.library.resolve(), root, auto_models=args.auto_models) as (base_url, upstream, headers):
            if headers.get("X-Cpa-Version") != args.cpa_version:
                raise RuntimeError("isolated host does not match the explicitly selected CPA version")
            results = [run_case(base_url, upstream, enabled=False, controls=True)]
            results.append(run_case(base_url, upstream, enabled=True, controls=False))
            results.append(run_case(base_url, upstream, enabled=True, controls=True))
            assert results[0]["terminal"] == results[1]["terminal"] == "response.completed"
            if args.reproduce:
                assert results[2]["terminal"] == "response.incomplete" and results[2]["reason"] == "upstream_error"
            else:
                results.append(run_case(base_url, upstream, enabled=True, controls=True, continuation=True))
                results.append(run_case(base_url, upstream, enabled=True, controls=True, tool=True))
                results.append(run_case(base_url, upstream, enabled=True, controls=False, websocket=True))
                results.append(run_case(base_url, upstream, enabled=True, controls=False, websocket=True, continuation=True))
                results.append(run_case(base_url, upstream, enabled=True, controls=False, websocket=True, tool=True))
                assert all(item["terminal"] == "response.completed" and item["answer_preserved"] for item in results)
                assert results[3]["upstream_requests"] == 2
                if args.auto_models:
                    for model in ("gpt-6-astra", "gpt-7-fixture", "lab/gpt-6-sol(max)"):
                        results.append(run_case(base_url, upstream, enabled=True, controls=True, model=model))
                    for model in ("gpt-4o", "fixture-alias"):
                        results.append(run_case(base_url, upstream, enabled=True, controls=True, model=model, intercepted=False))
                    for ws in (False, True):
                        results.append(run_case(base_url, upstream, enabled=True, controls=True, websocket=ws, no_state=True))
                        results.append(run_case(base_url, upstream, enabled=True, controls=True, websocket=ws, budget_limit=True))

                    def patch_config(body):
                        local_request(base_url + "/v0/management/plugins/codexreflow/config", body, "PATCH")
                        # CPA reloads configuration asynchronously. This only
                        # waits in the owned fixture instance, never production.
                        time.sleep(0.5)

                    # Upgrade compatibility: models-only retains the exact old
                    # whitelist, while selecting auto overrides it explicitly.
                    patch_config({"models": [MODEL]})
                    results.append(run_case(base_url, upstream, enabled=True, controls=True))
                    results.append(run_case(base_url, upstream, enabled=True, controls=True, model="gpt-6-sol", intercepted=False))
                    patch_config({"model_mode": "auto"})
                    results.append(run_case(base_url, upstream, enabled=True, controls=True, model="gpt-6-sol"))
                    patch_config({"exclude_models": ["gpt-6-sol"]})
                    results.append(run_case(base_url, upstream, enabled=True, controls=True, model="gpt-6-sol", intercepted=False))
                    results.append(run_case(base_url, upstream, enabled=True, controls=True, model="lab/gpt-6-sol(max)", intercepted=False))
                    patch_config({"model_mode": "manual", "models": []})
                    results.append(run_case(base_url, upstream, enabled=True, controls=True, intercepted=False))
            report = {
                "test_kind": "real CPA process + loopback synthetic Codex upstream; no live provider or Desktop",
                "cpa_version": headers.get("X-Cpa-Version"),
                "plugin_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
                "production_config_modified": False, "billable_model_calls": 0, "cases": results,
                "initial_plugin_config": "enabled flag only" if args.auto_models else "legacy models whitelist",
            }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    finally:
        if args.keep_directory:
            shutil.copytree(root, args.keep_directory, dirs_exist_ok=False)
        manager.cleanup()


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("Assertions must be enabled; do not use Python -O.")
    main()
