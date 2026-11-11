"""Real isolated CPA + strict synthetic WS cache, never a live model call.

Explicit --cpa and --dll inputs are read-only. All settings, auth, logs and
listeners belong to verified temporary directories. --expect-defect records
the old DLL's failure rather than presenting it as successful compatibility.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time

import isolated_cpa_smoke as harness
from fixture_websocket import FixtureWebSocket, LoopbackWebSocketClient, accept_key
from native_smoke import round_events, wire


def strict_ws(self):
    if self.path != "/responses" or self.headers.get("Upgrade", "").lower() != "websocket":
        self.send_error(404)
        return
    self.send_response(101)
    self.send_header("Upgrade", "websocket")
    self.send_header("Connection", "Upgrade")
    self.send_header("Sec-WebSocket-Accept", accept_key(self.headers["Sec-WebSocket-Key"]))
    self.end_headers()
    self.close_connection = True
    stats_lock = getattr(self.server, "fixture_lock", None)
    with stats_lock or nullcontext():
        self.server.ws_connections += 1
    peer = FixtureWebSocket(self.rfile, self.wfile, masked=False)
    latest = None
    latest_output = []
    local_round = 0
    scenario = None
    try:
        while True:
            raw = peer.receive()
            if raw is None:
                return
            body = json.loads(raw)
            parent = body.get("previous_response_id")
            with stats_lock or nullcontext():
                self.server.parent_observations.append({"parent": parent, "latest": latest})
            if parent and parent != latest:
                with stats_lock or nullcontext():
                    self.server.parent_rejections += 1
                peer.send(wire({"type": "error", "status": 400, "error": {
                    "code": "previous_response_not_found", "type": "invalid_request_error",
                    "param": "previous_response_id", "message": "Synthetic missing previous response",
                }}))
                continue
            if parent:
                calls = {item["call_id"] for item in latest_output if item.get("type") == "function_call"}
                for item in body.get("input", []):
                    if item.get("type") == "function_call_output":
                        assert item["call_id"] in calls, "tool delta lost its native parent call"
            scenarios = getattr(self.server, "socket_scenarios", None)
            if scenarios is None:
                events = self.next_round(body, "websocket")
            else:
                # Each connection deliberately reuses resp_1, but finishes its
                # hidden fold at a different parent. Shared/global ID caches
                # cannot pass this concurrent socket-isolation regression.
                if scenario is None:
                    scenario = body["input"][0]["content"]
                    assert scenario in scenarios
                local_round += 1
                with self.server.fixture_lock:
                    self.server.calls.append(body)
                    self.server.transports.append("websocket")
                    self.server.socket_observations.append({"scenario": scenario, "round": local_round, "parent": parent})
                native_count = getattr(self.server, "socket_native_counts", {}).get(scenario, 0)
                first_count = scenarios[scenario] + 1
                truncated = (local_round < first_count or
                             first_count + 1 <= local_round <= first_count + native_count)
                if native_count and local_round > first_count + 1 and not parent:
                    assert body["input"][0]["content"] == scenario, "replay transcript crossed sockets"
                events = round_events(local_round, reasoning=516 if truncated else 40, tentative=truncated)
            for event in events:
                peer.send(wire(event))
                if event["type"] == "response.completed":
                    latest = event["response"]["id"]
                    latest_output = event["response"].get("output", [])
    except (EOFError, BrokenPipeError, ConnectionResetError):
        pass


def receive_terminal(peer):
    events = []
    for _ in range(150):
        raw = peer.receive()
        if raw is None:
            raise AssertionError("fixture WS closed before terminal")
        event = json.loads(raw)
        events.append(event)
        if event.get("type") in ("response.completed", "response.failed", "response.incomplete", "error"):
            return event, events
    raise AssertionError("no fixture terminal")


def assert_fold_evidence(terminal, events, rounds, expect_defect):
    assert terminal["type"] == "response.completed"
    assert len([e for e in events if e.get("type") == "response.completed"]) == 1
    ids = [e["response"]["id"] for e in events if isinstance(e.get("response"), dict)]
    assert len(set(ids)) == 1, "response identity changed mid-stream"
    sequence = [e["sequence_number"] for e in events if "sequence_number" in e]
    assert sequence == list(range(len(sequence))), "fold sequence changed"
    if not expect_defect:
        info = terminal["response"]["metadata"]["proxy_reflow"]
        assert info["handled"] is True and info["rounds_completed"] == rounds
        assert info["continuations_completed"] == rounds - 1
        expected_bridge = "response_alias" if rounds > 1 else "not_needed"
        assert info["ws_context_bridge"] == expected_bridge, f"bridge={info['ws_context_bridge']}, expected={expected_bridge}"
        assert len(info["run_id"]) == 24


def run_case(executable, library, *, name, enabled, continue_rounds, tool=False,
             full_replay=False, reconnect=False, expect_defect=False, model=harness.MODEL,
             native_516=False, reconfigure=False, native_folds=False, cpa_version="8.0.13"):
    with tempfile.TemporaryDirectory(prefix="codexreflow-ws-regression-") as temp:
        root = Path(temp).resolve()
        assert root.parent == Path(tempfile.gettempdir()).resolve()
        assert root.name.startswith("codexreflow-ws-regression-")
        with harness.isolated_cpa(executable, library, root, auto_models=True) as (base, upstream, headers):
            assert headers.get("X-Cpa-Version") == cpa_version, "explicit CPA version required"
            harness.set_enabled(base, enabled)
            upstream.parent_observations = []
            upstream.parent_rejections = 0
            rounds = continue_rounds + 1 if enabled else 1
            upstream.rounds = [round_events(n, reasoning=516, tentative=True) for n in range(1, rounds)]
            upstream.rounds += [round_events(rounds, reasoning=516 if not enabled and continue_rounds else 40, tool=tool)]
            upstream.rounds += [round_events(rounds + 1, reasoning=516 if native_516 or reconfigure else 40), round_events(rounds + 2)]
            if native_516 and native_folds:
                upstream.rounds += [round_events(rounds + 3)]
            body = {"type": "response.create", "model": model, "stream": True, "store": False,
                    "instructions": "synthetic fixture only", "input": [{"role": "user", "content": "fixture first"}],
                    "reasoning": {"effort": "low"}}
            url = base.replace("http:", "ws:") + "/v1/responses"
            with LoopbackWebSocketClient(url, harness.FIXTURE_KEY) as peer:
                peer.send(wire(body))
                first, events = receive_terminal(peer)
                assert first["type"] == "response.completed"
                if enabled:
                    assert_fold_evidence(first, events, rounds, expect_defect)
                assert len(upstream.calls) == rounds
                first_id = first["response"]["id"]
                if reconfigure:
                    harness.local_request(base + "/v0/management/plugins/codexreflow/config", {"max_continue": 0}, "PATCH")
                    time.sleep(0.5)  # Reload is verified by the new full turn below.
                delta = ([{"type": "function_call_output", "call_id": "call_fixture_1", "output": "fixture tool result 中文"}]
                         if tool else [{"role": "user", "content": "fixture followup"}])
                followup = {**body, "previous_response_id": first_id, "input": delta}
                if full_replay:
                    followup.pop("previous_response_id")
                    followup["input"] = body["input"] + first["response"]["output"] + delta
                if reconfigure:
                    peer.send(wire(followup))
                    assert peer.receive() is None, "pinned CPA reload did not close the old execution session"
                    assert "reason=executor_shutdown" in (root / "cpa.stdout.log").read_text(encoding="utf-8", errors="replace")
                    # Configuration reload shuts down the native executor in
                    # this pinned host. Recovery must use a fresh socket and
                    # full input, not pretend that its old cache survived.
                    with LoopbackWebSocketClient(url, harness.FIXTURE_KEY) as fresh:
                        replay = {**body, "input": body["input"] + first["response"]["output"] + delta}
                        before = len(upstream.calls)
                        fresh.send(wire(replay))
                        second, _ = receive_terminal(fresh)
                        assert second["type"] == "response.completed" and len(upstream.calls) == before + 1
                        if enabled:
                            assert second["response"]["metadata"]["proxy_stopped_reason"] == "max_continue"
                            if not expect_defect:
                                info = second["response"]["metadata"]["proxy_reflow"]
                                assert info["continuations_started"] == 0 and info["stop_reason"] == "max_continue"
                elif reconnect:
                    with LoopbackWebSocketClient(url, harness.FIXTURE_KEY) as fresh:
                        fresh.send(wire(followup))
                        rejected, _ = receive_terminal(fresh)
                        assert rejected["type"] == "error", "bridge must not cross sockets"
                    # A new socket recovers by replaying full input, never by
                    # dropping the parent and silently forwarding the delta.
                    with LoopbackWebSocketClient(url, harness.FIXTURE_KEY) as fresh:
                        replay = {**body, "input": body["input"] + first["response"]["output"] + delta}
                        fresh.send(wire(replay))
                        second, _ = receive_terminal(fresh)
                        assert second["type"] == "response.completed"
                else:
                    peer.send(wire(followup))
                    second, _ = receive_terminal(peer)
                    defect_expected = expect_defect and enabled and continue_rounds and not full_replay
                    if defect_expected:
                        assert second["type"] == "error" and upstream.parent_rejections == 1
                        assert second["error"]["code"] == "previous_response_not_found", second
                    else:
                        assert second["type"] == "response.completed", second
                        assert upstream.parent_rejections == 0
                        if not full_replay:
                            initial_native = upstream.calls[rounds]
                            assert initial_native.get("previous_response_id") == f"resp_{rounds}"
                            assert initial_native["input"] == delta, "bridge replayed or altered the initial native delta"
                        if native_516:
                            if native_folds:
                                info = second["response"]["metadata"]["proxy_reflow"]
                                assert info["path"] == "ws_incremental" and info["continuations_completed"] == 1
                            else:
                                assert "proxy_reflow" not in second["response"].get("metadata", {}), "native incremental turn was folded"
                        peer.send(wire({**body, "previous_response_id": second["response"]["id"],
                                        "input": [{"role": "user", "content": "fixture third turn"}]}))
                        third, _ = receive_terminal(peer)
                        assert third["type"] == "response.completed", third
                        expected_parent = f"resp_{rounds + 2}" if native_516 and native_folds else second["response"]["id"]
                        assert upstream.calls[-1]["previous_response_id"] == expected_parent
                assert set(upstream.transports) == {"websocket"}, "unexpected HTTP fallback"
                if enabled and continue_rounds:
                    assert "discard me" not in wire(first).decode()
                    # No fake response ID retagging: the fold still identifies
                    # the same client response; only the next native parent is mapped.
                    assert first_id == "resp_1"
                result = {"case": name, "passed": True, "first_rounds": rounds, "next_terminal": second["type"],
                          "parent_rejections": upstream.parent_rejections,
                          "transports": upstream.transports, "upstream_connections": upstream.ws_connections}
                print(json.dumps(result, ensure_ascii=False), flush=True)
                return result


def run_concurrent_case(executable, library, *, expect_defect, cpa_version="8.0.13"):
    with tempfile.TemporaryDirectory(prefix="codexreflow-ws-regression-") as temp:
        root = Path(temp).resolve()
        assert root.parent == Path(tempfile.gettempdir()).resolve() and root.name.startswith("codexreflow-ws-regression-")
        with harness.isolated_cpa(executable, library, root, auto_models=True) as (base, upstream, headers):
            assert headers.get("X-Cpa-Version") == cpa_version
            harness.set_enabled(base, True)
            upstream.parent_observations, upstream.parent_rejections = [], 0
            upstream.socket_scenarios = {"fixture-socket-A": 1, "fixture-socket-B": 2}
            upstream.fixture_lock = threading.Lock()
            upstream.socket_observations = []
            barrier = threading.Barrier(2)
            url = base.replace("http:", "ws:") + "/v1/responses"

            def exercise(scenario, continuation_rounds):
                body = {"type": "response.create", "model": harness.MODEL, "store": False, "stream": True,
                        "instructions": "synthetic fixture only", "reasoning": {"effort": "low"},
                        "input": [{"role": "user", "content": scenario}]}
                with LoopbackWebSocketClient(url, harness.FIXTURE_KEY) as peer:
                    peer.send(wire(body))
                    first, events = receive_terminal(peer)
                    assert_fold_evidence(first, events, continuation_rounds + 1, expect_defect)
                    assert first["response"]["id"] == "resp_1"
                    barrier.wait(timeout=10)
                    delta = [{"role": "user", "content": "fixture followup"}]
                    peer.send(wire({**body, "previous_response_id": "resp_1", "input": delta}))
                    second, _ = receive_terminal(peer)
                    assert second["type"] == ("error" if expect_defect else "response.completed"), second
                    if expect_defect:
                        assert second["error"]["code"] == "previous_response_not_found", second
                    return first["response"].get("metadata", {}).get("proxy_reflow", {}).get("run_id")

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(exercise, scenario, count) for scenario, count in upstream.socket_scenarios.items()]
                run_ids = [future.result(timeout=30) for future in futures]
            if not expect_defect:
                assert len(set(run_ids)) == 2, "concurrent folds reused a run ID"
                for scenario, count in upstream.socket_scenarios.items():
                    observations = [o for o in upstream.socket_observations if o["scenario"] == scenario]
                    assert observations[-1]["parent"] == f"resp_{count + 1}", "socket alias escaped its scope"
                assert upstream.parent_rejections == 0 and len(upstream.calls) == 7
            else:
                assert upstream.parent_rejections == 2
            assert upstream.ws_connections == 2 and set(upstream.transports) == {"websocket"}
            result = {"case": "concurrent_sockets_same_visible_id", "passed": True,
                      "distinct_fold_run_ids": len(set(run_ids)) if not expect_defect else None,
                      "parent_rejections": upstream.parent_rejections, "upstream_connections": upstream.ws_connections}
            print(json.dumps(result), flush=True)
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpa", type=Path, required=True)
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expect-defect", action="store_true")
    parser.add_argument("--native-folds", action="store_true", help="Expect dev.4's incremental response folding, not dev.3's bypass")
    parser.add_argument("--cpa-version", choices=("8.0.13", "8.0.15", "8.0.16"), default="8.0.13")
    args = parser.parse_args()
    if not args.cpa.is_file() or not args.dll.is_file():
        raise ValueError("CPA and DLL must be existing local files")
    original = harness.FixtureHandler.do_GET
    harness.FixtureHandler.do_GET = strict_ws
    try:
        cases = [dict(name="disabled_normal", enabled=False, continue_rounds=0),
                 dict(name="disabled_516", enabled=False, continue_rounds=1),
                 dict(name="enabled_normal", enabled=True, continue_rounds=0),
                 dict(name="enabled_516_then_delta", enabled=True, continue_rounds=1),
                 dict(name="enabled_repeated_516_then_delta", enabled=True, continue_rounds=2),
                 dict(name="enabled_516_then_tool_return", enabled=True, continue_rounds=1, tool=True),
                 dict(name="enabled_516_then_full_replay", enabled=True, continue_rounds=1, full_replay=True),
                 dict(name="reconnect_requires_full_replay", enabled=True, continue_rounds=1, reconnect=True),
                 dict(name="requested_model_prefix_and_suffix", enabled=True, continue_rounds=1, model="lab/gpt-6-sol(high)"),
                 dict(name="native_incremental_516_stays_native", enabled=True, continue_rounds=1, native_516=True),
                 dict(name="reload_disabled_control_recovers_full_replay", enabled=False, continue_rounds=0, reconfigure=True),
                 dict(name="reload_after_fold_recovers_full_replay", enabled=True, continue_rounds=1, reconfigure=True)]
        results = [run_case(args.cpa.resolve(), args.dll.resolve(), expect_defect=args.expect_defect,
                            native_folds=args.native_folds, cpa_version=args.cpa_version, **case) for case in cases]
        results.append(run_concurrent_case(args.cpa.resolve(), args.dll.resolve(), expect_defect=args.expect_defect,
                                           cpa_version=args.cpa_version))
    finally:
        harness.FixtureHandler.do_GET = original
    report = {"test_kind": "real isolated CPA + strict synthetic WS cache; not live-model/Desktop acceptance",
              "expected_old_defect": args.expect_defect, "cases": results, "billable_model_calls": 0,
              "production_config_modified": False, "cpa_version": args.cpa_version,
              "plugin_sha256": hashlib.sha256(args.dll.read_bytes()).hexdigest()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("Run without Python -O; assertions are required.")
    main()
