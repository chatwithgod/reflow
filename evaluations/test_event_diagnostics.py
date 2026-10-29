"""Error markers and counter probes must not retain arbitrary content."""
import json
import unittest

from event_diagnostics import COUNTERS, EventDiagnostics, failure_markers


class EventDiagnosticsTests(unittest.TestCase):
    def test_failure_markers_are_fixed_and_success_text_is_ignored(self):
        samples = {"AssertionError: private": "python_assertion", "SyntaxError: private": "python_syntax",
                   "ModuleNotFoundError: private": "python_import", "TypeError: private": "python_name_or_type",
                   "KeyError: private": "python_value_or_key", "ParserError: private": "powershell_parser",
                   "CommandNotFoundException private": "command_unavailable", "PermissionError: private": "permission_denied",
                   "PRIVATE_SENTINEL": "unclassified"}
        for output, marker in samples.items():
            with self.subTest(marker=marker):
                item = dict(type="command_execution", exit_code=1, aggregated_output=output)
                self.assertEqual(failure_markers(item), [marker])
                self.assertEqual(failure_markers(dict(item, exit_code=0, status="completed")), [])

    def test_snapshot_whitelist_ordinals_and_payload_privacy(self):
        metrics = {key: 0 for key in COUNTERS}
        metrics.update(continuations=1, continued_tool_calls=1, ignored="PRIVATE_SENTINEL")
        timer = iter([1.0, 1.1, 2.0, 2.1])
        diagnostic = EventDiagnostics(lambda: metrics, 0, clock=lambda: next(timer))
        item = dict(id="PRIVATE_SENTINEL", type="command_execution", command="PRIVATE_SENTINEL")
        started = diagnostic.observe("item.started", dict(item, status="in_progress"), capture=True)
        metrics["continued_tool_results"] = 1
        completed = diagnostic.observe("item.completed", dict(item, status="failed", exit_code=1,
                        aggregated_output="AssertionError: PRIVATE_SENTINEL"), capture=True)
        self.assertEqual(started["tool_ordinal"], completed["tool_ordinal"])
        self.assertEqual(started["proxy_counters"]["continued_tool_results"], 0)
        self.assertEqual(completed["proxy_counters"]["continued_tool_results"], 1)
        summary = diagnostic.summary()
        self.assertEqual(summary["failure_marker_counts"]["python_assertion"], 1)
        self.assertEqual(summary["unfinished_tracked_tools"], 0)
        self.assertEqual(summary["tool_id_tracking_drops"], 0)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps([started, completed, summary]))

    def test_invalid_or_unavailable_probe_disables_further_probes(self):
        for result in (None, {}, dict.fromkeys(COUNTERS, True), dict.fromkeys(COUNTERS, -1)):
            calls = []
            def probe():
                calls.append(1)
                return result
            diagnostic = EventDiagnostics(probe, 0, clock=lambda: 1)
            item = dict(id="tool", type="command_execution")
            first = diagnostic.observe("item.started", item, capture=True)
            second = diagnostic.observe("item.completed", item, capture=True)
            self.assertEqual(len(calls), 1)
            self.assertNotIn("proxy_counters", first)
            self.assertNotIn("proxy_counters", second)
            self.assertEqual(diagnostic.summary()["counter_probe_errors"], 1)

    def test_exception_has_no_text_and_marker_collection_survives_trace_cap(self):
        def probe():
            raise RuntimeError("PRIVATE_SENTINEL")
        diagnostic = EventDiagnostics(probe, 0, clock=lambda: 1)
        first = diagnostic.observe("item.started", dict(id="tool", type="command_execution"), capture=True)
        dropped = diagnostic.observe("item.completed", dict(type="command_execution", status="failed",
                    aggregated_output="SyntaxError: PRIVATE_SENTINEL"), capture=False)
        self.assertEqual(diagnostic.summary()["failure_marker_counts"]["python_syntax"], 1)
        self.assertEqual(diagnostic.summary()["counter_probes"], 1)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps([first, dropped, diagnostic.summary()]))

    def test_probe_and_identifier_storage_are_bounded(self):
        diagnostic = EventDiagnostics(lambda: dict.fromkeys(COUNTERS, 0), 0, clock=lambda: 1)
        for index in range(100):
            diagnostic.observe("item.started", dict(id=str(index), type="command_execution"), capture=True)
        self.assertEqual(diagnostic.summary()["counter_probes"], 80)
        self.assertEqual(diagnostic.summary()["unfinished_tracked_tools"], 80)
        self.assertEqual(diagnostic.summary()["tool_id_tracking_drops"], 20)

    def test_duplicate_or_missing_identifiers_are_reported_as_ambiguous(self):
        diagnostic = EventDiagnostics(lambda: dict.fromkeys(COUNTERS, 0), 0, clock=lambda: 1)
        item = dict(id="tool", type="command_execution")
        diagnostic.observe("item.started", item, capture=True)
        diagnostic.observe("item.started", item, capture=True)
        diagnostic.observe("item.completed", item, capture=True)
        missing = diagnostic.observe("item.completed", dict(type="command_execution"), capture=True)
        self.assertNotIn("tool_ordinal", missing)
        self.assertEqual(diagnostic.summary()["tool_id_tracking_drops"], 2)

    def test_ansi_colors_do_not_hide_fixed_error_markers(self):
        item = dict(type="command_execution", exit_code=1,
                    aggregated_output="\x1b[31;1mParserError: PRIVATE_SENTINEL\x1b[0m")
        self.assertEqual(failure_markers(item), ["powershell_parser"])
