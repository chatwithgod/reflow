"""Check the scheduling grader and its independent finite-time oracle."""
import itertools
from pathlib import Path
import tempfile
import unittest

import run as evaluation
from scheduler_task import DEFECTS, ORACLE, STARTER, SKELETON, PROMPT, SKELETON_PROMPT, grid_oracle, job
import workspace_fixture


class SchedulerGraderTests(unittest.TestCase):
    def grade(self, source):
        with tempfile.TemporaryDirectory(prefix="reflow-scheduler-grader-") as temporary:
            path = Path(temporary) / "solution.py"
            path.write_text(source, encoding="utf-8")
            return evaluation.grade("scheduler", path)

    def test_reference_start_and_each_independent_fault_are_distinguished(self):
        self.assertEqual(self.grade(ORACLE), {"status": "scored", "total": 18, "passed": 18, "failed": []})
        self.assertEqual(self.grade(STARTER)["passed"], 15)
        for name, (before, after) in DEFECTS.items():
            with self.subTest(defect=name):
                self.assertEqual(ORACLE.count(before), 1)
                grade = self.grade(ORACLE.replace(before, after))
                self.assertEqual(grade["status"], "scored")
                self.assertGreaterEqual(grade["passed"], 0)
                self.assertLess(grade["passed"], 18)

    def test_skeleton_has_no_solution_and_preserves_full_specification(self):
        result = self.grade(SKELETON)
        self.assertEqual((result["total"], result["passed"]), (18, 0))
        original_spec = PROMPT.split("\n\n", 1)[1].replace("After repairing,", "After implementing,")
        self.assertEqual(SKELETON_PROMPT.split("\n\n", 1)[1], original_spec)

    def test_grid_oracle_matches_direct_start_time_enumeration(self):
        for tasks, slots, memory in [
            ({"a": job(2), "b": job(1), "c": job(2, needs=["a"])}, 2, 2),
            ({"a": job(1), "z": job(1), "b": job(2, needs=["a"])}, 2, 2),
            ({"a": job(2, 2), "b": job(3, 1), "c": job(1, 1)}, 2, 2),
            ({"a": job(1, needs=["z"]), "z": job(2), "b": job(1)}, 1, 2),
        ]:
            names = sorted(tasks)
            horizon = sum(tasks[name]["duration"] for name in names)
            best = None
            for starts in itertools.product(*(range(horizon - tasks[name]["duration"] + 1) for name in names)):
                times = {name: (start, start + tasks[name]["duration"]) for name, start in zip(names, starts)}
                if any(times[dependency][1] > times[name][0] for name in names for dependency in tasks[name]["needs"]):
                    continue
                if any(sum(times[name][0] <= t < times[name][1] for name in names) > slots or
                       sum(tasks[name]["memory"] for name in names if times[name][0] <= t < times[name][1]) > memory
                       for t in range(horizon)):
                    continue
                entries = tuple(sorted((times[name][0], name, times[name][1]) for name in names))
                candidate = (max(end for start, name, end in entries), entries)
                if best is None or candidate < best:
                    best = candidate
            self.assertIsNotNone(best)
            self.assertEqual(grid_oracle(tasks, slots, memory), [(name, start, end) for start, name, end in best[1]])

    def test_scheduler_checker_is_separate_and_immutable(self):
        with tempfile.TemporaryDirectory(prefix="reflow-scheduler-checker-") as temporary:
            work = Path(temporary)
            digest = workspace_fixture.prepare(work, "scheduler")
            self.assertIn("schedule_builds", (work / workspace_fixture.FILENAME).read_text(encoding="utf-8"))
            self.assertTrue(workspace_fixture.unchanged(work, digest))
            with self.assertRaises(ValueError):
                workspace_fixture.prepare(work, "unknown")
