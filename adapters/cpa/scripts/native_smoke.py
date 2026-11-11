"""Exercise the compiled C ABI with a fully offline fake CPA host.

No ECPA process, credential, network connection, or model call is used. Raw JSON
host reads model the WS callback contract; they are not a live WebSocket test.
"""

import argparse
import base64
import ctypes as c
import hashlib
import json
from pathlib import Path
import threading

from diagnostic_assertions import assert_run
from summarize_diagnostics import parse_line, summarize
import tool_schema_fixtures as schema_fixture


class Buffer(c.Structure):
    _fields_ = [("ptr", c.c_void_p), ("length", c.c_size_t)]


HostCall = c.CFUNCTYPE(c.c_int, c.c_void_p, c.c_char_p, c.c_void_p, c.c_size_t, c.POINTER(Buffer))
HostFree = c.CFUNCTYPE(None, c.c_void_p, c.c_size_t)
PluginCall = c.CFUNCTYPE(c.c_int, c.c_char_p, c.c_void_p, c.c_size_t, c.POINTER(Buffer))
PluginFree = c.CFUNCTYPE(None, c.c_void_p, c.c_size_t)
Shutdown = c.CFUNCTYPE(None)


class HostAPI(c.Structure):
    _fields_ = [("abi_version", c.c_uint32), ("ctx", c.c_void_p), ("call", HostCall), ("free", HostFree)]


class PluginAPI(c.Structure):
    _fields_ = [("abi_version", c.c_uint32), ("call", PluginCall), ("free", PluginFree), ("shutdown", Shutdown)]


def encoded(raw):
    return base64.b64encode(raw).decode("ascii")


def wire(event):
    return json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()


def round_events(number, reasoning=40, tool=False, tentative=False):
    response = {"id": f"resp_{number}", "model": "fixture-model", "status": "in_progress"}
    rs = {"id": f"rs_{number}", "type": "reasoning", "encrypted_content": f"opaque_fixture_{number}"}
    item = (
        {"id": "fc_1", "type": "function_call", "call_id": "call_fixture_1", "name": "lookup", "arguments": '{"q":"中文"}'}
        if tool else
        {"id": "msg_tentative" if tentative else "msg_final", "type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "discard me" if tentative else "fixture answer 中文"}]}
    )
    events = [
        {"type": "response.created", "response": response},
        {"type": "response.in_progress", "response": response},
        {"type": "response.output_item.added", "output_index": 0, "item": {"type": "reasoning", "id": rs["id"]}},
        {"type": "response.reasoning_summary_text.delta", "output_index": 0, "delta": "fixture reasoning"},
        {"type": "response.output_item.done", "output_index": 0, "item": rs},
        {"type": "response.output_item.added", "output_index": 1, "item": {**item, "content": [], "arguments": ""}},
        {"type": "response.function_call_arguments.delta" if tool else "response.output_text.delta", "output_index": 1,
         "delta": item["arguments"] if tool else item["content"][0]["text"]},
        {"type": "response.output_item.done", "output_index": 1, "item": item},
        {"type": "response.completed", "response": {**response, "status": "completed", "output": [rs, item],
         "usage": {"input_tokens": 1000, "output_tokens": reasoning + 10, "total_tokens": 1010 + reasoning,
                   "input_tokens_details": {"cached_tokens": 800}, "output_tokens_details": {"reasoning_tokens": reasoning}}}},
    ]
    return events


class OfflineHost:
    def __init__(self, library):
        self.lock = threading.RLock()
        self.allocations = {}
        self.errors = []
        self.logs = []
        self.callback = HostCall(self.on_call)
        self.free_callback = HostFree(self.on_free)
        self.host = HostAPI(1, None, self.callback, self.free_callback)
        self.plugin = PluginAPI()
        self.library = c.CDLL(str(library.resolve()))
        self.library.cliproxy_plugin_init.argtypes = [c.POINTER(HostAPI), c.POINTER(PluginAPI)]
        self.library.cliproxy_plugin_init.restype = c.c_int
        if self.library.cliproxy_plugin_init(c.byref(self.host), c.byref(self.plugin)) != 0:
            raise RuntimeError("plugin init failed")
        assert self.plugin.abi_version == 1

    def call(self, method, payload):
        raw = wire(payload)
        request = c.create_string_buffer(raw)
        response = Buffer()
        code = self.plugin.call(method.encode(), c.cast(request, c.c_void_p), len(raw), c.byref(response))
        try:
            result = json.loads(c.string_at(response.ptr, response.length))
        finally:
            if response.ptr:
                self.plugin.free(response.ptr, response.length)
        if code or not result.get("ok"):
            raise RuntimeError(f"{method} failed: {result}")
        return result["result"]

    def on_free(self, pointer, length):
        with self.lock:
            self.allocations.pop(pointer, None)

    def on_call(self, ctx, method, pointer, length, response):
        try:
            request = json.loads(c.string_at(pointer, length))
            with self.lock:
                result = self.dispatch(method.decode(), request)
            raw = wire({"ok": True, "result": result})
        except Exception as error:
            with self.lock:
                self.errors.append(str(error))
            raw = wire({"ok": False, "error": {"code": "offline_mock_error", "message": "offline host rejected callback"}})
        allocation = c.create_string_buffer(raw)
        address = c.addressof(allocation)
        with self.lock:
            self.allocations[address] = allocation
        response[0].ptr, response[0].length = address, len(raw)
        return 0

    def dispatch(self, method, request):
        if method == "host.log":
            self.logs.append(request)
            return {}
        if method == "host.model.execute_stream":
            body = json.loads(base64.b64decode(request["body"]))
            assert request["host_callback_id"] == "fixture-callback"
            assert request["exit_protocol"] == "codex"
            assert body["stream"] is True and "previous_response_id" not in body
            self.bodies.append(body)
            index = len(self.bodies) - 1
            assert index < len(self.rounds), "unexpected extra model round"
            sid = f"upstream_{index}"
            chunks = []
            for event in self.rounds[index]:
                raw = wire(event)
                if self.transport == "cpa-lines":
                    chunks.extend([b"event: " + event["type"].encode(), b"data: " + raw, b""])
                else:
                    chunks.append(b"data: " + raw + b"\n\n" if self.transport == "sse" else raw)
            if self.fragmented:
                joined = b"".join(chunks)
                chunks = [joined[i:i+7] for i in range(0, len(joined), 7)]
            self.streams[sid] = iter(chunks)
            return {"status_code": 200, "stream_id": sid, "headers": {}}
        if method == "host.model.stream_read":
            raw = next(self.streams[request["stream_id"]], None)
            if raw is None:
                return {"done": True, "error": "fixture cancelled" if self.cancelled else ""}
            return {"payload": encoded(raw), "done": False}
        if method == "host.model.stream_close":
            self.streams.pop(request["stream_id"], None)
            return {}
        if method == "host.stream.emit":
            self.emitted.append(base64.b64decode(request["payload"]))
            return {}
        if method == "host.stream.close":
            assert not request.get("error"), request
            self.closed.set()
            return {}
        raise RuntimeError(f"unexpected callback: {method}")

    def run_case(self, transport, rounds, fragmented=False, cancelled=False, *, model="fixture-model", config=None, input_items=None,
                 request_fields=None, original_request=None):
        config = b"models: [fixture-model]\nmax_continue: 3\n" if config is None else config
        self.call("plugin.reconfigure", {"config_yaml": encoded(config)})
        items = [{"role": "user", "content": "offline fixture"}] if input_items is None else input_items
        body = wire({"model": model, "stream": True, "input": items, **(request_fields or {})})
        route = self.call("model.route", {
            "RequestedModel": model, "SourceFormat": "openai-response", "Stream": True, "Body": encoded(body),
        })
        assert route.get("Handled", route.get("handled")), "fixture was not selected by the model router"
        with self.lock:
            self.transport, self.rounds, self.fragmented, self.cancelled = transport, rounds, fragmented, cancelled
            self.bodies, self.emitted, self.streams, self.errors, self.logs = [], [], {}, [], []
            self.closed = threading.Event()
        self.call("executor.execute_stream", {
            "model": model, "stream_id": "downstream_fixture", "host_callback_id": "fixture-callback",
            "payload": encoded(body),
            **({"OriginalRequest": encoded(wire(original_request))} if original_request is not None else {}),
        })
        assert self.closed.wait(10), "plugin did not close its downstream stream"
        assert not self.errors, self.errors
        events = []
        for chunk in self.emitted:
            for line in chunk.splitlines():
                if line.startswith(b"data:"):
                    raw = line[5:].strip()
                    if raw != b"[DONE]":
                        events.append(json.loads(raw))
        sequences = [event["sequence_number"] for event in events]
        assert sequences == list(range(len(events))), sequences
        terminals = [event for event in events if event["type"] in ("response.completed", "response.failed", "response.incomplete")]
        assert len(terminals) == 1, "must emit exactly one terminal response"
        assert len([event for event in events if event["type"] == "response.created"]) == 1
        return events, terminals[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    host = OfflineHost(args.library)
    registration = host.call("plugin.register", {})
    assert all(registration["metadata"].get(key, "").strip() for key in
               ("Name", "Version", "Author", "GitHubRepository")), "CPA rejects empty registration metadata"
    assert registration["metadata"]["Name"] == "codexreflow"
    assert registration["capabilities"]["executor_output_formats"] == ["codex", "openai-response"]
    assert registration["capabilities"]["request_interceptor"] is True
    results = []
    # Prewarms must stay on CPA's native route; folding them changes request state.
    host.call("plugin.reconfigure", {"config_yaml": encoded(b"")})
    for items in ([], [{"role": "user", "content": "offline warmup fixture"}]):
        body = wire({"model": "gpt-6-sol", "stream": True, "generate": False, "input": items})
        route = host.call("model.route", {
            "RequestedModel": "gpt-6-sol", "SourceFormat": "openai-response", "Stream": True, "Body": encoded(body),
        })
        assert not route.get("Handled", route.get("handled", False)), "prewarm was selected for reasoning continuation"
        scenario = "prewarm-native-route-with-input" if items else "prewarm-native-route-empty-input"
        results.append({"scenario": scenario, "input_count": len(items), "passed": True})
    # Exercise the actual compiled executor, not just the JSON helper: copying
    # an empty slice previously changed the upstream wire input from [] to null.
    _, terminal = host.run_case("json", [round_events(1)], input_items=[])
    assert host.bodies[0]["input"] == [], "empty executor input changed to null"
    assert terminal["type"] == "response.completed"
    results.append({"scenario": "empty-input-preserved-on-wire", "passed": True})
    # Exercise the SDK's OriginalRequest field through the real C ABI, not
    # only the Go helper. Keep host routing edits and ordinary tool schemas.
    for transport in ("sse", "json", "cpa-lines"):
        for scenario in ("schema-initial", "schema-continuation", "schema-additional", "schema-missing-original"):
            original = schema_fixture.request(dynamic=scenario == "schema-additional")
            payload = schema_fixture.normalized_request(original)
            payload["instructions"] = "host transformed instructions"
            payload["prompt_cache_key"] = "synthetic-host-cache-key"
            supplied = None if scenario == "schema-missing-original" else original
            expected = schema_fixture.declarations(original if supplied is not None else payload)
            rounds = ([round_events(1, 516, tentative=True), round_events(2, 30)]
                      if scenario in ("schema-continuation", "schema-additional") else [round_events(1)])
            _, terminal = host.run_case(transport, rounds, request_fields=payload, original_request=supplied)
            assert terminal["type"] == "response.completed" and len(host.bodies) == len(rounds)
            for upstream_body in host.bodies:
                assert schema_fixture.declarations(upstream_body) == expected, scenario
                assert upstream_body["instructions"] == payload["instructions"]
                assert upstream_body["prompt_cache_key"] == payload["prompt_cache_key"]
                assert upstream_body["tools"][1] == payload["tools"][1], "ordinary host schema rewrite was undone"
            results.append({"transport_payload": transport, "scenario": scenario, "passed": True})
            print(f"PASS {transport:4s} / {scenario}")
    for transport in ("sse", "json", "cpa-lines"):
        scenarios = ("normal", "continuation", "tool", "cancelled", "eof", "failed", "upstream-incomplete")
        if transport != "cpa-lines":
            scenarios += ("fragmented",)
        for scenario in scenarios:
            rounds = [round_events(1, tool=scenario == "tool")]
            if scenario == "continuation":
                rounds = [round_events(1, 516, tentative=True), round_events(2, 30)]
            if scenario in ("cancelled", "eof"):
                rounds = [rounds[0][:4]]
            if scenario in ("failed", "upstream-incomplete"):
                rounds[0][-1]["type"] = "response.failed" if scenario == "failed" else "response.incomplete"
                rounds[0][-1]["response"]["status"] = "failed" if scenario == "failed" else "incomplete"
            events, terminal = host.run_case(transport, rounds, fragmented=scenario == "fragmented", cancelled=scenario == "cancelled")
            response = terminal["response"]
            expected_type = {"cancelled": "response.incomplete", "eof": "response.incomplete", "failed": "response.failed", "upstream-incomplete": "response.incomplete"}.get(scenario, "response.completed")
            assert terminal["type"] == expected_type
            if scenario not in ("cancelled", "eof"):
                assert len(response["metadata"]["proxy_rounds"]) == len(rounds)
                assert response["output"][-1]["type"] == ("function_call" if scenario == "tool" else "message")
            if scenario == "tool":
                assert response["output"][-1]["call_id"] == "call_fixture_1"
                assert response["output"][-1]["arguments"] == '{"q":"中文"}'
            if scenario == "continuation":
                assert response["id"] == "resp_1", "continuation must retain downstream identity"
                assert response["usage"]["output_tokens_details"]["reasoning_tokens"] == 546
                assert response["metadata"]["proxy_billed_usage"]["input_tokens"] == 2000
                assert all("discard me" not in json.dumps(event) for event in events)
                replay = host.bodies[1]["input"]
                assert replay[-2]["encrypted_content"] == "opaque_fixture_1"
                assert replay[-1]["phase"] == "commentary"
            info = response["metadata"]["proxy_reflow"]
            finish_logs = [json.loads(log["message"].split("[codexreflow] ", 1)[1]) for log in host.logs if '"event":"fold_finished"' in log.get("message", "")]
            assert len(finish_logs) == 1, "missing or duplicated per-fold evidence"
            finish = finish_logs[0]
            for field, value in info.items():
                assert finish[field] == value, f"terminal/log mismatch: {field}"
            assert finish["result"] == expected_type and finish["emission"] == "host_accepted"
            expected_stop = {"cancelled": "upstream_error", "eof": "upstream_eof", "failed": "upstream_failed", "upstream-incomplete": "upstream_incomplete"}.get(scenario, "normal")
            assert info["stop_reason"] == expected_stop
            assert info["rounds_started"] == len(rounds)
            assert info["rounds_completed"] == (0 if scenario in ("cancelled", "eof") else len(rounds))
            assert info["continuations_completed"] == max(0, info["rounds_completed"] - 1)
            assert "opaque_fixture" not in wire(finish).decode() and "fixture answer" not in wire(finish).decode()
            diagnostic_events = [event for log in host.logs if (event := parse_line(log.get("message", ""))) is not None]
            diagnostic = assert_run(diagnostic_events, info)
            assert diagnostic["reasoning_tokens_by_round"] == [r["reasoning_tokens"] for r in (response["metadata"].get("proxy_rounds") or [])]
            assert all(token not in wire(diagnostic).decode() for token in ("opaque_fixture", "fixture answer", "discard me"))
            results.append({"transport_payload": transport, "scenario": scenario, "events": len(events), "passed": True})
            print(f"PASS {transport:4s} / {scenario}")
    for transport in ("sse", "json", "cpa-lines"):
        for scenario in ("auto-normal", "auto-516"):
            rounds = [round_events(1)]
            if scenario == "auto-516":
                rounds = [round_events(1, 516, tentative=True), round_events(2, 30)]
            events, terminal = host.run_case(transport, rounds, model="gpt-6-astra", config=b"")
            response = terminal["response"]
            assert terminal["type"] == "response.completed"
            assert len(host.bodies) == len(rounds) == len(response["metadata"]["proxy_rounds"])
            assert response["output"][-1]["content"][0]["text"] == "fixture answer 中文"
            if scenario == "auto-516":
                assert response["usage"]["output_tokens_details"]["reasoning_tokens"] == 546
                assert all("discard me" not in json.dumps(event) for event in events)
            results.append({"transport_payload": transport, "scenario": scenario, "events": len(events), "passed": True})
            print(f"PASS {transport:4s} / {scenario}")
    # Error paths with no upstream terminal must not invent token counts or
    # a successful client delivery. Fixture identifiers deliberately repeat.
    with host.lock:
        host.logs, host.errors = [], []
    original_dispatch = host.dispatch
    def reject_start(method, request):
        if method == "host.model.execute_stream":
            raise RuntimeError("private synthetic startup failure")
        return original_dispatch(method, request)
    host.dispatch = reject_start
    try:
        try:
            host.call("executor.execute_stream", {"Model": "gpt-6-astra", "stream_id": "fixture-failed-start",
                      "host_callback_id": "fixture-callback", "Payload": encoded(wire({"model": "gpt-6-astra", "input": []}))})
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected startup failure")
    finally:
        host.dispatch = original_dispatch
    diagnostic = summarize([e for log in host.logs if (e := parse_line(log["message"])) is not None])["runs"]
    assert len(diagnostic) == 1 and diagnostic[0]["evidence_complete"]
    assert diagnostic[0]["finish"]["result"] == "startup_error" and diagnostic[0]["rounds"] == []
    assert "private synthetic" not in wire(diagnostic).decode()
    results.append({"scenario": "diagnostic_startup_failure", "passed": True})
    host.logs = []
    for outcome in ("failed", "canceled"):
        body = wire({"model": "gpt-6-astra", "input": [], "previous_response_id": "fixture-parent"})
        host.call("response.intercept_stream_chunk", {"RequestID": "same-fixture-lifecycle", "SourceFormat": "openai-response",
                  "Model": "gpt-6-astra", "RequestBody": encoded(body), "OriginalRequest": encoded(body),
                  "ChunkIndex": -1, "Metadata": {"execution_session_id": "same-fixture-socket"}})
        host.call("request.complete", {"RequestID": "same-fixture-lifecycle", "Outcome": outcome,
                  "Error": "private synthetic auth / response / request error"})
    diagnostic = summarize([e for log in host.logs if (e := parse_line(log["message"])) is not None])["runs"]
    assert len(diagnostic) == 2 and len({r["run_id"] for r in diagnostic}) == 2
    assert all(r["evidence_complete"] and r["rounds"] == [] and r["finish"]["emission"] == "not_confirmed" for r in diagnostic)
    assert {r["finish"]["result"] for r in diagnostic} == {"host_lifecycle_failed", "host_lifecycle_canceled"}
    assert all(value not in wire(diagnostic).decode() for value in ("private synthetic", "same-fixture", "fixture-parent"))
    results.append({"scenario": "diagnostic_native_lifecycle_failure_and_reused_identifier", "passed": True})
    host.plugin.shutdown()
    report = {"test_kind": "offline C ABI mock host; not live CPA/WebSocket", "plugin_version": registration["metadata"]["Version"],
              "plugin_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(), "cases": results}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"All {len(results)} offline C ABI scenarios passed; no model calls.")


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("Run this test without Python -O / PYTHONOPTIMIZE; assertions are required.")
    main()
