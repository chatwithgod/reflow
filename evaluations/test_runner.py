"""Process/lifecycle verification with a synthetic agent; never a live account."""
import json
import os
from pathlib import Path
import tempfile
import shutil
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import run as evaluation


@unittest.skipUnless(os.environ.get("REFLOW_EVAL_FAKE_CODEX") and os.environ.get("REFLOW_EVAL_REFLOW_BIN"),
                     "explicit fixture and packaged Reflow paths required")
class RunnerProcessTests(unittest.TestCase):
    def args(self, timeout=10):
        return SimpleNamespace(codex=Path(os.environ["REFLOW_EVAL_FAKE_CODEX"]),
                               reflow=Path(os.environ["REFLOW_EVAL_REFLOW_BIN"]),
                               model="synthetic-model", effort="high", timeout=timeout)

    def execute(self, condition, prompt, timeout=10, *, require_inference=False):
        with tempfile.TemporaryDirectory(prefix="reflow-evaluation-test-") as temporary:
            root = Path(temporary)
            record = evaluation.run_trial(self.args(timeout),
                                          {"task": "intervals", "condition": condition, "repeat": 0,
                                           "max_continue": 3 if condition == "on" else 0},
                                          prompt, '{"auth_mode":"chatgpt","tokens":{"access_token":"synthetic-evaluation-token"}}', root,
                                          require_inference=require_inference)
            self.assertEqual(list(root.iterdir()), [], "temporary profile or credentials survived the trial")
            self.assertNotIn("SYNTHETIC_PRIVATE_SENTINEL", json.dumps(record))
            self.assertNotIn("synthetic-evaluation-token", json.dumps(record))
            return record

    def test_both_conditions_use_real_proxy_and_score(self):
        for condition in ("off", "on"):
            with self.subTest(condition=condition):
                record = self.execute(condition, "Fix merge_intervals in solution.py")
                self.assertTrue(record["success"], record)
                self.assertEqual(record["completed_turns"], 1)
                self.assertTrue(record["artifact_changed"])
                self.assertTrue(record["event_trace"])
                for event in record["event_trace"]:
                    self.assertLessEqual(set(event), {"at_seconds", "event", "kind", "status", "exit_code"})
                self.assertEqual(record["client_reported_usage"]["input_tokens"], 10)
                self.assertEqual(record["client_reported_usage"]["output_tokens"], 8 if condition == "on" else 5)
                self.assertEqual(record["upstream_metrics"]["requests"], 0)
                self.assertFalse(record["model_evidence_valid"])
                self.assertTrue(record["tool_roundtrip_metrics_available"])
                self.assertFalse(record["continuation_tool_result_observed"])

    def test_live_gate_rejects_success_without_proxy_inference(self):
        record = self.execute("on", "Fix merge_intervals in solution.py", require_inference=True)
        self.assertEqual(record["score"]["passed"], record["score"]["total"])
        self.assertEqual(record["completed_turns"], 1)
        self.assertEqual(record["status"], "proxy_inference_unverified")
        self.assertFalse(record["success"])

    def test_agent_failure_is_not_a_success(self):
        record = self.execute("on", "SYNTHETIC_AGENT_FAILURE merge_intervals")
        self.assertEqual(record["status"], "agent_error")
        self.assertEqual(record["error_events"], 1)
        self.assertFalse(record["success"])

    def test_timeout_joins_owned_processes_and_removes_credentials(self):
        record = self.execute("on", "SYNTHETIC_AGENT_TIMEOUT merge_intervals", timeout=1)
        self.assertEqual(record["status"], "agent_timeout")
        self.assertFalse(record["success"])

    def test_rate_limit_stops_agent_and_records_only_classification(self):
        record = self.execute("on", "SYNTHETIC_AGENT_RATE_LIMIT parse_chunks", timeout=5)
        self.assertEqual(record["status"], "rate_limited")
        self.assertTrue(record["rate_limit_detected"])
        self.assertFalse(record["success"])

    def test_failed_tool_has_numeric_snapshot_and_fixed_marker_only(self):
        record = self.execute("on", "SYNTHETIC_TOOL_ERRORS merge_intervals")
        self.assertEqual(record["tool_failure_events"], 1)
        diagnostics = record["event_diagnostics"]
        self.assertEqual(diagnostics["counter_probes"], 2)
        self.assertEqual(diagnostics["counter_probe_errors"], 0)
        self.assertEqual(diagnostics["tool_id_tracking_drops"], 0)
        self.assertEqual(diagnostics["failure_marker_counts"]["python_assertion"], 1)
        tools = [item for item in record["event_trace"] if item["kind"] == "command_execution"]
        self.assertEqual(len(tools), 2)
        self.assertEqual(tools[0]["tool_ordinal"], tools[1]["tool_ordinal"])
        self.assertEqual(tools[1]["failure_markers"], ["python_assertion"])
        for event in tools:
            self.assertEqual(event["proxy_counters"]["continuations"], 0)
            self.assertLessEqual(event["at_seconds"], event["counter_probe_started_seconds"])
            self.assertLessEqual(event["counter_probe_started_seconds"], event["counter_probe_finished_seconds"])


if os.name == "nt":
    @unittest.skipUnless(os.environ.get("REFLOW_EVAL_FAKE_CODEX") and os.environ.get("REFLOW_EVAL_REFLOW_BIN"),
                         "explicit fixture and packaged Reflow paths required")
    class WindowsPreflightProcessTests(unittest.TestCase):
        def fixture(self, root, name="agent.exe", host=True):
            binaries = root / "bin"
            binaries.mkdir()
            client = binaries / name
            shutil.copy2(os.environ["REFLOW_EVAL_FAKE_CODEX"], client)
            if host:
                shutil.copy2(os.environ["REFLOW_EVAL_FAKE_CODEX"], binaries / "codex-code-mode-host.exe")
            return client

        def test_preflight_checks_native_writes_and_rejects_outside_writes(self):
            with tempfile.TemporaryDirectory(prefix="reflow-preflight-test-") as temporary:
                root = Path(temporary)
                client = self.fixture(root)
                report = root / "reports"
                report.mkdir()
                result = evaluation.execution_preflight(client, report)
                self.assertEqual(result["status"], "pass", result)
                self.assertTrue(result["native_filesystem_write_verified"])
                self.assertTrue(result["out_of_workspace_write_blocked"])
                self.assertEqual(result["model_calls"], 0)
                self.assertEqual(list(report.iterdir()), [])

        def test_preflight_missing_companion_stops_before_auth_read(self):
            self.check_main_gate("agent.exe", False, "code_mode_host_unavailable")

        def test_preflight_only_never_reads_auth(self):
            with tempfile.TemporaryDirectory(prefix="reflow-preflight-test-") as temporary:
                root = Path(temporary)
                client = self.fixture(root)
                argv = ["run.py", "--preflight-only", "--codex", str(client),
                        "--auth-file", str(root / "auth-must-not-be-read.json")]
                with mock.patch.object(sys, "argv", argv), mock.patch.object(evaluation, "ROOT", root):
                    evaluation.main()
                records = list(root.glob("build/evaluations/*/summary.json"))
                self.assertEqual(len(records), 1)
                record = json.loads(records[0].read_text())
                self.assertEqual(record["execution_preflight"]["status"], "pass")
                self.assertFalse(record["live_account"])
                self.assertEqual(record["model_calls"], 0)
                self.assertFalse(list(root.rglob("auth.json")))
                self.assertFalse(list(root.glob("build/evaluations/*/preflight-*")))

        def test_preflight_native_failure_stops_before_auth_read(self):
            self.check_main_gate("missing-systemroot.exe", True, "missing_systemroot")

        def test_preflight_rejects_unenforced_write_boundary(self):
            self.check_main_gate("unsafe-filesystem.exe", True, "write_boundary_failed")

        def check_main_gate(self, name, host, reason):
            with tempfile.TemporaryDirectory(prefix="reflow-preflight-test-") as temporary:
                root = Path(temporary)
                client = self.fixture(root, name, host)
                # If main reaches auth loading, strict path resolution will fail
                # instead of producing the expected preflight SystemExit.
                missing_auth = root / "auth-must-not-be-read.json"
                argv = ["run.py", "--run-live", "--codex", str(client), "--reflow", os.environ["REFLOW_EVAL_REFLOW_BIN"],
                        "--auth-file", str(missing_auth), "--model", "synthetic-model", "--tasks", "intervals"]
                with mock.patch.object(sys, "argv", argv), mock.patch.object(evaluation, "ROOT", root):
                    with self.assertRaisesRegex(SystemExit, "Execution preflight failed"):
                        evaluation.main()
                records = list(root.glob("build/evaluations/*/results.json"))
                self.assertEqual(len(records), 1)
                record = json.loads(records[0].read_text())
                self.assertEqual(record["results"], [])
                result = record["execution_preflight"]
                self.assertEqual(result["status"], "fail")
                self.assertEqual(result.get("reason", result.get("native_filesystem_reason")), reason)
                self.assertEqual(result["model_calls"], 0)
                self.assertNotIn("SYNTHETIC_PRIVATE_SENTINEL", json.dumps(record))
                self.assertFalse(list(root.rglob("auth.json")))
                self.assertFalse(list(root.glob("build/evaluations/*/preflight-*")))


if __name__ == "__main__":
    unittest.main()
