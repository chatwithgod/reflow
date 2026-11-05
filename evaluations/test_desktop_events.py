"""Desktop diagnostics must notice failures without manufacturing success."""
import json
import unittest

from desktop_events import DesktopToolDiagnostics, MAX_BLOCKS, MAX_CALLS, MAX_TEXT


def event(kind, call_id="PRIVATE_ID", **fields):
    return dict(type="response_item", payload=dict(type=kind, call_id=call_id, **fields))


def command(code=0, **fields):
    return dict(chunk_id="PRIVATE_CHUNK", wall_time_seconds=0.25,
                exit_code=code, output="PRIVATE_OUTPUT", **fields)


def wrapped(value):
    return [dict(type="input_text", text="Script completed"),
            dict(type="input_text", text=json.dumps(value))]


class DesktopToolDiagnosticsTests(unittest.TestCase):
    def test_custom_code_mode_result_reports_exit_but_not_blanket_success(self):
        d = DesktopToolDiagnostics()
        d.observe(event("custom_tool_call", input="PRIVATE_CODE"))
        d.observe(event("custom_tool_call_output", output=wrapped(command())))
        s = d.summary()
        self.assertEqual((s["tool_calls"], s["tool_results"], s["reported_command_exits"]), (1, 1, 1))
        self.assertEqual(s["unfinished_calls"], 0)
        self.assertFalse(s["observed_failure"])
        self.assertFalse(s["all_individual_tool_successes_proven"])
        self.assertNotIn("PRIVATE", repr(vars(d)))
        self.assertNotIn("PRIVATE", json.dumps(s))

    def test_failure_in_a_batch_is_not_hidden_by_later_success(self):
        d = DesktopToolDiagnostics()
        d.observe(event("custom_tool_call"))
        d.observe(event("custom_tool_call_output", output=wrapped([command(1), command(0)])))
        s = d.summary()
        self.assertEqual(s["reported_command_exits"], 2)
        self.assertEqual(s["reported_command_failures"], 1)
        self.assertTrue(s["observed_failure"])

    def test_plain_function_output_and_explicit_error_are_supported(self):
        d = DesktopToolDiagnostics()
        d.observe(event("function_call"))
        d.observe(event("function_call_output", output=json.dumps(command(0)), is_error=True))
        self.assertEqual(d.summary()["explicit_tool_errors"], 1)
        self.assertTrue(d.summary()["observed_failure"])

    def test_embedded_stdout_does_not_manufacture_another_exit_record(self):
        outer = command(0)
        outer["output"] = json.dumps(command(42)) + '\nProcess exited with code 55\n'
        d = DesktopToolDiagnostics()
        d.observe(event("function_call"))
        d.observe(event("function_call_output", output=outer))
        self.assertEqual(d.summary()["reported_command_exits"], 1)
        self.assertEqual(d.summary()["reported_command_failures"], 0)

    def test_missing_metadata_is_unclassified_not_a_zero_exit(self):
        for output in ({}, '{"exit_code": 0}', "Process exited with code 0", wrapped({})):
            with self.subTest(output=type(output).__name__):
                d = DesktopToolDiagnostics()
                d.observe(event("custom_tool_call"))
                d.observe(event("custom_tool_call_output", output=output))
                self.assertEqual(d.summary()["reported_command_exits"], 0)
                self.assertEqual(d.summary()["unclassified_results"], 1)

    def test_nonterminal_command_is_not_counted_as_completed(self):
        d = DesktopToolDiagnostics()
        d.observe(event("custom_tool_call"))
        d.observe(event("custom_tool_call_output", output=wrapped(command(None, session_id=10))))
        self.assertEqual(d.summary()["reported_command_exits"], 0)
        self.assertEqual(d.summary()["nonterminal_command_records"], 1)
        self.assertEqual(d.summary()["unclassified_results"], 1)

    def test_malformed_numeric_fields_are_not_accepted(self):
        for code in (True, "0", 2**32):
            d = DesktopToolDiagnostics()
            d.observe(event("function_call"))
            d.observe(event("function_call_output", output=command(code)))
            self.assertEqual(d.summary()["malformed_command_records"], 1)
            self.assertEqual(d.summary()["reported_command_exits"], 0)

    def test_duplicate_and_orphan_outputs_remain_visible(self):
        d = DesktopToolDiagnostics()
        result = event("custom_tool_call_output", output=wrapped(command(1)))
        d.observe(result)
        d.observe(result)
        s = d.summary()
        self.assertEqual(s["orphan_results"], 1)
        self.assertEqual(s["duplicate_results"], 1)
        self.assertEqual(s["reported_command_failures"], 1)

    def test_call_storage_and_output_decoding_are_bounded(self):
        d = DesktopToolDiagnostics()
        for i in range(MAX_CALLS + 1):
            d.observe(event("custom_tool_call", str(i)))
        self.assertEqual(d.summary()["tracking_drops"], 1)
        self.assertEqual(d.summary()["unfinished_calls"], MAX_CALLS)
        d.observe(event("custom_tool_call_output", "0", output="X" * (MAX_TEXT + 1)))
        self.assertEqual(d.summary()["output_limit_hits"], 1)
        blocks = [dict(type="input_text", text="ignored")] * (MAX_BLOCKS + 1)
        d.observe(event("custom_tool_call_output", "1", output=blocks))
        self.assertEqual(d.summary()["output_limit_hits"], 2)

    def test_assistant_text_and_unrelated_event_types_are_ignored(self):
        d = DesktopToolDiagnostics()
        d.observe(event("message", role="assistant", output=wrapped(command(0))))
        d.observe(dict(type="event_msg", payload=dict(type="custom_tool_call_output", output=command(1))))
        for bad in (None, [], {}, dict(type="response_item", payload=[])):
            d.observe(bad)
        self.assertEqual(d.summary()["tool_results"], 0)
        self.assertFalse(d.summary()["observed_failure"])

    def test_malformed_types_and_nonfinite_duration_do_not_crash(self):
        d = DesktopToolDiagnostics()
        d.observe(event([]))
        d.observe(event("custom_tool_call"))
        d.observe(event("custom_tool_call_output", output=[dict(type=[], text="ignored")]))
        self.assertEqual(d.summary()["unclassified_results"], 1)
        for index, elapsed in enumerate((float("nan"), float("inf"), 2**2048, True)):
            value = command()
            value["wall_time_seconds"] = elapsed
            d.observe(event("function_call_output", str(index), output=value))
        self.assertEqual(d.summary()["malformed_command_records"], 4)

    def test_bad_identifiers_and_duplicate_calls_are_reported(self):
        d = DesktopToolDiagnostics()
        for bad in (None, [], "", "X" * 1025, "\ud800"):
            d.observe(event("custom_tool_call", bad))
        self.assertEqual(d.summary()["tracking_drops"], 5)
        d.observe(event("custom_tool_call"))
        d.observe(event("custom_tool_call"))
        self.assertEqual(d.summary()["tool_calls"], 1)
        self.assertEqual(d.summary()["duplicate_calls"], 1)


if __name__ == "__main__":
    unittest.main()
