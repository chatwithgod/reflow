import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from package_candidate import create_archive, sanitize_report, validate_metadata


class CandidateTests(unittest.TestCase):
    def test_identity_and_local_version(self):
        meta = {"Name": "codexreflow", "Version": "0.1.0-dev.5", "GitHubRepository": "local://codexreflow"}
        validate_metadata(meta, meta["Version"])
        for changed, version in [({**meta, "Name": "codexcomp"}, meta["Version"]),
                                 ({**meta, "GitHubRepository": "https://github.com/fixture/repo"}, meta["Version"]),
                                 (meta, "0.1.0"), (meta, "../escape-dev.5"), (meta, "0.1.0-dev.6")]:
            with self.assertRaises(ValueError):
                validate_metadata(changed, version)

    def test_report_hash_failures_privacy(self):
        digest = "a" * 64
        report = {"test_kind": "offline C ABI mock host; not live CPA/WebSocket", "plugin_sha256": digest,
                  "cases": [{"passed": True, "body": "private-fixture"}], "local_path": "private-path"}
        safe = sanitize_report(report, digest, "b" * 64)
        self.assertEqual(safe["case_executions"], 1)
        self.assertNotIn("private", json.dumps(safe))
        for bad in [{**report, "plugin_sha256": "c" * 64}, {**report, "cases": []},
                    {**report, "cases": [{"passed": False, "answer_preserved": True}]}]:
            with self.assertRaises(ValueError):
                sanitize_report(bad, digest, "b" * 64)

    def test_isolated_not_live_or_negative_control(self):
        report = {"test_kind": "real isolated CPA + strict synthetic WS incremental folds; not live-model acceptance",
                  "plugin_sha256": "a" * 64, "cases": [{"passed": True}], "cpa_version": "8.0.16",
                  "production_config_modified": False, "billable_model_calls": 0}
        sanitize_report(report, "a" * 64, "b" * 64)
        for key, value in [("production_config_modified", True), ("billable_model_calls", 1), ("expected_old_bypass", True), ("cpa_version", "latest")]:
            with self.assertRaises(ValueError):
                sanitize_report({**report, key: value}, "a" * 64, "b" * 64)

    def test_archive_whitelist_hashes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["LICENSE", "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_LICENSES.txt", "docs/LOCAL-CANDIDATE.md", "docs/DIAGNOSTICS.md", "scripts/summarize_diagnostics.py"]:
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"synthetic fixture")
            (root / "secret-config.yaml").write_text("not for packaging")
            evidence = [{"kind": "native_abi"}, {"kind": "isolated_incremental"}]
            archive = create_archive(root, "0.1.0-dev.5", b"synthetic DLL fixture", evidence)
            with zipfile.ZipFile(archive) as z:
                self.assertNotIn("secret-config.yaml", z.namelist())
                manifest = json.loads(z.read("manifest.json"))
                self.assertTrue(manifest["local_candidate"])
                self.assertFalse(manifest["installed_by_packager"])
                for name, digest in manifest["files"].items():
                    self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), digest)
            with self.assertRaises(FileExistsError):
                create_archive(root, "0.1.0-dev.5", b"different", evidence)
            with self.assertRaises(ValueError):
                create_archive(root, "0.1.0-dev.6", b"data", [{"kind": "native_abi"}])

    def test_schema_report_is_pinned_and_not_a_negative_control(self):
        report = {"test_kind": "real isolated CPA + strict synthetic collaboration schemas; not live-model acceptance",
                  "plugin_sha256": "a" * 64, "cases": [{"passed": True}], "cpa_version": "8.0.47",
                  "production_config_modified": False, "billable_model_calls": 0}
        safe = sanitize_report(report, "a" * 64, "b" * 64)
        self.assertEqual(safe["kind"], "isolated_tool_schema")
        for bad in [{**report, "cpa_version": "8.0.53"}, {**report, "expected_old_defect": True},
                    {**report, "cases": [{"passed": True, "expected_old_defect": True}]}]:
            with self.assertRaises(ValueError):
                sanitize_report(bad, "a" * 64, "b" * 64)


if __name__ == "__main__":
    unittest.main()
