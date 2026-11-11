"""Summarize Reflow diagnostics by run_id, never by time or WS connection ID.

Reads an existing log file only; no network, credentials or CPA usage queue.
Output contains whitelisted counters/enums and plugin-generated IDs, not raw
lines, request bodies, response text, headers, models or upstream identifiers.
"""

import argparse
import json
from pathlib import Path
import re
import sys

MAX_LINE = 16384
MAX_RUNS = 10000
MAX_EVENTS = 200000
MAX_ROUNDS = 4096
MAX_COUNTER = 2**53 - 1
RUN_ID = re.compile(r"(?:[0-9a-f]{24}|local-[0-9a-f]+-[0-9a-f]+)\Z")
COUNTERS = ("input_tokens", "output_tokens", "total_tokens", "cached_tokens", "reasoning_tokens")
TERMINALS = {"response.completed", "response.incomplete", "response.failed"}
RESULTS = TERMINALS | {"aborted", "startup_error", "host_lifecycle_failed", "host_lifecycle_canceled",
                       "host_lifecycle_rejected", "host_lifecycle_unknown"}
EMISSIONS = {"not_emitted", "host_accepted", "interceptor_returned", "emit_failed", "not_confirmed"}
STOPS = {"normal", "upstream_error", "upstream_eof", "downstream_emit_error", "aborted", "upstream_failed",
         "upstream_incomplete", "no_encrypted_content", "max_continue", "tier_out_of_window",
         "stream_size_limit", "host_lifecycle_failed", "host_lifecycle_canceled", "host_lifecycle_rejected",
         "host_lifecycle_unknown", "replay_context_miss", "replay_size_limit"}


def counter(value):
    return value if type(value) is int and 0 <= value <= MAX_COUNTER else None


def enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else "unknown"


def sanitize_event(raw):
    if not isinstance(raw, dict) or raw.get("plugin") != "codexreflow" or type(raw.get("diagnostic_schema")) is not int or raw["diagnostic_schema"] != 1:
        return None
    run_id = raw.get("run_id")
    if not isinstance(run_id, str) or len(run_id) > 80 or not RUN_ID.fullmatch(run_id):
        return None
    kind = raw.get("event")
    if kind not in ("fold_started", "round_finished", "fold_finished"):
        return None
    event = {"run_id": run_id, "event": kind, "path": enum(raw.get("path"), {"executor", "ws_incremental"})}
    if kind == "round_finished":
        number = counter(raw.get("round"))
        if number is None or not 1 <= number <= MAX_ROUNDS:
            raise ValueError("diagnostic round number exceeds supported bounds")
        usage = raw.get("reported_usage")
        usage = usage if isinstance(usage, dict) else {}
        event.update(round=number, terminal=enum(raw.get("terminal"), TERMINALS),
                     reported_usage={key: counter(usage.get(key)) for key in COUNTERS})
    elif kind == "fold_finished":
        event.update(result=enum(raw.get("result"), RESULTS), emission=enum(raw.get("emission"), EMISSIONS),
                     stop_reason=enum(raw.get("stop_reason"), STOPS))
        for key in ("rounds_started", "rounds_completed", "continuations_started", "continuations_completed"):
            value = counter(raw.get(key))
            if value is None or value > MAX_ROUNDS:
                raise ValueError("invalid diagnostic fold counters")
            event[key] = value
    return event


def parse_line(line):
    if len(line) > MAX_LINE:
        return None
    marker = "[codexreflow] "
    try:
        # JSON logging may wrap the plugin's message in msg/message. Decode the
        # wrapper first rather than treating backslash-escaped JSON as a payload.
        if line.lstrip().startswith("{"):
            outer = json.loads(line)
            if isinstance(outer, dict):
                if outer.get("plugin") == "codexreflow":
                    return sanitize_event(outer)
                line = outer.get("msg", outer.get("message", ""))
        if not isinstance(line, str) or marker not in line:
            return None
        raw, _ = json.JSONDecoder().raw_decode(line.split(marker, 1)[1].lstrip())
        return sanitize_event(raw)
    except (json.JSONDecodeError, RecursionError):
        return None


def read_events(path):
    # readline(size) also bounds memory for a single malicious/accidental huge
    # line. Skip its entire remainder, not a tail that could look like a log.
    with Path(path).open("rb") as source:
        while line := source.readline(MAX_LINE + 1):
            if len(line) > MAX_LINE:
                while line and not line.endswith(b"\n"):
                    line = source.readline(MAX_LINE + 1)
                continue
            event = parse_line(line.decode("utf-8", errors="replace"))
            if event is not None:
                yield event


def summarize(events):
    runs = {}
    for count, event in enumerate(events, 1):
        if count > MAX_EVENTS:
            raise ValueError("too many diagnostic events; split the input log")
        # Re-sanitize even when called directly by a test/other Python caller.
        event = sanitize_event({**event, "plugin": "codexreflow", "diagnostic_schema": 1})
        if event is None:
            continue
        run_id = event["run_id"]
        if run_id not in runs:
            if len(runs) >= MAX_RUNS:
                raise ValueError("too many diagnostic runs; split the input log")
            runs[run_id] = {"starts": [], "ends": [], "rounds": {}, "duplicate_rounds": False, "paths": set()}
        run = runs[run_id]
        if event["path"] != "unknown":
            run["paths"].add(event["path"])
        if event["event"] == "fold_started":
            run["starts"].append(True)
        elif event["event"] == "fold_finished":
            run["ends"].append(event)
        else:
            number = event["round"]
            if number in run["rounds"]:
                run["duplicate_rounds"] = True
            else:
                run["rounds"][number] = event
    output = []
    for run_id, run in sorted(runs.items()):
        rounds = [run["rounds"][number] for number in sorted(run["rounds"])]
        end = run["ends"][0] if len(run["ends"]) == 1 else None
        expected = end["rounds_completed"] if end else None
        consistent = bool(end and end["rounds_started"] >= expected and
                          end["continuations_started"] == max(0, end["rounds_started"] - 1) and
                          end["continuations_completed"] == max(0, expected - 1))
        if end and end["result"] == "response.completed":
            consistent = consistent and expected == end["rounds_started"]
        output.append({
            "run_id": run_id,
            "path": next(iter(run["paths"])) if len(run["paths"]) == 1 else "unknown",
            "finished": end is not None,
            "evidence_complete": (len(run["starts"]) == 1 and len(run["paths"]) == 1 and consistent and
                                  not run["duplicate_rounds"] and [r["round"] for r in rounds] == list(range(1, expected + 1))),
            "ambiguous_events": len(run["ends"]) > 1 or len(run["starts"]) > 1 or run["duplicate_rounds"] or len(run["paths"]) > 1,
            "reasoning_tokens_by_round": [r["reported_usage"]["reasoning_tokens"] for r in rounds],
            "observed_reasoning_sum": (sum(r["reported_usage"]["reasoning_tokens"] for r in rounds)
                                       if rounds and all(r["reported_usage"]["reasoning_tokens"] is not None for r in rounds) else None),
            "rounds": [{k: v for k, v in r.items() if k not in ("run_id", "event", "path")} for r in rounds],
            "finish": {k: v for k, v in end.items() if k not in ("run_id", "event", "path")} if end else None,
            "usage_join": "unavailable", "client_delivery_confirmed": False,
        })
    return {"schema": 1, "runs": output, "notice": "Plugin-observed rounds only; not a billing join, delivery receipt or quality assessment."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--output", type=Path, help="Optional NEW sanitized JSON file; never overwrite")
    args = parser.parse_args()
    result = json.dumps(summarize(read_events(args.log)), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as dest:
            dest.write(result)
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
