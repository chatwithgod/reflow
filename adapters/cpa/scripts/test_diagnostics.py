import json
from pathlib import Path
import tempfile
import unittest

from summarize_diagnostics import MAX_LINE, parse_line, read_events, summarize


RID = "a" * 24


def event(kind, rid=RID, **fields):
    return {"plugin": "codexreflow", "diagnostic_schema": 1, "run_id": rid, "event": kind, "path": "executor", **fields}


def fixture(rid=RID, tokens=(516, 0)):
    return [event("fold_started", rid)] + [
        event("round_finished", rid, round=i, terminal="response.completed", reported_usage={"reasoning_tokens": token})
        for i, token in enumerate(tokens, 1)
    ] + [event("fold_finished", rid, rounds_started=len(tokens), rounds_completed=len(tokens),
               continuations_started=max(0, len(tokens) - 1), continuations_completed=max(0, len(tokens) - 1),
               result="response.completed", emission="host_accepted", stop_reason="normal")]


class DiagnosticTests(unittest.TestCase):
    def test_out_of_order_and_zero_is_not_unknown(self):
        run = summarize(reversed(fixture()))["runs"][0]
        self.assertTrue(run["evidence_complete"])
        self.assertEqual(run["reasoning_tokens_by_round"], [516, 0])
        self.assertEqual(run["observed_reasoning_sum"], 516)
        self.assertFalse(run["client_delivery_confirmed"])
        self.assertEqual(run["usage_join"], "unavailable")

    def test_interleaved_identical_tokens_do_not_merge_runs(self):
        a, b = fixture(), fixture("b" * 24)
        runs = summarize([item for pair in zip(a, b) for item in pair])["runs"]
        self.assertEqual(len(runs), 2)
        self.assertTrue(all(r["evidence_complete"] for r in runs))

    def test_missing_duplicate_and_conflicting_events_not_complete(self):
        f = fixture()
        for events in [f[1:], f[:-1], f[:1] + f[2:], f + [f[-1]], f + [f[1]], f + [f[0]],
                       f + [event("fold_started", path="ws_incremental")]]:
            with self.subTest(events=events):
                self.assertFalse(summarize(events)["runs"][0]["evidence_complete"])

    def test_startup_failure_has_no_invented_terminal_or_usage(self):
        events = [event("fold_started"), event("fold_finished", rounds_started=1, rounds_completed=0,
                  continuations_started=0, continuations_completed=0, result="startup_error",
                  emission="not_emitted", stop_reason="upstream_error")]
        run = summarize(events)["runs"][0]
        self.assertTrue(run["evidence_complete"])
        self.assertIsNone(run["observed_reasoning_sum"])
        self.assertEqual(run["finish"]["result"], "startup_error")

    def test_unknown_counters_not_zero(self):
        for value in [None, "516", -1, True, 1.5, 2**53, {"secret": "prompt"}]:
            run = summarize(fixture(tokens=(value,)))["runs"][0]
            self.assertEqual(run["reasoning_tokens_by_round"], [None])
            self.assertIsNone(run["observed_reasoning_sum"])

    def test_whitelist_removes_private_fields_and_values(self):
        f = fixture()
        for e in f:
            e.update(auth="secret-auth", request_id="secret-id", body="secret-prompt", error="secret-error")
        f[-1]["stop_reason"] = "secret-stop"
        f[1]["terminal"] = "secret-event"
        result = json.dumps(summarize(f))
        self.assertNotIn("secret", result)
        self.assertNotIn("request_id", result)

    def test_plain_and_json_logs(self):
        raw = event("fold_started")
        for line in [json.dumps(raw), "[time] [info] [codexreflow] " + json.dumps(raw),
                     json.dumps({"msg": "[codexreflow] " + json.dumps(raw), "auth": "secret"}),
                     json.dumps({"message": "[codexreflow] " + json.dumps(raw)})]:
            self.assertEqual(parse_line(line)["run_id"], RID)
        for line in ["unrelated prompt", "[codexreflow] {not-json}", json.dumps(event("fold_started", rid="private-id")),
                     json.dumps({**raw, "diagnostic_schema": True}), "x" * (MAX_LINE + 1)]:
            self.assertIsNone(parse_line(line))

    def test_bad_bounds_and_counts(self):
        with self.assertRaises(ValueError):
            summarize([event("round_finished", round=9999999999)])
        f = fixture()
        f[-1]["continuations_started"] = 0
        self.assertFalse(summarize(f)["runs"][0]["evidence_complete"])

    def test_oversized_line_tail_cannot_be_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic.log"
            raw = json.dumps(event("fold_started"))
            path.write_text("x" * (MAX_LINE + 1) + "[codexreflow] " + raw + "\n" + raw + "\n", encoding="utf-8")
            self.assertEqual(len(list(read_events(path))), 1)
            path.write_text("\u6d4b" * (MAX_LINE // 2) + "[codexreflow] " + raw + "\n" + raw + "\n", encoding="utf-8")
            self.assertEqual(len(list(read_events(path))), 1)


if __name__ == "__main__":
    unittest.main()
