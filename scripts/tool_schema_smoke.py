"""Real isolated CPA and strict synthetic collaboration schemas; no live models.

Old-build controls deliberately reject the known number-to-integer mutation.
The synthetic 400 is a test oracle, not a replay of a live OpenAI response.
Only the supplied binaries are read; no production config or account is used.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.error
import urllib.request

import isolated_cpa_smoke as harness
from fixture_websocket import FixtureWebSocket, LoopbackWebSocketClient, accept_key
from native_smoke import round_events, wire
import tool_schema_fixtures as fixtures
from ws_incremental_smoke import receive_terminal

KIND = "real isolated CPA + strict synthetic collaboration schemas; not live-model acceptance"
MODEL = "gpt-5.6-terra"
CODEX_HEADERS = {"User-Agent": "codex_cli_rs/0.159.2", "Originator": "codex_exec",
                 "OpenAI-Beta": "responses_websockets=2026-02-06",
                 "X-OpenAI-Internal-Codex-Responses-Lite": "true"}


class SchemaMismatch(Exception):
    pass


def rejection():
    return {"type": "error", "status": 400, "error": {"code": "invalid_function_parameters",
            "type": "invalid_request_error", "message": "Synthetic collaboration schema mismatch"}}


class SchemaHandler(harness.FixtureHandler):
    def next_round(self, body, transport):
        index = len(self.server.calls)
        events = super().next_round(body, transport)
        expected, required = self.server.schema_expectations[index]
        found = fixtures.declarations(body)
        if not set(required).issubset(found) or any(expected.get(k) != v for k, v in found.items()):
            self.server.schema_rejections += 1
            raise SchemaMismatch()
        return events

    def do_POST(self):
        if self.path != "/responses":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            events = self.next_round(body, "http")
        except SchemaMismatch:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(wire(rejection()))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            for event in events:
                self.wfile.write(b"data: " + wire(event) + b"\n\n")
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass

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
        latest, latest_calls = None, set()
        try:
            while True:
                raw = peer.receive()
                if raw is None:
                    return
                body = json.loads(raw)
                assert body["type"] == "response.create"
                if body.get("previous_response_id"):
                    assert body["previous_response_id"] == latest, "parent ID bridge lost"
                    for item in body.get("input", []):
                        if item.get("type") == "function_call_output":
                            assert item["call_id"] in latest_calls, "tool call identity lost"
                try:
                    events = self.next_round(body, "websocket")
                except SchemaMismatch:
                    peer.send(wire(rejection()))
                    return
                for event in events:
                    peer.send(wire(event))
                    if event["type"] == "response.completed":
                        latest = event["response"]["id"]
                        latest_calls = {i["call_id"] for i in event["response"].get("output", []) if i.get("type") == "function_call"}
        except (EOFError, BrokenPipeError, ConnectionResetError):
            pass


def http_terminal(base, body, headers):
    assert base.startswith("http://127.0.0.1:")
    request = urllib.request.Request(base + "/v1/responses", data=wire(body), headers={
        **headers, "Authorization": f"Bearer {harness.FIXTURE_KEY}", "Content-Type": "application/json"})
    try:
        with harness.OPENER.open(request, timeout=15) as response:
            raw, status = response.read(), response.status
    except urllib.error.HTTPError as error:
        raw, status = error.read(), error.code
    if status != 200:
        return {"type": "error", "http_status": status}, []
    events = [json.loads(line[5:].strip()) for line in raw.splitlines()
              if line.startswith(b"data:") and line[5:].strip() != b"[DONE]"]
    terminals = [e for e in events if e.get("type") in ("response.completed", "response.failed", "response.incomplete", "error")]
    assert len(terminals) == 1, "expected exactly one terminal"
    return terminals[0], events


def assert_completed(terminal, events, rounds, *, enabled=True, path=None):
    assert terminal["type"] == "response.completed", terminal
    assert len([e for e in events if e.get("type") == "response.completed"]) == 1
    if enabled:
        info = terminal["response"]["metadata"]["proxy_reflow"]
        assert info["rounds_completed"] == rounds and info["continuations_completed"] == rounds - 1
        if path:
            assert info["path"] == path
        seq = [e["sequence_number"] for e in events if "sequence_number" in e]
        assert seq == list(range(len(seq)))
    assert "discard me" not in wire(terminal).decode(), "tentative response leaked"


def collaboration_round(n):
    events = round_events(n, tool=True)
    arguments = '{"timeout_ms":1000,"poll_count":1}'
    # Added/done/output objects are distinct in some fixture events.
    for event in events:
        items = [event.get("item", {})] + event.get("response", {}).get("output", [])
        for item in items:
            if item.get("type") == "function_call":
                item.update(name="wait_agent", namespace="collaboration")
                if item.get("arguments"):
                    item["arguments"] = arguments
        if event["type"] == "response.function_call_arguments.delta":
            event["delta"] = arguments
    return events


def run_case(executable, library, cpa_version, transport, scenario, *, enabled=True, expect_defect=False):
    name = f"{transport}-{scenario}" + ("-disabled" if not enabled else "")
    with tempfile.TemporaryDirectory(prefix="codexreflow-schema-") as tmp:
        root = Path(tmp).resolve()
        assert root.parent == Path(tempfile.gettempdir()).resolve() and root.name.startswith("codexreflow-schema-")
        with harness.isolated_cpa(executable, library, root, auto_models=True) as (base, upstream, response_headers):
            assert response_headers.get("X-Cpa-Version") == cpa_version
            harness.set_enabled(base, enabled)
            upstream.schema_rejections = 0
            dynamic = scenario in ("dynamic-only", "root-and-dynamic", "incremental-dynamic")
            incremental = scenario.startswith("incremental-")
            body = fixtures.request(MODEL, dynamic=dynamic and not incremental,
                                    root=scenario not in ("no-tools", "dynamic-only"))
            if scenario == "integer":
                body["tools"][0] = fixtures.namespace("root", "integer")
            expected = fixtures.declarations(body)
            headers = {**CODEX_HEADERS, **({"User-Agent": "curl/8.7.1"} if scenario == "curl" else {})}
            continued = scenario not in ("initial", "integer") and enabled
            upstream.rounds = ([round_events(1, 516, tentative=True), round_events(2, 30)]
                               if continued else [round_events(1, 30)])
            upstream.schema_expectations = [(expected, list(expected))] * len(upstream.rounds)
            if incremental:
                # Root fold -> collaboration call -> native delta with a tool
                # return -> hidden 516 replay -> another call and return.
                upstream.rounds = [round_events(1, 516, tentative=True), collaboration_round(2),
                                   round_events(3, 516, tentative=True), collaboration_round(4), round_events(5, 30)]
                dynamic_items = fixtures.request(dynamic=True, root=False)["input"][:-1] if dynamic else []
                dynamic_expected = fixtures.declarations({"input": dynamic_items})
                combined = {**expected, **dynamic_expected}
                upstream.schema_expectations = [(expected, list(expected)), (expected, list(expected)),
                                                (combined, list(dynamic_expected)), (combined, list(combined)),
                                                (combined, [])]
            if transport == "http":
                terminal, events = http_terminal(base, body, headers)
            else:
                with LoopbackWebSocketClient(base.replace("http:", "ws:") + "/v1/responses", harness.FIXTURE_KEY, headers=headers) as peer:
                    peer.socket.settimeout(15)
                    peer.send(wire({"type": "response.create", **body}))
                    try:
                        terminal, events = receive_terminal(peer)
                    except (EOFError, AssertionError):
                        if not expect_defect or upstream.schema_rejections != 1:
                            raise
                        terminal, events = {"type": "socket_closed"}, []
                    if incremental and not expect_defect:
                        assert_completed(terminal, events, 2)
                        call = terminal["response"]["output"][-1]
                        assert call["name"] == "wait_agent" and call["namespace"] == "collaboration"
                        assert json.loads(call["arguments"])["timeout_ms"] == 1000
                        delta = deepcopy(dynamic_items) + [{"type": "function_call_output", "call_id": call["call_id"], "output": "synthetic tool returned"}]
                        peer.send(wire({"type": "response.create", "model": MODEL, "stream": True,
                                        "previous_response_id": terminal["response"]["id"], "input": delta}))
                        second, second_events = receive_terminal(peer)
                        assert_completed(second, second_events, 2, path="ws_incremental")
                        assert upstream.calls[2]["input"] == delta
                        replay = upstream.calls[3]
                        assert "previous_response_id" not in replay
                        assert sum(i.get("type") == "function_call_output" for i in replay["input"]) == 1
                        assert sum(i.get("type") == "additional_tools" for i in replay["input"]) == len(dynamic_items)
                        assert replay["instructions"] == body["instructions"]
                        assert replay["input"][-1]["phase"] == "commentary"
                        call = second["response"]["output"][-1]
                        assert call["name"] == "wait_agent" and call["namespace"] == "collaboration"
                        peer.send(wire({"type": "response.create", "model": MODEL, "stream": True,
                                        "previous_response_id": second["response"]["id"],
                                        "input": [{"type": "function_call_output", "call_id": call["call_id"], "output": "synthetic final tool returned"}]}))
                        terminal, events = receive_terminal(peer)
                        assert_completed(terminal, events, 1, path="ws_incremental")
                        assert upstream.calls[-1]["previous_response_id"] == "resp_4"
            if expect_defect:
                assert upstream.schema_rejections == 1 and len(upstream.calls) == 1
                assert terminal["type"] != "response.completed", "old defect unexpectedly disappeared"
            else:
                assert_completed(terminal, events, 1 if incremental else len(upstream.rounds), enabled=enabled)
                assert upstream.schema_rejections == 0 and len(upstream.calls) == len(upstream.rounds)
                for call in upstream.calls:
                    assert call["model"] == harness.MODEL, "host model mapping was overwritten"
                if continued and not incremental:
                    assert "previous_response_id" not in upstream.calls[1]
                    assert upstream.calls[1]["input"][-1]["phase"] == "commentary"
            assert set(upstream.transports) == {"http" if transport == "http" else "websocket"}
            if transport == "ws":
                assert upstream.ws_connections == 1, "unexpected socket reconnect or fallback"
            result = {"scenario": name, "passed": True, "upstream_requests": len(upstream.calls),
                      "schema_rejections": upstream.schema_rejections, "terminal": terminal["type"],
                      "expected_old_defect": expect_defect}
            print(json.dumps(result), flush=True)
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpa", type=Path, required=True)
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--cpa-version", choices=("8.0.47",), required=True)
    parser.add_argument("--expect-defect", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    assert args.cpa.is_file() and args.dll.is_file()
    if args.report.exists():
        raise FileExistsError("validation reports are immutable")
    previous_handler = harness.FixtureHandler
    harness.FixtureHandler = SchemaHandler
    harness.MODEL_ALIASES.append(MODEL)
    cases = []
    try:
        for transport in ("http", "ws"):
            scenarios = ("initial", "dynamic-only") if args.expect_defect else (
                "initial", "continuation", "dynamic-only", "root-and-dynamic", "integer", "curl", "no-tools")
            for scenario in scenarios:
                cases.append(run_case(args.cpa.resolve(), args.dll.resolve(), args.cpa_version, transport, scenario,
                                      expect_defect=args.expect_defect))
            cases.append(run_case(args.cpa.resolve(), args.dll.resolve(), args.cpa_version, transport, "initial", enabled=False))
        if not args.expect_defect:
            for scenario in ("incremental-cached", "incremental-dynamic"):
                cases.append(run_case(args.cpa.resolve(), args.dll.resolve(), args.cpa_version, "ws", scenario))
    finally:
        harness.FixtureHandler = previous_handler
        harness.MODEL_ALIASES.remove(MODEL)
    report = {"test_kind": KIND, "cpa_version": args.cpa_version,
              "plugin_sha256": hashlib.sha256(args.dll.read_bytes()).hexdigest(),
              "cpa_sha256": hashlib.sha256(args.cpa.read_bytes()).hexdigest(),
              "production_config_modified": False, "billable_model_calls": 0,
              "expected_old_defect": args.expect_defect, "cases": cases}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as out:
        out.write(json.dumps(report, indent=2) + "\n")
    print(f"Completed {len(cases)} isolated schema scenarios; no live model requests.")


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("Assertions must remain enabled; do not use Python -O.")
    main()
