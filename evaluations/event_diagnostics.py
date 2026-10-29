"""Bounded event diagnostics: numeric snapshots and fixed error markers only."""
import re
import time

TOOL_KINDS = {"command_execution", "file_change", "mcp_tool_call"}
COUNTERS = ("requests", "completed", "continuations", "continued_tool_responses",
            "continued_tool_calls", "continued_tool_results", "tool_tracking_drops")
PATTERNS = {
    "python_assertion": r"(?m)^\s*AssertionError(?::|\s*$)",
    "python_syntax": r"(?m)^\s*(?:SyntaxError|IndentationError|TabError):",
    "python_import": r"(?m)^\s*(?:ModuleNotFoundError|ImportError):",
    "python_name_or_type": r"(?m)^\s*(?:NameError|TypeError|AttributeError):",
    "python_value_or_key": r"(?m)^\s*(?:ValueError|KeyError|IndexError):",
    "powershell_parser": r"(?m)^\s*ParserError\s*:|FullyQualifiedErrorId\s*:\s*(?:UnexpectedToken|Missing\w+)",
    "command_unavailable": r"CommandNotFoundException|is not recognized as (?:an internal|the name of)",
    "permission_denied": r"(?m)^\s*PermissionError:|Access is denied|UnauthorizedAccessException",
}


def failed_tool(item):
    return item.get("type") in TOOL_KINDS and (item.get("status") == "failed" or
            type(item.get("exit_code")) is int and item["exit_code"] != 0)


def failure_markers(item):
    """Markers are diagnostic hints, not proof of the underlying cause."""
    if not failed_tool(item):
        return []
    output = item.get("aggregated_output", "")
    error = item.get("error")
    message = error.get("message", "") if isinstance(error, dict) else ""
    # Never interpolate raw values into exceptions or reports, or hash/store them.
    text = "\n".join(value[:65536] for value in (output, message) if isinstance(value, str))
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return [name for name, pattern in PATTERNS.items() if re.search(pattern, text, re.IGNORECASE)] or ["unclassified"]


class EventDiagnostics:
    def __init__(self, read_metrics, started, clock=time.monotonic):
        self.read_metrics = read_metrics
        self.started = started
        self.clock = clock
        self.probes = 0
        self.probe_errors = 0
        self.probes_disabled = False
        self.markers = dict.fromkeys((*PATTERNS, "unclassified"), 0)
        self.active = {}
        self.next_ordinal = 1
        self.id_tracking_drops = 0

    def observe(self, event_type, item, *, capture):
        extra = {}
        if item.get("type") not in TOOL_KINDS:
            return extra
        if event_type == "item.completed":
            markers = failure_markers(item)
            for marker in markers:
                self.markers[marker] += 1
            if markers:
                extra["failure_markers"] = markers
        if not capture:
            return extra
        raw_id = item.get("id")
        valid = isinstance(raw_id, str) and 0 < len(raw_id) <= 1024
        key = (item["type"], raw_id) if valid else None
        if event_type == "item.started" and key in self.active:
            self.id_tracking_drops += 1
        if event_type == "item.started" and key is not None and key not in self.active and len(self.active) < 80:
            self.active[key] = self.next_ordinal
            self.next_ordinal += 1
        ordinal = self.active.get(key)
        if ordinal is None:
            self.id_tracking_drops += 1
        else:
            extra["tool_ordinal"] = ordinal
        if event_type == "item.completed":
            self.active.pop(key, None)
        if self.probes_disabled or self.probes >= 80:
            return extra
        self.probes += 1
        before = round(self.clock() - self.started, 3)
        try:
            metrics = self.read_metrics()
            valid = isinstance(metrics, dict) and all(type(metrics.get(key)) is int and metrics[key] >= 0 for key in COUNTERS)
        except Exception:
            valid = False
        after = round(self.clock() - self.started, 3)
        extra["counter_probe_started_seconds"] = before
        extra["counter_probe_finished_seconds"] = after
        if not valid:
            self.probe_errors += 1
            self.probes_disabled = True
        else:
            extra["proxy_counters"] = {key: metrics[key] for key in COUNTERS}
        return extra

    def summary(self):
        return {"version": 1, "counter_probes": self.probes, "counter_probe_errors": self.probe_errors,
                "counter_probes_disabled": self.probes_disabled, "failure_marker_counts": dict(self.markers),
                "tool_id_tracking_drops": self.id_tracking_drops, "unfinished_tracked_tools": len(self.active)}
