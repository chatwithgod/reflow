"""Read numeric tool diagnostics from Desktop rollout events, never tool bodies.

Code Mode can print arbitrary text. A decoded command envelope is reported
metadata, not independent proof that every command in that Code Mode call ran.
This module deliberately does not produce a trial acceptance verdict.
"""
import hashlib
import json


MAX_CALLS = 128
MAX_ID = 1024
MAX_BLOCKS = 16
MAX_TEXT = 65536
TEXT_TYPES = {"input_text", "output_text", "text"}
CALL_TYPES = {"custom_tool_call", "function_call"}
RESULT_TYPES = {"custom_tool_call_output", "function_call_output"}


def _identity(value):
    if not isinstance(value, str) or not 0 < len(value) <= MAX_ID:
        return None
    try:
        return hashlib.sha256(value.encode("utf-8")).digest()
    except UnicodeError:
        return None


def _command_record(value):
    """Recognize the exec_command envelope; never search its output for codes."""
    if not isinstance(value, dict):
        return None
    if not all(k in value for k in ("chunk_id", "wall_time_seconds", "output")):
        return None
    elapsed = value["wall_time_seconds"]
    if (not isinstance(value["chunk_id"], str) or len(value["chunk_id"]) > 128
            or type(elapsed) not in (int, float) or not 0 <= elapsed <= 86400
            or not isinstance(value["output"], str)):
        return {"invalid": 1}
    code = value.get("exit_code")
    if type(code) is int and -(2**31) <= code < 2**32:
        return {"exits": 1, "failures": int(code != 0)}
    if code is None and type(value.get("session_id")) is int:
        return {"nonterminal": 1}
    return {"invalid": 1}


def _output_numbers(output):
    numbers = dict(exits=0, failures=0, nonterminal=0, invalid=0, limits=0)

    def packet(value):
        record = _command_record(value)
        if record:
            for key, count in record.items():
                numbers[key] += count

    def text(value):
        if not isinstance(value, str):
            return
        if len(value) > MAX_TEXT:
            numbers["limits"] += 1
            return
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError):
            return
        if isinstance(decoded, list):
            if len(decoded) > MAX_BLOCKS:
                numbers["limits"] += 1
            for item in decoded[:MAX_BLOCKS]:
                packet(item)
        else:
            packet(decoded)

    if isinstance(output, dict):
        packet(output)
    elif isinstance(output, str):
        text(output)
    elif isinstance(output, list):
        if len(output) > MAX_BLOCKS:
            numbers["limits"] += 1
        for block in output[:MAX_BLOCKS]:
            if isinstance(block, dict) and isinstance(block.get("type"), str) and block["type"] in TEXT_TYPES:
                text(block.get("text"))
    return numbers


class DesktopToolDiagnostics:
    """Feed only rollout events belonging to the selected isolated task.

    Call identifiers are bounded, hashed in memory and never exported. The
    caller owns file offsets, task selection and any live-stop policy.
    """
    def __init__(self):
        self._calls = set()
        self._results = set()
        self._counts = dict(tool_calls=0, tool_results=0, reported_command_exits=0,
                            reported_command_failures=0, nonterminal_command_records=0,
                            explicit_tool_errors=0, unclassified_results=0,
                            malformed_command_records=0, output_limit_hits=0,
                            duplicate_calls=0, duplicate_results=0,
                            orphan_results=0, tracking_drops=0)

    def observe(self, event):
        if not isinstance(event, dict) or event.get("type") != "response_item":
            return
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        if not isinstance(kind, str) or kind not in CALL_TYPES | RESULT_TYPES:
            return
        key = _identity(payload.get("call_id"))
        if key is None:
            self._counts["tracking_drops"] += 1
            return
        if kind in CALL_TYPES:
            if key in self._calls:
                self._counts["duplicate_calls"] += 1
            elif len(self._calls) >= MAX_CALLS:
                self._counts["tracking_drops"] += 1
            else:
                self._calls.add(key)
                self._counts["tool_calls"] += 1
            return
        if key in self._results:
            self._counts["duplicate_results"] += 1
            return
        if len(self._results) >= MAX_CALLS:
            self._counts["tracking_drops"] += 1
            return
        self._results.add(key)
        self._counts["tool_results"] += 1
        if key not in self._calls:
            self._counts["orphan_results"] += 1
        explicit_error = payload.get("is_error") is True
        self._counts["explicit_tool_errors"] += explicit_error
        numbers = _output_numbers(payload.get("output"))
        mapping = {"exits": "reported_command_exits", "failures": "reported_command_failures",
                   "nonterminal": "nonterminal_command_records", "invalid": "malformed_command_records",
                   "limits": "output_limit_hits"}
        for source, target in mapping.items():
            self._counts[target] += numbers[source]
        if not numbers["exits"] and not explicit_error:
            self._counts["unclassified_results"] += 1

    def summary(self):
        return {"version": 1, **self._counts,
                "unfinished_calls": len(self._calls - self._results),
                "observed_failure": bool(self._counts["reported_command_failures"]
                                         or self._counts["explicit_tool_errors"]),
                "all_individual_tool_successes_proven": False}
