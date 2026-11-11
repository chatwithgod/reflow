"""Check native WebSocket prewarms on isolated CPA and a loopback-only upstream."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from fixture_websocket import LoopbackWebSocketClient
from isolated_cpa_smoke import FIXTURE_KEY, MODEL, isolated_cpa, set_enabled
from native_smoke import round_events, wire


def receive_terminal(peer):
    for _ in range(100):
        raw = peer.receive()
        assert raw is not None, "WebSocket closed before terminal event"
        event = json.loads(raw)
        assert event.get("type") != "error", event
        if event.get("type") in ("response.completed", "response.failed", "response.incomplete"):
            return event
    raise AssertionError("WebSocket produced no terminal event")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpa", type=Path, required=True)
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--cpa-version", default="8.0.38")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    core, library = args.cpa.resolve(strict=True), args.dll.resolve(strict=True)
    cases = []
    with tempfile.TemporaryDirectory(prefix="codexreflow-prewarm-") as directory:
        root = Path(directory).resolve()
        assert root.parent == Path(tempfile.gettempdir()).resolve() and root.name.startswith("codexreflow-prewarm-")
        with isolated_cpa(core, library, root, auto_models=True) as (base, upstream, headers):
            assert headers.get("X-Cpa-Version") == args.cpa_version
            set_enabled(base, True)
            for items in ([], [{"role": "user", "content": "synthetic warmup"}]):
                response = {"id": "resp_fixture_warmup", "status": "completed", "output": [],
                            "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}
                upstream.rounds = [[{"type": "response.created", "response": {**response, "status": "in_progress"}},
                                    {"type": "response.completed", "response": response}], round_events(1)]
                upstream.calls, upstream.transports = [], []
                with LoopbackWebSocketClient(base.replace("http:", "ws:") + "/v1/responses", FIXTURE_KEY, headers={
                    "User-Agent": "Codex Desktop/0.163.0-alpha.11.2 (Windows; synthetic fixture)",
                    "Originator": "codex_exec",
                    "OpenAI-Beta": "responses_websockets=2026-02-06",
                    "X-OpenAI-Internal-Codex-Responses-Lite": "true",
                }) as peer:
                    peer.send(wire({"type": "response.create", "model": MODEL, "stream": True,
                                    "generate": False, "store": False, "input": items,
                                    "reasoning": {"effort": "high", "context": "all_turns"}}))
                    warmup = receive_terminal(peer)
                    assert warmup["type"] == "response.completed", warmup
                    assert len(upstream.calls) == 1, "prewarm was not forwarded once to the fixture"
                    sent = upstream.calls[0]
                    assert sent["input"] == items, "prewarm input was changed (empty arrays must stay [])"
                    assert sent["generate"] is False
                    assert warmup["response"]["output"] == []
                    assert "proxy_reflow" not in warmup["response"].get("metadata", {})
                    peer.send(wire({"type": "response.create", "model": MODEL, "store": False,
                                    "previous_response_id": warmup["response"]["id"],
                                    "input": [{"role": "user", "content": "synthetic followup"}]}))
                    terminal = receive_terminal(peer)
                    assert terminal["type"] == "response.completed", terminal
                    assert terminal["response"]["output"][-1]["content"][0]["text"] == "fixture answer 中文"
                assert upstream.transports == ["websocket", "websocket"], "HTTP fallback does not count as native WS"
                cases.append({"prewarm_input_count": len(items), "input_preserved": True,
                              "prewarm_native": True, "same_socket_followup": True,
                              "upstream_transports": upstream.transports.copy(), "passed": True})
    report = {"test_kind": "isolated official CPA with synthetic loopback upstream; no real model calls",
              "cpa_version": args.cpa_version, "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
              "cases": cases, "success": True}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    if not __debug__:
        raise RuntimeError("Assertions are required; run without Python -O")
    main()
