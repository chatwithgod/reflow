"""Process/lifecycle verification with a synthetic agent; never a live account."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

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
                self.assertEqual(record["client_reported_usage"]["input_tokens"], 10)
                self.assertEqual(record["client_reported_usage"]["output_tokens"], 8 if condition == "on" else 5)
                self.assertEqual(record["upstream_metrics"]["requests"], 0)
                self.assertFalse(record["model_evidence_valid"])

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


if __name__ == "__main__":
    unittest.main()
