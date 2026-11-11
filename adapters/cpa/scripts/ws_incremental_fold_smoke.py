"""Real isolated CPA 8.0.13 with synthetic incremental folds; no live accounts."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time

import ws_incremental_smoke as ws
from diagnostic_assertions import assert_log_run

harness = ws.harness


def run_case(executable, library, *, name, root_fold=0, triggers=(516,), final_reasoning=70,
             first_tool=False, final_tool=False, no_encrypted=False, failure=None,
             zero_budget=False, expect_unfolded=False, cpa_version="8.0.13", omit_settings=False):
    with tempfile.TemporaryDirectory(prefix="codexreflow-incremental-fold-") as tmp:
        root = Path(tmp).resolve()
        assert root.parent == Path(tempfile.gettempdir()).resolve()
        with harness.isolated_cpa(executable, library, root, auto_models=True) as (base, upstream, headers):
            assert headers.get("X-Cpa-Version") == cpa_version
            harness.set_enabled(base, True)
            if zero_budget:
                harness.local_request(base + "/v0/management/plugins/codexreflow/config", {"max_continue": 0}, "PATCH")
                time.sleep(0.8)  # Wait for the owned host's asynchronous config/executor reload.
            upstream.parent_observations, upstream.parent_rejections = [], 0
            first_count = root_fold + 1
            upstream.rounds = [ws.round_events(n, reasoning=516, tentative=True) for n in range(1, first_count)]
            upstream.rounds.append(ws.round_events(first_count, reasoning=40, tool=first_tool))
            for offset, tokens in enumerate(triggers, start=1):
                upstream.rounds.append(ws.round_events(first_count + offset, reasoning=tokens, tentative=True))
            native_first = upstream.rounds[first_count]
            if no_encrypted:
                for event in native_first:
                    if isinstance(event.get("item"), dict):
                        event["item"].pop("encrypted_content", None)
                for item in native_first[-1]["response"]["output"]:
                    item.pop("encrypted_content", None)
            if failure:
                native_first[-1]["type"] = "response." + failure
                native_first[-1]["response"]["status"] = failure
            attempts = 0 if expect_unfolded or no_encrypted or failure or zero_budget else min(3, len(triggers))
            upstream.rounds.append(ws.round_events(first_count + len(triggers) + 1, reasoning=final_reasoning, tool=final_tool))
            visible_second = f"resp_{first_count + 1}"
            last_second = first_count + 1 + attempts
            # Add a following generation so ID bridging and tool-parent
            # preservation are verified after the hidden incremental fold.
            if attempts == len(triggers):
                upstream.rounds.append(ws.round_events(last_second + 1, reasoning=40))
            body = {"type": "response.create", "model": harness.MODEL, "stream": True, "store": False,
                    "instructions": "synthetic regression only", "reasoning": {"effort": "low"},
                    "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
                    "input": [{"role": "user", "content": "fixture original context must survive"}]}
            url = base.replace("http:", "ws:") + "/v1/responses"
            with ws.LoopbackWebSocketClient(url, harness.FIXTURE_KEY) as peer:
                peer.socket.settimeout(12)
                peer.send(ws.wire(body))
                first, _ = ws.receive_terminal(peer)
                assert first["type"] == "response.completed" and len(upstream.calls) == first_count
                assert_log_run(root / "cpa.stdout.log", first)
                delta = ([{"type": "function_call_output", "call_id": "call_fixture_1", "output": "fixture tool result 中文"}]
                         if first_tool else [{"role": "user", "content": "fixture incremental delta"}])
                incremental = {**body, "previous_response_id": first["response"]["id"], "input": delta}
                if omit_settings:
                    for key in ["instructions", "tools", "reasoning"]:
                        incremental.pop(key)
                peer.send(ws.wire(incremental))
                try:
                    second, events = ws.receive_terminal(peer)
                except (EOFError, AssertionError):
                    if failure != "failed":
                        raise
                    # The native executor can reject response.failed before
                    # success-only stream hooks run. Check that no hidden call
                    # replaced the failure with a fabricated normal response.
                    assert len(upstream.calls) == first_count + 1
                    log = (root / "cpa.stdout.log").read_text(encoding="utf-8", errors="replace")
                    assert "response.failed" in log or "upstream_failed" in log
                    report = {"case": name, "passed": True, "native_continuations": 0,
                              "next_terminal": "native_socket_closed", "host_preempted_response_hook": True}
                    print(json.dumps(report), flush=True)
                    return report
                assert second["type"] == "response." + (failure or "completed"), second
                assert len(upstream.calls) == first_count + 1 + attempts, "wrong native continuation count"
                assert upstream.calls[first_count]["input"] == delta
                assert upstream.calls[first_count]["previous_response_id"] == f"resp_{first_count}"
                if expect_unfolded:
                    assert "proxy_reflow" not in second["response"].get("metadata", {})
                else:
                    info = second["response"]["metadata"]["proxy_reflow"]
                    assert info["path"] == "ws_incremental"
                    assert info["rounds_completed"] == 1 + attempts
                    assert info["continuations_completed"] == attempts
                    assert second["response"]["id"] == visible_second
                    sequence = [event["sequence_number"] for event in events if "sequence_number" in event]
                    assert sequence == list(range(len(sequence)))
                    expected_stop = ("upstream_" + failure if failure else "no_encrypted_content" if no_encrypted else
                                     "max_continue" if zero_budget or len(triggers) > 3 else "normal")
                    assert info["stop_reason"] == expected_stop, info
                    assert_log_run(root / "cpa.stdout.log", second)
                for call in upstream.calls[first_count + 1:]:
                    assert "previous_response_id" not in call, "hidden round accidentally re-used the parent delta"
                    encoded = json.dumps(call["input"], ensure_ascii=False)
                    assert "fixture original context must survive" in encoded
                    assert encoded.count("fixture tool result 中文" if first_tool else "fixture incremental delta") == 1
                    assert "discard me" not in encoded, "tentative answer replayed into canonical history"
                    assert call["input"][-1]["phase"] == "commentary"
                    if omit_settings:
                        assert call["instructions"] == body["instructions"] and call["tools"] == body["tools"]
                        assert call["reasoning"] == body["reasoning"], "native inherited settings lost during full replay"
                if attempts and not failure:
                    if attempts == len(triggers):
                        assert "discard me" not in ws.wire(second).decode(), "tentative tool/text leaked"
                    else:
                        assert len([item for item in second["response"]["output"] if item.get("type") == "message"]) == 1
                    expected_tokens = sum(triggers[:attempts + 1]) if len(triggers) > attempts else sum(triggers) + final_reasoning
                    assert second["response"]["usage"]["output_tokens_details"]["reasoning_tokens"] == expected_tokens
                if not failure and not zero_budget and not no_encrypted and not expect_unfolded:
                    follow = ([{"type": "function_call_output", "call_id": "call_fixture_1", "output": "fixture returned final tool"}]
                              if final_tool else [{"role": "user", "content": "fixture after native fold"}])
                    peer.send(ws.wire({**body, "previous_response_id": second["response"]["id"], "input": follow}))
                    third, _ = ws.receive_terminal(peer)
                    assert third["type"] == "response.completed", third
                    assert_log_run(root / "cpa.stdout.log", third)
                    assert upstream.calls[-1]["previous_response_id"] == f"resp_{last_second}"
                assert upstream.parent_rejections == 0 and upstream.ws_connections == 1
                assert set(upstream.transports) == {"websocket"}, "unexpected HTTP fallback"
                report = {"case": name, "passed": True, "native_continuations": attempts,
                          "parent_rejections": upstream.parent_rejections, "connections": upstream.ws_connections,
                          "next_terminal": second["type"]}
                print(json.dumps(report), flush=True)
                return report


def run_concurrent(executable, library, cpa_version="8.0.13"):
    # Identical upstream/client IDs on both sockets with different root input;
    # a shared prompt/alias cache must not mix their replay transcripts.
    with tempfile.TemporaryDirectory(prefix="codexreflow-incremental-fold-") as tmp:
        with harness.isolated_cpa(executable, library, Path(tmp), auto_models=True) as (base, upstream, headers):
            assert headers.get("X-Cpa-Version") == cpa_version
            harness.set_enabled(base, True)
            upstream.parent_observations, upstream.parent_rejections = [], 0
            upstream.fixture_lock = threading.Lock()
            upstream.socket_scenarios = {"fixture-socket-A": 1, "fixture-socket-B": 2}
            upstream.socket_native_counts = {"fixture-socket-A": 1, "fixture-socket-B": 2}
            upstream.socket_observations = []
            barrier = threading.Barrier(2)
            def exercise(label, count):
                body = {"type": "response.create", "model": harness.MODEL, "stream": True, "store": False,
                        "instructions": "synthetic concurrent fixture", "reasoning": {"effort": "low"},
                        "input": [{"role": "user", "content": label}]}
                with ws.LoopbackWebSocketClient(base.replace("http:", "ws:") + "/v1/responses", harness.FIXTURE_KEY) as peer:
                    peer.send(ws.wire(body));first, _ = ws.receive_terminal(peer)
                    barrier.wait(timeout=10)
                    peer.send(ws.wire({**body, "previous_response_id": first["response"]["id"],
                                       "input": [{"role": "user", "content": "fixture native delta"}]}))
                    second, _ = ws.receive_terminal(peer)
                    assert second["type"] == "response.completed"
                    info = second["response"]["metadata"]["proxy_reflow"]
                    assert info["path"] == "ws_incremental" and info["continuations_completed"] == count
                    assert_log_run(Path(tmp) / "cpa.stdout.log", second)
                    return info["run_id"]
            with ThreadPoolExecutor(max_workers=2) as pool:
                runs = [future.result(timeout=30) for future in
                        [pool.submit(exercise, label, count) for label, count in upstream.socket_scenarios.items()]]
            assert len(set(runs)) == 2 and upstream.parent_rejections == 0
            result = {"case": "concurrent_incremental_sockets", "passed": True, "distinct_native_runs": len(set(runs))}
            print(json.dumps(result), flush=True)
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpa", type=Path, required=True)
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expect-unfolded", action="store_true", help="Old dev.3 control must not fold incremental triggers")
    parser.add_argument("--cpa-version", choices=("8.0.13", "8.0.15", "8.0.16"), default="8.0.13")
    args = parser.parse_args()
    if not args.cpa.is_file() or not args.dll.is_file():
        raise ValueError("existing pinned CPA and local DLL required")
    original = harness.FixtureHandler.do_GET
    harness.FixtureHandler.do_GET = ws.strict_ws
    try:
        cases = [dict(name="native_516", triggers=(516,)),
                 dict(name="native_1034", triggers=(1034,)),
                 dict(name="root_fold_then_native_fold", root_fold=1),
                 dict(name="tool_return_then_native_fold", root_fold=1, first_tool=True),
                 dict(name="native_fold_then_tool_return", final_tool=True),
                 dict(name="repeated_native_516", triggers=(516, 516)),
                 dict(name="native_omitted_settings_inherit", omit_settings=True),
                 dict(name="zero_added_reasoning", final_reasoning=0)]
        if not args.expect_unfolded:
            cases += [dict(name="native_max_continue", triggers=(516, 516, 516, 516)),
                      dict(name="native_zero_budget", zero_budget=True),
                      dict(name="native_missing_encrypted", no_encrypted=True),
                      dict(name="native_failed", failure="failed"),
                      dict(name="native_incomplete", failure="incomplete")]
        results = [run_case(args.cpa.resolve(), args.dll.resolve(), expect_unfolded=args.expect_unfolded,
                            cpa_version=args.cpa_version, **case)
                   for case in cases]
        if not args.expect_unfolded:
            results.append(run_concurrent(args.cpa.resolve(), args.dll.resolve(), args.cpa_version))
    finally:
        harness.FixtureHandler.do_GET = original
    report = {"test_kind": "real isolated CPA + strict synthetic WS incremental folds; not live-model acceptance",
              "expected_old_bypass": args.expect_unfolded, "cases": results, "billable_model_calls": 0,
              "production_config_modified": False, "cpa_version": args.cpa_version,
              "plugin_sha256": hashlib.sha256(args.dll.read_bytes()).hexdigest()}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("Run without Python -O; assertions are required.")
    main()
