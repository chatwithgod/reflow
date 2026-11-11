"""Synthetic container/provenance tests; not execution of foreign libraries."""

import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import warnings
import zipfile

from assemble_release import assemble, validate_platform
from package_release import (LICENSE_FILES, NATIVE_CASE_KEYS, NATIVE_CASES, NATIVE_KIND, PLATFORMS,
                             archive_name, create_archive, host_platform, library_name,
                             source_fingerprint, validate_archive, validate_library,
                             validate_metadata, validate_native_report)

VERSION = "0.1.1"
REPOSITORY = "https://github.com/fixture-user/cpa-plugin-codexreflow"
COMMIT = "a" * 40
FINGERPRINT = "b" * 64
LICENSES = {name: f"synthetic retained {name}\n".encode() for name in LICENSE_FILES}


def library_fixture(goos, goarch):
    raw = bytearray(256)
    if goos == "windows":
        raw[:2] = b"MZ"
        struct.pack_into("<I", raw, 60, 128)
        raw[128:132] = b"PE\0\0"
        struct.pack_into("<H", raw, 132, 0x8664)
        struct.pack_into("<H", raw, 150, 0x2000)
    elif goos == "linux":
        raw[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<HHI", raw, 16, 3, 62 if goarch == "amd64" else 183, 1)
        struct.pack_into("<H", raw, 52, 64)
    elif goos == "darwin":
        raw[:4] = b"\xcf\xfa\xed\xfe"
        struct.pack_into("<IIIII", raw, 4, 0x01000007 if goarch == "amd64" else 0x0100000C, 0, 6, 0, 0)
    return bytes(raw)


def native_fixture(raw):
    return {"test_kind": NATIVE_KIND, "plugin_version": VERSION,
            "plugin_sha256": hashlib.sha256(raw).hexdigest(),
            "cases": [{"scenario": scenario, "passed": True, **({"transport_payload": transport} if transport else {})}
                      for transport, scenario in sorted(NATIVE_CASE_KEYS)]}


def zip_fixture(contents, symlink=None):
    stream = io.BytesIO()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in contents:
                info = zipfile.ZipInfo(name)
                info.external_attr = (0o120777 if name == symlink else 0o100644) << 16
                archive.writestr(info, value)
    return stream.getvalue()


def write_platform(parent, goos, goarch):
    directory = parent / f"platform-{goos}-{goarch}"
    raw = library_fixture(goos, goarch)
    archive = create_archive(directory, VERSION, goos, goarch, raw, LICENSES)
    report_raw = (json.dumps(native_fixture(raw), indent=2) + "\n").encode()
    reports = {}
    for name in ("native-smoke.json", "packaged-native-smoke.json"):
        (directory / name).write_bytes(report_raw)
        reports[name] = hashlib.sha256(report_raw).hexdigest()
    (directory / "registration.json").write_text(json.dumps({"Name": "codexreflow", "Version": VERSION, "GitHubRepository": REPOSITORY}), encoding="utf-8")
    evidence = {"schema_version": 1, "plugin": "codexreflow", "version": VERSION, "repository": REPOSITORY,
                "goos": goos, "goarch": goarch, "source_commit": COMMIT, "root_go_source_sha256": FINGERPRINT,
                "sdk_version": "8.0.13", "go_version": "go1.26.8", "archive": archive.name,
                "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "library_sha256": hashlib.sha256(raw).hexdigest(), "reports": reports,
                "go_unit_race_vet_fuzz_passed": True, "python_tests_passed": True,
                "native_case_executions": NATIVE_CASES, "packaged_native_case_executions": NATIVE_CASES,
                "validation_scope": "offline native ABI; not full CPA integration or live models",
                "production_changes": False, "billable_model_calls": 0, "published": False}
    (directory / "validation.json").write_text(json.dumps(evidence), encoding="utf-8")
    return directory


class PlatformHeaderTests(unittest.TestCase):
    def test_five_target_headers(self):
        for goos, goarch in PLATFORMS:
            with self.subTest(target=(goos, goarch)):
                validate_library(library_fixture(goos, goarch), goos, goarch)

    def test_other_architecture_and_format_rejected(self):
        for goos, goarch in PLATFORMS:
            for other_os, other_arch in PLATFORMS:
                if (goos, goarch) != (other_os, other_arch):
                    with self.subTest(target=(goos, goarch), actual=(other_os, other_arch)), self.assertRaises(ValueError):
                        validate_library(library_fixture(other_os, other_arch), goos, goarch)

    def test_executable_and_bad_headers_rejected(self):
        elf = bytearray(library_fixture("linux", "amd64"))
        struct.pack_into("<H", elf, 16, 2)
        elf_endian = bytearray(library_fixture("linux", "amd64"))
        elf_endian[5] = 2
        elf_header = bytearray(library_fixture("linux", "amd64"))
        struct.pack_into("<H", elf_header, 52, 0)
        macho = bytearray(library_fixture("darwin", "arm64"))
        struct.pack_into("<I", macho, 12, 2)
        macho_commands = bytearray(library_fixture("darwin", "arm64"))
        struct.pack_into("<I", macho_commands, 20, 10000)
        for raw, goos, goarch in ((elf, "linux", "amd64"), (elf_endian, "linux", "amd64"),
                                  (elf_header, "linux", "amd64"), (macho, "darwin", "arm64"),
                                  (macho_commands, "darwin", "arm64"), (b"\xca\xfe\xba\xbe" + bytes(252), "darwin", "amd64")):
            with self.subTest(target=(goos, goarch)), self.assertRaises(ValueError):
                validate_library(raw, goos, goarch)

    def test_truncated_and_empty_library_rejected(self):
        for goos, goarch in PLATFORMS:
            for raw in (b"", b"not a library", library_fixture(goos, goarch)[:12]):
                with self.subTest(target=(goos, goarch), size=len(raw)), self.assertRaises(ValueError):
                    validate_library(raw, goos, goarch)

    def test_native_host_aliases(self):
        for system, machine, expected in (("win32", "AMD64", ("windows", "amd64")),
                                         ("linux", "aarch64", ("linux", "arm64")),
                                         ("darwin", "arm64", ("darwin", "arm64")),
                                         ("darwin", "x86_64", ("darwin", "amd64"))):
            self.assertEqual(host_platform(system, machine), expected)

    def test_unsupported_hosts_and_targets_rejected(self):
        for system, machine in (("freebsd", "amd64"), ("win32", "arm64"), ("linux", "riscv64")):
            with self.assertRaises(ValueError):
                host_platform(system, machine)
        for goos, goarch in (("windows", "arm64"), ("linux", "386"), ("../linux", "amd64")):
            with self.assertRaises(ValueError):
                library_name(goos, goarch)

    def test_archive_version_rejects_path_and_development(self):
        for version in ("../0.1.1", "v0.1.1", "0.1.1-dev", "01.1.1"):
            with self.assertRaises(ValueError):
                archive_name(version, "linux", "amd64")


class NativeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.raw = library_fixture("linux", "amd64")
        self.report = native_fixture(self.raw)

    def test_matching_complete_report(self):
        validate_native_report(self.report, self.raw, VERSION)

    def test_same_scenario_on_distinct_transports_is_valid(self):
        normals = [case for case in self.report["cases"] if case["scenario"] == "normal"]
        self.assertEqual({case["transport_payload"] for case in normals}, {"sse", "json", "cpa-lines"})
        validate_native_report(self.report, self.raw, VERSION)

    def test_unknown_or_repeated_transport_identity_rejected(self):
        for transport in ("unknown", [], "sse"):
            changed = copy.deepcopy(self.report)
            target = next(case for case in changed["cases"] if case.get("transport_payload") == "json" and case["scenario"] == "normal")
            target["transport_payload"] = transport
            with self.subTest(transport=transport), self.assertRaises(ValueError):
                validate_native_report(changed, self.raw, VERSION)

    def test_wrong_report_identity_rejected(self):
        for field, value in (("plugin_version", "0.1.0"), ("test_kind", "live acceptance"), ("plugin_sha256", "0" * 64)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_native_report({**self.report, field: value}, self.raw, VERSION)

    def test_missing_failed_duplicate_or_unsafe_cases_rejected(self):
        variants = [self.report["cases"][:-1], [], None]
        failed = copy.deepcopy(self.report["cases"])
        failed[0]["passed"] = False
        duplicate = copy.deepcopy(self.report["cases"])
        duplicate[0] = duplicate[1]
        unsafe = copy.deepcopy(self.report["cases"])
        unsafe[0]["scenario"] = "private payload / paths"
        variants.extend((failed, duplicate, unsafe))
        for cases in variants:
            with self.subTest(cases=type(cases)), self.assertRaises(ValueError):
                validate_native_report({**self.report, "cases": cases}, self.raw, VERSION)

    def test_boolean_success_not_integer(self):
        changed = copy.deepcopy(self.report)
        changed["cases"][0]["passed"] = 1
        with self.assertRaises(ValueError):
            validate_native_report(changed, self.raw, VERSION)

    def test_non_object_metadata_or_report_rejected(self):
        for value in (None, [], "not metadata"):
            with self.assertRaises(ValueError):
                validate_metadata(value, VERSION, REPOSITORY)
            with self.assertRaises(ValueError):
                validate_native_report(value, self.raw, VERSION)


class ArchiveTests(unittest.TestCase):
    def test_five_platform_root_layout_and_license_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for goos, goarch in PLATFORMS:
                raw = library_fixture(goos, goarch)
                archive = create_archive(root / f"{goos}-{goarch}", VERSION, goos, goarch, raw, LICENSES)
                contents = validate_archive(archive.read_bytes(), VERSION, goos, goarch, LICENSES)
                self.assertEqual(contents[library_name(goos, goarch)], raw)
                self.assertEqual({key: contents[key] for key in LICENSE_FILES}, LICENSES)
                checksum = archive.parent / "checksums.txt"
                self.assertEqual(checksum.read_bytes(), f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n".encode())

    def test_immutable_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "sealed"
            archive = create_archive(output, VERSION, "windows", "amd64", library_fixture("windows", "amd64"), LICENSES)
            before = archive.read_bytes()
            with self.assertRaises(FileExistsError):
                create_archive(output, VERSION, "windows", "amd64", library_fixture("windows", "amd64"), LICENSES)
            self.assertEqual(archive.read_bytes(), before)

    def test_zip_paths_duplicate_members_and_extra_library_rejected(self):
        raw = library_fixture("linux", "amd64")
        members = [("codexreflow.so", raw), *LICENSES.items()]
        variants = [[("../codexreflow.so", raw), *LICENSES.items()],
                    [("nested/codexreflow.so", raw), *LICENSES.items()],
                    [("/codexreflow.so", raw), *LICENSES.items()],
                    [*members, ("second.so", raw)],
                    [("codexreflow.so", raw), ("codexreflow.so", raw), ("LICENSE", b"x"), ("THIRD_PARTY_NOTICES.md", b"y")]]
        for contents in variants:
            with self.assertRaises(ValueError):
                validate_archive(zip_fixture(contents), VERSION, "linux", "amd64", LICENSES)

    def test_symlink_missing_and_changed_license_rejected(self):
        raw = library_fixture("darwin", "arm64")
        members = [("codexreflow.dylib", raw), *LICENSES.items()]
        bad = zip_fixture(members, symlink="codexreflow.dylib")
        with self.assertRaises(ValueError):
            validate_archive(bad, VERSION, "darwin", "arm64", LICENSES)
        for changed in (members[:-1], [("codexreflow.dylib", raw), *{**LICENSES, "LICENSE": b"wrong"}.items()]):
            with self.assertRaises(ValueError):
                validate_archive(zip_fixture(changed), VERSION, "darwin", "arm64", LICENSES)

    def test_zip_library_architecture_mismatch_rejected(self):
        members = [("codexreflow.so", library_fixture("linux", "arm64")), *LICENSES.items()]
        with self.assertRaises(ValueError):
            validate_archive(zip_fixture(members), VERSION, "linux", "amd64", LICENSES)

    def test_source_fingerprint_detects_go_or_module_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("main.go", "go.mod", "go.sum"):
                (root / name).write_bytes(name.encode())
            before = source_fingerprint(root)
            (root / "main.go").write_bytes(b"changed source")
            self.assertNotEqual(source_fingerprint(root), before)


class AggregateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.incoming = self.root / "incoming"
        self.incoming.mkdir()
        for goos, goarch in PLATFORMS:
            write_platform(self.incoming, goos, goarch)
        self.output = self.root / "bundle"

    def collect(self):
        return assemble(self.incoming, self.output, VERSION, REPOSITORY, COMMIT, FINGERPRINT, LICENSES)

    def test_five_package_bundle(self):
        summary = self.collect()
        self.assertEqual(len(summary["platforms"]), 5)
        self.assertFalse(summary["published"])
        self.assertEqual(summary["native_case_executions"], NATIVE_CASES * len(PLATFORMS))
        expected = {archive_name(VERSION, *target) for target in PLATFORMS}
        self.assertEqual({path.name for path in self.output.glob("*.zip")}, expected)
        lines = (self.output / "checksums.txt").read_text().splitlines()
        self.assertEqual(len(lines), 5)
        for line in lines:
            digest, name = line.split("  ")
            self.assertEqual(digest, hashlib.sha256((self.output / name).read_bytes()).hexdigest())

    def test_missing_or_extra_target_fails_before_output_creation(self):
        shutil.rmtree(self.incoming / "platform-linux-arm64")
        with self.assertRaises(ValueError):
            self.collect()
        self.assertFalse(self.output.exists())
        write_platform(self.incoming, "linux", "arm64")
        (self.incoming / "unexpected").mkdir()
        with self.assertRaises(ValueError):
            self.collect()
        self.assertFalse(self.output.exists())

    def test_mixed_commit_sdk_version_or_boolean_evidence_rejected(self):
        path = self.incoming / "platform-linux-amd64/validation.json"
        original = path.read_bytes()
        for field, value in (("source_commit", "c" * 40), ("version", "0.1.0"), ("sdk_version", "8.0.16"),
                              ("root_go_source_sha256", "d" * 64), ("go_version", "go1.26.9"),
                              ("go_unit_race_vet_fuzz_passed", 1), ("python_tests_passed", False), ("published", True)):
            record = json.loads(original)
            record[field] = value
            path.write_text(json.dumps(record), encoding="utf-8")
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.collect()
            self.assertFalse(self.output.exists())
        path.write_bytes(original)

    def test_changed_checksum_or_report_bytes_rejected(self):
        directory = self.incoming / "platform-windows-amd64"
        for name in ("checksums.txt", "native-smoke.json", "packaged-native-smoke.json"):
            path = directory / name
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.collect()
            path.write_bytes(original)

    def test_tampered_native_report_still_rejected_after_rehash(self):
        directory = self.incoming / "platform-darwin-arm64"
        report_path = directory / "packaged-native-smoke.json"
        report = json.loads(report_path.read_bytes())
        report["cases"][0]["passed"] = False
        report_path.write_text(json.dumps(report), encoding="utf-8")
        record_path = directory / "validation.json"
        record = json.loads(record_path.read_bytes())
        record["reports"][report_path.name] = hashlib.sha256(report_path.read_bytes()).hexdigest()
        record_path.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.collect()

    def test_extra_file_or_registration_mismatch_rejected(self):
        directory = self.incoming / "platform-linux-amd64"
        extra = directory / "raw-log.txt"
        extra.write_text("synthetic unapproved file", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.collect()
        extra.unlink()
        (directory / "registration.json").write_text(json.dumps({"Name": "codexcomp", "Version": VERSION, "GitHubRepository": REPOSITORY}), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.collect()

    def test_aggregate_output_never_overwrites(self):
        self.collect()
        before = (self.output / "checksums.txt").read_bytes()
        with self.assertRaises(FileExistsError):
            self.collect()
        self.assertEqual((self.output / "checksums.txt").read_bytes(), before)

    def test_invalid_source_identifiers_rejected(self):
        for commit, fingerprint in (("not a commit", FINGERPRINT), (COMMIT, "not a hash")):
            with self.assertRaises(ValueError):
                assemble(self.incoming, self.output, VERSION, REPOSITORY, commit, fingerprint, LICENSES)


if __name__ == "__main__":
    unittest.main()
