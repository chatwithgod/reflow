"""Validate a native library and package one platform, without publishing.

Native registration and the same-library ABI report are mandatory. A CI package
is not a GitHub Release or full CPA/live-model acceptance. Versioned outputs are
immutable; assemble_release.py combines all five validated platform packages.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import struct
import sys
import zipfile

from native_smoke import OfflineHost

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
REPOSITORY_PATTERN = r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
PLATFORMS = (("darwin", "amd64"), ("darwin", "arm64"), ("linux", "amd64"), ("linux", "arm64"), ("windows", "amd64"))
LICENSE_FILES = ("LICENSE", "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_LICENSES.txt")
NATIVE_KIND = "offline C ABI mock host; not live CPA/WebSocket"
NATIVE_CASE_KEYS = frozenset(
    [(transport, scenario)
     for transport in ("sse", "json", "cpa-lines")
     for scenario in ("normal", "continuation", "tool", "cancelled", "eof", "failed", "upstream-incomplete")]
    + [(transport, "fragmented") for transport in ("sse", "json")]
    + [(transport, scenario) for transport in ("sse", "json", "cpa-lines") for scenario in ("auto-normal", "auto-516")]
    + [("", "diagnostic_startup_failure"), ("", "diagnostic_native_lifecycle_failure_and_reused_identifier")]
    + [("", scenario) for scenario in ("prewarm-native-route-empty-input", "prewarm-native-route-with-input",
                                      "empty-input-preserved-on-wire")]
    + [(transport, scenario) for transport in ("sse", "json", "cpa-lines")
       for scenario in ("schema-initial", "schema-continuation", "schema-additional", "schema-missing-original")]
)
NATIVE_CASES = len(NATIVE_CASE_KEYS)
MAX_LIBRARY_SIZE = 64 * 1024 * 1024


def library_name(goos, goarch):
    if (goos, goarch) not in PLATFORMS:
        raise ValueError("unsupported release platform")
    return "codexreflow" + {"windows": ".dll", "linux": ".so", "darwin": ".dylib"}[goos]


def archive_name(version, goos, goarch):
    library_name(goos, goarch)
    if not re.fullmatch(VERSION_PATTERN, version):
        raise ValueError("formal packages require a numeric MAJOR.MINOR.PATCH version")
    return f"codexreflow_{version}_{goos}_{goarch}.zip"


def host_platform(system=None, machine=None):
    system = sys.platform if system is None else system
    machine = platform.machine().lower() if machine is None else machine.lower()
    goos = {"win32": "windows", "linux": "linux", "darwin": "darwin"}.get(system)
    goarch = {"amd64": "amd64", "x86_64": "amd64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if (goos, goarch) not in PLATFORMS:
        raise ValueError("native validation requires a supported 64-bit host")
    return goos, goarch


def validate_windows_amd64_dll(raw):
    if len(raw) < 64 or raw[:2] != b"MZ":
        raise ValueError("release asset must be a Windows PE DLL")
    offset = struct.unpack_from("<I", raw, 60)[0]
    if offset + 24 > len(raw) or raw[offset:offset + 4] != b"PE\0\0":
        raise ValueError("invalid PE header")
    machine = struct.unpack_from("<H", raw, offset + 4)[0]
    characteristics = struct.unpack_from("<H", raw, offset + 22)[0]
    if machine != 0x8664 or not characteristics & 0x2000:
        raise ValueError("only Windows amd64 DLLs may use this release asset name")


def validate_library(raw, goos, goarch):
    library_name(goos, goarch)
    if not raw or len(raw) > MAX_LIBRARY_SIZE:
        raise ValueError("invalid or oversized library")
    if goos == "windows":
        validate_windows_amd64_dll(raw)
    elif goos == "linux":
        if len(raw) < 64 or raw[:7] != b"\x7fELF\x02\x01\x01":
            raise ValueError("expected a little-endian ELF64 shared library")
        kind, machine, version = struct.unpack_from("<HHI", raw, 16)
        if kind != 3 or version != 1 or machine != {"amd64": 62, "arm64": 183}[goarch]:
            raise ValueError("ELF type or architecture mismatch")
        if struct.unpack_from("<H", raw, 52)[0] != 64:
            raise ValueError("invalid ELF64 header size")
    else:
        if len(raw) < 32 or raw[:4] != b"\xcf\xfa\xed\xfe":
            raise ValueError("expected a thin little-endian Mach-O 64-bit dylib")
        cpu, _, kind, _, commands_size = struct.unpack_from("<IIIII", raw, 4)
        if cpu != {"amd64": 0x01000007, "arm64": 0x0100000C}[goarch] or kind != 6:
            raise ValueError("Mach-O type or architecture mismatch")
        if commands_size > len(raw) - 32:
            raise ValueError("truncated Mach-O load commands")


def validate_metadata(metadata, version, repository):
    if not isinstance(metadata, dict):
        raise ValueError("plugin metadata must be an object")
    if not re.fullmatch(VERSION_PATTERN, version):
        raise ValueError("formal releases require a numeric MAJOR.MINOR.PATCH version")
    if not re.fullmatch(REPOSITORY_PATTERN, repository) or "REPLACE_WITH" in repository or "/OWNER/" in repository:
        raise ValueError("confirm the actual GitHub repository before packaging")
    if metadata.get("Name") != "codexreflow":
        raise ValueError("DLL plugin ID is not codexreflow")
    if metadata.get("Version") != version:
        raise ValueError("DLL version does not match the release version (development builds are rejected)")
    if metadata.get("GitHubRepository") != repository:
        raise ValueError("DLL source repository does not match the release repository")


def validate_native_report(report, library_bytes, version):
    if not isinstance(report, dict):
        raise ValueError("native ABI report must be an object")
    if (report.get("test_kind") != NATIVE_KIND or report.get("plugin_version") != version or
            report.get("plugin_sha256") != hashlib.sha256(library_bytes).hexdigest()):
        raise ValueError("ABI report does not match this library/version/test kind")
    cases = report.get("cases")
    if not isinstance(cases, list) or len(cases) != NATIVE_CASES:
        raise ValueError("complete native ABI suite required")
    identities = []
    for case in cases:
        if (not isinstance(case, dict) or case.get("passed") is not True or
                not isinstance(case.get("scenario"), str) or
                not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", case["scenario"])):
            raise ValueError("invalid or unpassed native case")
        transport = case.get("transport_payload", "")
        if not isinstance(transport, str) or transport not in ("", "sse", "json", "cpa-lines"):
            raise ValueError("invalid native transport identity")
        identities.append((transport, case["scenario"]))
    if len(set(identities)) != len(identities) or set(identities) != NATIVE_CASE_KEYS:
        raise ValueError("native suite must contain exactly all transport/scenario identities")


def license_bytes(root):
    return {name: (root / name).read_bytes() for name in LICENSE_FILES}


def source_fingerprint(root):
    files = sorted(root.glob("*.go")) + [root / "go.mod", root / "go.sum"]
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_archive(raw, version, goos, goarch, licenses):
    target = library_name(goos, goarch)
    if len(raw) > MAX_LIBRARY_SIZE + 1024 * 1024:
        raise ValueError("oversized platform archive")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != 4 or set(names) != {target, *LICENSE_FILES}:
            raise ValueError("ZIP must contain exactly the root library and three license files")
        for member in archive.infolist():
            mode = (member.external_attr >> 16) & 0o170000
            if (member.is_dir() or member.file_size > MAX_LIBRARY_SIZE or
                    mode not in (0, 0o100000) or member.flag_bits & 1):
                raise ValueError("invalid ZIP member type, size or encryption")
            if member.filename in licenses and member.file_size != len(licenses[member.filename]):
                raise ValueError("ZIP license length differs from the source checkout")
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC failure")
        contents = {name: archive.read(name) for name in names}
    if any(contents[name] != licenses[name] for name in LICENSE_FILES):
        raise ValueError("ZIP licenses differ from the source checkout")
    validate_library(contents[target], goos, goarch)
    archive_name(version, goos, goarch)
    return contents


def create_archive(output, version, goos, goarch, raw, licenses):
    validate_library(raw, goos, goarch)
    name = archive_name(version, goos, goarch)
    if set(licenses) != set(LICENSE_FILES):
        raise ValueError("all retained license files are required")
    # Caller chooses a new output directory; never replace a previous version.
    output.mkdir(parents=True, exist_ok=False)
    archive = output / name
    contents = {library_name(goos, goarch): raw, **licenses}
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as stream:
        for name, data in contents.items():
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o100644 << 16
            stream.writestr(member, data)
    validate_archive(archive.read_bytes(), version, goos, goarch, licenses)
    with (output / "checksums.txt").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n")
    return archive


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--goos", choices=("windows", "linux", "darwin"), default="windows")
    parser.add_argument("--goarch", choices=("amd64", "arm64"), default="amd64")
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True, help="same-library native_smoke.py JSON report")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.version != (ROOT / "VERSION").read_text(encoding="utf-8").strip():
        raise ValueError("update VERSION deliberately before packaging a different release")
    if host_platform() != (args.goos, args.goarch):
        raise ValueError("native registration must run on the matching OS/architecture")
    raw = args.library.read_bytes()
    validate_library(raw, args.goos, args.goarch)
    validate_native_report(json.loads(args.report.read_bytes()), raw, args.version)
    host = OfflineHost(args.library)
    try:
        registration = host.call("plugin.register", {})
    finally:
        host.plugin.shutdown()
    validate_metadata(registration["metadata"], args.version, args.repository)
    if args.library.read_bytes() != raw:
        raise ValueError("library changed while validating registration")
    output = args.output_dir or ROOT / "dist" / args.version / f"{args.goos}_{args.goarch}"
    archive = create_archive(output, args.version, args.goos, args.goarch, raw, license_bytes(ROOT))
    registration = {key: registration["metadata"][key] for key in ("Name", "Version", "GitHubRepository")}
    with (output / "registration.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(registration, stream, indent=2)
        stream.write("\n")
    print(f"Packaged {archive}; no upload, Release, or store submission performed.")


if __name__ == "__main__":
    main()
