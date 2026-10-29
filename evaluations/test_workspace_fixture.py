"""The supplied check must reject broken code and remain immutable."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ledger_task import ORACLE, STARTER
import workspace_fixture


class WorkspaceFixtureTests(unittest.TestCase):
    def test_fixed_checker_accepts_reference_and_rejects_starter(self):
        with tempfile.TemporaryDirectory(prefix="reflow-workspace-check-") as temporary:
            work = Path(temporary)
            digest = workspace_fixture.prepare(work)
            for source, good in ((ORACLE, True), (STARTER, False)):
                (work / "solution.py").write_text(source, encoding="utf-8")
                process = subprocess.run([sys.executable, "-I", "-B", str(work / workspace_fixture.FILENAME)],
                    cwd=work, capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode == 0, good)
                if good:
                    self.assertEqual(json.loads(process.stdout), {"smoke_checks": 6, "passed": 6})
            self.assertTrue(workspace_fixture.unchanged(work, digest))

    def test_missing_or_edited_checker_cannot_pass_integrity_check(self):
        with tempfile.TemporaryDirectory(prefix="reflow-workspace-check-") as temporary:
            work = Path(temporary)
            digest = workspace_fixture.prepare(work)
            path = work / workspace_fixture.FILENAME
            path.write_text("print('fake pass')", encoding="utf-8")
            self.assertFalse(workspace_fixture.unchanged(work, digest))
            path.unlink()
            self.assertFalse(workspace_fixture.unchanged(work, digest))

    def test_reader_prints_only_supplied_files_without_modifying_them(self):
        with tempfile.TemporaryDirectory(prefix="reflow-workspace-reader-") as temporary:
            work = Path(temporary)
            (work / "solution.py").write_text("# SYNTHETIC_SOLUTION", encoding="utf-8")
            check_hash = workspace_fixture.prepare(work, "scheduler")
            read_hash = workspace_fixture.prepare_reader(work)
            process = subprocess.run([sys.executable, "-I", "-B", str(work / workspace_fixture.READ_FILENAME)],
                                     cwd=work, capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0)
            self.assertIn("# SYNTHETIC_SOLUTION", process.stdout)
            self.assertIn("schedule_builds", process.stdout)
            self.assertTrue(workspace_fixture.unchanged(work, check_hash))
            self.assertTrue(workspace_fixture.unchanged(work, read_hash, workspace_fixture.READ_FILENAME))
            (work / workspace_fixture.READ_FILENAME).write_text("# changed", encoding="utf-8")
            self.assertFalse(workspace_fixture.unchanged(work, read_hash, workspace_fixture.READ_FILENAME))
