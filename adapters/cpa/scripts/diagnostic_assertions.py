"""Test-only assertions for synthetic native/isolated CPA runs."""

import time

from summarize_diagnostics import read_events, summarize


def assert_run(events, info):
    assert info.get("diagnostic_schema") == 1, "new diagnostic schema not present"
    assert info.get("usage_join") == "unavailable", "invented usage execution join"
    matches = [run for run in summarize(events)["runs"] if run["run_id"] == info["run_id"]]
    assert len(matches) == 1, "missing per-run diagnostics"
    run = matches[0]
    assert run["evidence_complete"], run
    for key in ("rounds_started", "rounds_completed", "continuations_started", "continuations_completed", "stop_reason"):
        assert run["finish"][key] == info[key], (key, run)
    return run


def assert_log_run(path, terminal):
    info = terminal["response"]["metadata"]["proxy_reflow"]
    # Retain support for the old dev.3 control and dev.4 baseline harness runs.
    if info.get("diagnostic_schema") != 1:
        return None
    deadline = time.monotonic() + 3
    while True:
        try:
            run = assert_run(list(read_events(path)), info)
            break
        except AssertionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)  # Host logs can flush after the client sees terminal.
    rounds = terminal["response"]["metadata"].get("proxy_rounds") or []
    assert run["reasoning_tokens_by_round"] == [r["reasoning_tokens"] for r in rounds], run
    return run
