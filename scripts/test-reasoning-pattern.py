"""Synthetic checks for the read-only README frequency report; no live accounts."""
from contextlib import closing
import hashlib
import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("pattern_stats", Path(__file__).with_name("summarize-reasoning-pattern.py"))
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


class FrequencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="reflow-pattern-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name)/"synthetic.db"
        self.since = stats.parse_time("2026-10-01T00:00:00+08:00")
        self.until = stats.parse_time("2026-11-12T00:00:00+08:00")
        self.begin = int(self.since.timestamp()*1000)
        self.end = int(self.until.timestamp()*1000)
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("""CREATE TABLE usage_events(event_key TEXT, timestamp_ms INTEGER, latency_ms INTEGER,
                provider TEXT, model TEXT, failed INTEGER, canceled INTEGER, generate INTEGER,
                reasoning_tokens INTEGER, auth_type TEXT, reasoning_effort TEXT, response_model TEXT)""")

    def add(self, tokens, **changes):
        defaults = dict(event_key="fixture", timestamp_ms=self.begin+1000, latency_ms=50,
                        provider="codex", model="gpt-6-astra", failed=0, canceled=0, generate=1,
                        reasoning_tokens=tokens, auth_type="oauth", reasoning_effort="high", response_model="gpt-6-astra")
        defaults.update(changes)
        with closing(sqlite3.connect(self.db)) as c, c:
            c.execute("INSERT INTO usage_events VALUES ("+",".join("?" for _ in defaults)+")",list(defaults.values()))

    def report(self):
        return stats.summarize(self.db,self.since,self.until)

    def test_formula_denominators_and_default_window(self):
        for i,tokens in enumerate((0,1,515,516,517,518,1034,3106,3624)):
            self.add(tokens,timestamp_ms=self.begin+1000+i)
        result=self.report()["windows"]["retained_history"]["totals"]
        self.assertEqual(result["successful_generations"],9)
        self.assertEqual(result["positive_reasoning_records"],8)
        self.assertEqual(result["pattern_matches"],4)
        self.assertEqual(result["default_tier_window_matches"],3)
        self.assertEqual(result["percent_of_positive_reasoning"],"50.00")
        self.assertEqual(result["percent_of_all_successful_generations"],"44.44")

    def test_excludes_failures_cancellation_prewarm_and_invalid_usage(self):
        changes=[{"failed":1},{"canceled":1},{"generate":0},{"provider":"other"},
                 {"model":"other-model"},{"reasoning_tokens":None},{"reasoning_tokens":-2},
                 {"latency_ms":-1},{"reasoning_tokens":516.5}]
        for i,patch in enumerate(changes):self.add(516,timestamp_ms=self.begin+1000+i,**patch)
        self.add(516,timestamp_ms=self.begin+2000)
        result=self.report()["windows"]["retained_history"]["totals"]
        self.assertEqual(result["successful_generations"],1)
        self.assertEqual(result["pattern_matches"],1)

    def test_start_and_completion_boundaries_and_recent_window(self):
        self.add(516,timestamp_ms=self.begin,latency_ms=0)
        self.add(516,timestamp_ms=self.begin-1,latency_ms=100)
        self.add(516,timestamp_ms=self.end-50,latency_ms=50)
        self.add(1034,timestamp_ms=self.end-51,latency_ms=50)
        report=self.report()["windows"]
        self.assertEqual(report["retained_history"]["totals"]["pattern_matches"],2)
        self.assertEqual(report["last_30_days"]["totals"]["pattern_matches"],1)

    def test_shared_event_key_with_distinct_start_is_not_deduplicated(self):
        self.add(516,timestamp_ms=self.begin+1000)
        self.add(1034,timestamp_ms=self.begin+2000)
        self.assertEqual(self.report()["windows"]["retained_history"]["totals"]["pattern_matches"],2)

    def test_duplicate_key_and_start_requires_review(self):
        self.add(516)
        self.add(516)
        with self.assertRaisesRegex(ValueError,"deduplication"):self.report()

    def test_empty_sample_has_no_invented_probability(self):
        self.assertIsNone(self.report()["windows"]["retained_history"]["totals"]["percent_of_positive_reasoning"])

    def test_zero_only_sample_is_separate(self):
        self.add(0)
        result=self.report()["windows"]["retained_history"]["totals"]
        self.assertIsNone(result["percent_of_positive_reasoning"])
        self.assertEqual(result["percent_of_all_successful_generations"],"0.00")

    def test_database_unchanged_and_no_identifiers_exported(self):
        self.add(516,event_key="private-fixture-identifier")
        before=hashlib.sha256(self.db.read_bytes()).hexdigest()
        result=self.report()
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(),before)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["raw_rows_exported"])
        self.assertNotIn("private-fixture-identifier",str(result))
        self.assertNotIn(str(self.db),str(result))

    def test_explicit_time_zone_required(self):
        with self.assertRaises(ValueError):stats.parse_time("2026-11-12T00:00:00")


if __name__ == "__main__":
    unittest.main()
