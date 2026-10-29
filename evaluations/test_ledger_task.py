"""Validate the new grader against deliberate accounting defects, without a model."""
from pathlib import Path
import tempfile
import unittest

import run as evaluation
from ledger_task import ORACLE, STARTER


class LedgerGraderTests(unittest.TestCase):
    def grade(self, source):
        with tempfile.TemporaryDirectory(prefix="reflow-ledger-grader-") as temporary:
            path = Path(temporary) / "solution.py"
            path.write_text(source, encoding="utf-8")
            return evaluation.grade("ledger", path)

    def test_reference_and_broken_start_are_distinguished(self):
        good, broken = self.grade(ORACLE), self.grade(STARTER)
        self.assertEqual(good, {"status": "scored", "total": 18, "passed": 18, "failed": []})
        self.assertEqual(broken["status"], "scored")
        self.assertGreaterEqual(broken["passed"], 0)
        self.assertLess(broken["passed"], 18)

    def test_each_independent_accounting_defect_is_rejected(self):
        defects = {
            "visible_is_billed": ('client = dict(input=known[0]["input"], cached=known[0]["cached"], reasoning=billed["reasoning"],',
                                   'client = dict(input=billed["input"], cached=billed["cached"], reasoning=billed["reasoning"],'),
            "missing_usage_hidden": ('complete = len(known) == n', 'complete = True'),
            "failed_result_counted_success": ('sum(results[c]["success"] for c in matched)', 'len(matched)'),
            "unknown_results_counted": ('matched = calls.intersection(results)', 'matched = set(results)'),
            "scopes_mixed": ('groups.setdefault((scope, response)', 'groups.setdefault(("shared", response)'),
            "event_conflict_ignored": ('if key in seen and seen[key] != normalized:', 'if False:'),
            "discarded_billing_dropped": ('known = [r["usage"] for r in rounds if r["usage"] is not None]',
                                         'known = [r["usage"] for r in rounds[-1:] if r["usage"] is not None]'),
            "bool_counter_accepted": ('type(value) is not int', 'not isinstance(value, int)'),
        }
        for name, (old, new) in defects.items():
            with self.subTest(defect=name):
                self.assertEqual(ORACLE.count(old), 1)
                result = self.grade(ORACLE.replace(old, new))
                self.assertEqual(result["status"], "scored")
                self.assertGreaterEqual(result["passed"], 0)
                self.assertLess(result["passed"], result["total"])
