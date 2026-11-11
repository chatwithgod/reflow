"""Validate all five same-commit platform artifacts and collect ZIPs/checksums.

No library execution on foreign hosts, installation, Release or network write.
Per-platform native evidence is a trusted CI report, not a cryptographic attestation
or full CPA/live integration test. Missing or inconsistent targets fail closed.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from package_release import (NATIVE_CASES, PLATFORMS, archive_name, library_name, license_bytes,
                             source_fingerprint, validate_archive, validate_metadata,
                             validate_native_report)

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ("native-smoke.json", "packaged-native-smoke.json")


def validate_platform(directory, version, repository, commit, fingerprint, goos, goarch, licenses):
    name = archive_name(version, goos, goarch)
    required = {name, "checksums.txt", "registration.json", "validation.json", *REPORTS}
    if {path.name for path in directory.iterdir()} != required or any(path.is_symlink() or not path.is_file() for path in directory.iterdir()):
        raise ValueError("unexpected platform artifact members")
    raw = (directory / name).read_bytes()
    contents = validate_archive(raw, version, goos, goarch, licenses)
    library = contents[library_name(goos, goarch)]
    digest = hashlib.sha256(raw).hexdigest()
    if (directory / "checksums.txt").read_bytes() != f"{digest}  {name}\n".encode():
        raise ValueError("platform checksum contents mismatch")
    registration = json.loads((directory / "registration.json").read_bytes())
    validate_metadata(registration, version, repository)
    evidence = json.loads((directory / "validation.json").read_bytes())
    if not isinstance(evidence, dict):
        raise ValueError("platform validation record must be an object")
    expected = {"schema_version": 1, "plugin": "codexreflow", "version": version, "repository": repository,
                "goos": goos, "goarch": goarch, "source_commit": commit, "root_go_source_sha256": fingerprint,
                "sdk_version": "8.0.13", "go_version": "go1.26.8", "archive": name, "archive_sha256": digest,
                "library_sha256": hashlib.sha256(library).hexdigest(), "go_unit_race_vet_fuzz_passed": True,
                "python_tests_passed": True, "native_case_executions": NATIVE_CASES, "packaged_native_case_executions": NATIVE_CASES,
                "validation_scope": "offline native ABI; not full CPA integration or live models",
                "production_changes": False, "billable_model_calls": 0, "published": False}
    if any(type(evidence.get(key)) is not type(value) or evidence.get(key) != value for key, value in expected.items()):
        raise ValueError("platform provenance or validation state mismatch")
    if not isinstance(evidence.get("reports"), dict) or set(evidence["reports"]) != set(REPORTS):
        raise ValueError("two matching native ABI reports required")
    scenarios = []
    for report_name in REPORTS:
        report_bytes = (directory / report_name).read_bytes()
        if hashlib.sha256(report_bytes).hexdigest() != evidence["reports"][report_name]:
            raise ValueError("native report hash mismatch")
        report = json.loads(report_bytes)
        validate_native_report(report, library, version)
        scenarios.append([(case.get("transport_payload", ""), case["scenario"]) for case in report["cases"]])
    if scenarios[0] != scenarios[1]:
        raise ValueError("packaged native suite differs from the original suite")
    return raw, expected


def assemble(input_dir, output_dir, version, repository, commit, fingerprint, licenses):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("source commit identity required")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("source module fingerprint required")
    directories = {f"platform-{goos}-{goarch}": (goos, goarch) for goos, goarch in PLATFORMS}
    if {path.name for path in input_dir.iterdir()} != set(directories) or any(path.is_symlink() or not path.is_dir() for path in input_dir.iterdir()):
        raise ValueError("exactly five native platform artifact directories required")
    artifacts = {}
    evidence = []
    for directory, (goos, goarch) in directories.items():
        raw, record = validate_platform(input_dir / directory, version, repository, commit, fingerprint, goos, goarch, licenses)
        artifacts[archive_name(version, goos, goarch)] = raw
        evidence.append(record)
    # Validate everything before creating the immutable aggregate directory.
    output_dir.mkdir(parents=True, exist_ok=False)
    lines = []
    for name, raw in sorted(artifacts.items()):
        with (output_dir / name).open("xb") as stream:
            stream.write(raw)
        lines.append(f"{hashlib.sha256(raw).hexdigest()}  {name}\n")
    with (output_dir / "checksums.txt").open("x", encoding="utf-8", newline="\n") as stream:
        stream.writelines(lines)
    summary = {"schema_version": 1, "version": version, "repository": repository, "source_commit": commit,
               "root_go_source_sha256": fingerprint, "platforms": evidence,
               "native_case_executions": sum(record["native_case_executions"] for record in evidence),
               "packaged_native_case_executions": sum(record["packaged_native_case_executions"] for record in evidence),
               "validation_scope": "offline native ABI; not full CPA integration or live models",
               "production_changes": False, "billable_model_calls": 0, "published": False}
    with (output_dir / "validation-summary.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    result = assemble(args.input_dir, args.output_dir, version, args.repository, commit,
                      source_fingerprint(ROOT), license_bytes(ROOT))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
