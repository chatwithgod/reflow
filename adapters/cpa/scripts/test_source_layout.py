import tempfile
import unittest
from pathlib import Path

from package_release import source_fingerprint
from source_layout import snapshot_source, source_files


class SharedSourceTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        adapter = root / "adapters/cpa"
        adapter.mkdir(parents=True)
        (root / "core").mkdir()
        (root / "go.mod").write_text("module github.com/chatwithgod/reflow\n", encoding="utf-8")
        (root / "go.sum").write_text("root sum", encoding="utf-8")
        (root / "core/fold.go").write_text("package core\n", encoding="utf-8")
        (adapter / "go.mod").write_text("module example/cpa\nreplace github.com/chatwithgod/reflow => ../..\n", encoding="utf-8")
        (adapter / "go.sum").write_text("adapter sum", encoding="utf-8")
        (adapter / "main.go").write_text("package main\n", encoding="utf-8")
        return root, adapter

    def test_shared_core_and_both_module_files_change_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root, adapter = self.fixture(directory)
            for path in (root / "core/fold.go", root / "go.mod", root / "go.sum", adapter / "main.go", adapter / "go.mod", adapter / "go.sum"):
                before = source_fingerprint(adapter)
                with path.open("a", encoding="utf-8") as stream:
                    stream.write("\n// changed\n")
                self.assertNotEqual(source_fingerprint(adapter), before, path.name)

    def test_snapshot_keeps_relative_core_dependency_and_excludes_outputs(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as output:
            root, adapter = self.fixture(directory)
            (adapter / "build").mkdir()
            (adapter / "build/private.json").write_text("must not ship", encoding="utf-8")
            (root / "unrelated.go").write_text("must not ship", encoding="utf-8")
            snapshot = snapshot_source(adapter, Path(output))
            self.assertEqual(snapshot, Path(output) / "adapters/cpa")
            self.assertEqual((snapshot / "../../core/fold.go").resolve().read_bytes(), (root / "core/fold.go").read_bytes())
            self.assertEqual(source_fingerprint(snapshot), source_fingerprint(adapter))
            self.assertFalse((snapshot / "build").exists())
            self.assertFalse((Path(output) / "unrelated.go").exists())
            with self.assertRaises(FileExistsError):
                snapshot_source(adapter, Path(output))

    def test_missing_core_rejects_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root, adapter = self.fixture(directory)
            (root / "core/fold.go").unlink()
            with self.assertRaises(ValueError):
                source_files(adapter)

    def test_wrong_root_module_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, adapter = self.fixture(directory)
            (root / "go.mod").write_text("module another/project\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                source_files(adapter)


if __name__ == "__main__":
    unittest.main()
