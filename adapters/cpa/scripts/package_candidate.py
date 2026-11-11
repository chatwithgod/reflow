"""Package a LOCAL Windows development candidate, never a store release.

Does not download, install, enable a plugin, change configuration or publish.
Requires same-DLL passing native and isolated reports. Only sanitized evidence
counts/hashes are packaged; raw logs and test payloads are excluded.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

from native_smoke import OfflineHost
from package_release import validate_windows_amd64_dll

ROOT = Path(__file__).resolve().parents[1]
DEV_VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)-dev\.[1-9]\d*\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
KINDS = {
    "offline C ABI mock host; not live CPA/WebSocket": "native_abi",
    "real CPA process + loopback synthetic Codex upstream; no live provider or Desktop": "isolated_http_ws",
    "real isolated CPA + strict synthetic WS incremental folds; not live-model acceptance": "isolated_incremental",
    "real isolated CPA + strict synthetic WS cache; not live-model/Desktop acceptance": "isolated_bridge",
    "real isolated CPA + strict synthetic collaboration schemas; not live-model acceptance": "isolated_tool_schema",
}


def validate_metadata(metadata, version):
    if not DEV_VERSION.fullmatch(version):
        raise ValueError("local candidates require a numbered -dev.N version")
    if metadata.get("Name") != "codexreflow" or metadata.get("Version") != version:
        raise ValueError("candidate plugin identity/version mismatch")
    if metadata.get("GitHubRepository") != "local://codexreflow":
        raise ValueError("local candidate must not claim a published repository")


def sanitize_report(report, digest, report_hash):
    if not HASH.fullmatch(digest) or not HASH.fullmatch(report_hash) or report.get("plugin_sha256") != digest:
        raise ValueError("report belongs to a different DLL or hash is invalid")
    kind = KINDS.get(report.get("test_kind"))
    if kind is None:
        raise ValueError("unsupported evidence report kind")
    cases = report.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) > 10000:
        raise ValueError("evidence report has no bounded cases")
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("invalid case")
        if case.get("passed") is False or not (case.get("passed") is True or case.get("answer_preserved") is True):
            raise ValueError("evidence includes unpassed cases")
        if case.get("expected_old_defect") is True:
            raise ValueError("negative old-build cases are not candidate validation")
    result = {"kind": kind, "case_executions": len(cases), "report_sha256": report_hash}
    if kind != "native_abi":
        versions = ("8.0.47",) if kind == "isolated_tool_schema" else ("8.0.13", "8.0.15", "8.0.16")
        if report.get("cpa_version") not in versions or report.get("production_config_modified") is not False or report.get("billable_model_calls") != 0:
            raise ValueError("expected pinned isolated non-production evidence")
        if report.get("expected_old_bypass") is True or report.get("expected_old_defect") is True:
            raise ValueError("negative old-build controls are not candidate validation")
        result["cpa_version"] = report["cpa_version"]
    return result


def create_archive(root, version, library_bytes, evidence):
    if not DEV_VERSION.fullmatch(version):
        raise ValueError("invalid development version")
    if not any(r["kind"] == "native_abi" for r in evidence) or not any(r["kind"].startswith("isolated_") for r in evidence):
        raise ValueError("native and isolated evidence are both required")
    # Fixed filenames only: never traverse arbitrary project content or include
    # raw validation reports, local paths, configuration, prompts or accounts.
    files = {f"codexreflow-v{version}.dll": library_bytes}
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_LICENSES.txt", "docs/LOCAL-CANDIDATE.md", "docs/DIAGNOSTICS.md", "scripts/summarize_diagnostics.py"):
        files[name] = (root / name).read_bytes()
    manifest = {"schema": 1, "plugin": "codexreflow", "version": version, "local_candidate": True,
                "source": "local://codexreflow", "sdk_version": "8.0.13", "installed_by_packager": False,
                "live_model_acceptance": "pending", "usage_execution_join": "unavailable", "evidence": evidence,
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    dest = root / "dist" / f"{version}-local-candidate"
    dest.mkdir(parents=True, exist_ok=False)  # Immutable versioned output.
    archive = dest / f"codexreflow_{version}_windows_amd64_LOCAL-CANDIDATE.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as out:
        for name, data in files.items():
            out.writestr(name, data)
    with (dest / "checksums.txt").open("x", encoding="utf-8", newline="\n") as out:
        out.write(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n")
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--report", action="append", type=Path, required=True)
    args = parser.parse_args()
    raw = args.library.read_bytes()
    validate_windows_amd64_dll(raw)
    digest = hashlib.sha256(raw).hexdigest()
    host = OfflineHost(args.library)
    try:
        metadata = host.call("plugin.register", {})["metadata"]
    finally:
        host.plugin.shutdown()
    validate_metadata(metadata, args.version)
    # Guard against a file replacement between reading bytes and loading DLL.
    if hashlib.sha256(args.library.read_bytes()).hexdigest() != digest:
        raise ValueError("DLL changed while validating")
    evidence = []
    seen_reports = set()
    for path in args.report:
        report_bytes = path.read_bytes()
        report_hash = hashlib.sha256(report_bytes).hexdigest()
        if report_hash in seen_reports:
            raise ValueError("duplicate evidence report")
        seen_reports.add(report_hash)
        evidence.append(sanitize_report(json.loads(report_bytes), digest, report_hash))
    archive = create_archive(ROOT, args.version, raw, evidence)
    print(f"Local candidate: {archive}. Not installed or published; not a store release.")


if __name__ == "__main__":
    main()
