"""Build/test a native platform package in isolation, never install or publish."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from package_release import (NATIVE_CASES, archive_name, host_platform, library_name, license_bytes,
                             source_fingerprint, validate_archive, validate_native_report)

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/chatwithgod/cpa-plugin-codexreflow"


def run(*args, cwd=ROOT):
    print("Running:", " ".join(map(str, args)), flush=True)
    subprocess.run([str(x) for x in args], cwd=cwd, check=True)


def capture(*args):
    return subprocess.check_output(args, cwd=ROOT).decode("utf-8").strip()


def main():
    if not __debug__ or os.environ.get("PYTHONOPTIMIZE"):
        raise RuntimeError("assertions must be enabled for the native harness")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--goos", required=True)
    parser.add_argument("--goarch", required=True)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if host_platform() != (args.goos, args.goarch):
        raise ValueError("use a native runner of the requested OS/architecture")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    archive = archive_name(version, args.goos, args.goarch)
    if capture("git", "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("commit tracked changes before building provenance-linked packages")
    commit = capture("git", "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("expected source commit identity")
    if not re.search(r"github\.com/router-for-me/CLIProxyAPI/v8 v8\.0\.13\b", (ROOT / "go.mod").read_text()):
        raise ValueError("CPA SDK pin changed")
    config = json.loads(capture("go", "env", "-json", "GOOS", "GOARCH", "GOHOSTOS", "GOHOSTARCH", "CGO_ENABLED", "GOVERSION"))
    if (config["GOOS"], config["GOARCH"]) != (args.goos, args.goarch) or config["CGO_ENABLED"] != "1":
        raise ValueError("native Go target with CGO_ENABLED=1 required")
    if (config["GOHOSTOS"], config["GOHOSTARCH"]) != (args.goos, args.goarch) or config["GOVERSION"] != "go1.26.8":
        raise ValueError("pinned Go 1.26.8 native toolchain required")
    os.environ["GOTOOLCHAIN"] = "local"
    os.environ["GOWORK"] = "off"
    os.environ["GOTELEMETRY"] = "off"
    fingerprint = source_fingerprint(ROOT)
    build = (args.build_dir or ROOT / "build" / f"platform-{args.goos}-{args.goarch}").resolve()
    output = (args.output_dir or ROOT / "dist" / version / f"{args.goos}_{args.goarch}").resolve()
    if not build.is_relative_to(ROOT / "build") or not output.is_relative_to(ROOT / "dist"):
        raise ValueError("build and package outputs must stay in their ignored project directories")
    if output.exists():
        raise FileExistsError("immutable platform package output already exists")
    build.mkdir(parents=True, exist_ok=False)
    tools = ROOT / ".tools"
    tools.mkdir(exist_ok=True)
    library = build / library_name(args.goos, args.goarch)
    # Ignored build/ may contain older CPA source checkouts. Test only the root
    # Go module snapshot, not arbitrary ignored nested projects, on every OS.
    with tempfile.TemporaryDirectory(prefix="platform-source-", dir=tools) as temporary:
        snapshot = Path(temporary).resolve()
        if not snapshot.is_relative_to(tools.resolve()):
            raise ValueError("unexpected temporary source location")
        for path in list(ROOT.glob("*.go")) + [ROOT / "go.mod", ROOT / "go.sum"]:
            shutil.copyfile(path, snapshot / path.name)
        unformatted = subprocess.check_output(["gofmt", "-l", *map(str, snapshot.glob("*.go"))], cwd=snapshot)
        if unformatted:
            raise ValueError("Go source is not formatted")
        run("go", "test", "./...", "-count=1", cwd=snapshot)
        run("go", "test", "./...", "-race", "-count=1", cwd=snapshot)
        run("go", "vet", "./...", cwd=snapshot)
        run("go", "test", "-run", "^$", "-fuzz", "^FuzzDecoderChunkBoundaries$", "-fuzztime=15s", "-parallel=2", cwd=snapshot)
        run("go", "test", "-run", "^$", "-fuzz", "^FuzzRestoreCollaborationToolSchemas$", "-fuzztime=15s", "-parallel=2", cwd=snapshot)
        run("go", "build", "-trimpath", "-buildmode=c-shared", "-ldflags",
            f"-X main.pluginVersion={version} -X main.pluginRepository={REPOSITORY}", "-o", library, ".", cwd=snapshot)
    run(sys.executable, "-m", "unittest", "discover", "-s", "scripts", "-p", "test_*.py")
    native = build / "native-smoke.json"
    run(sys.executable, ROOT / "scripts/native_smoke.py", library, "--report", native)
    raw = library.read_bytes()
    validate_native_report(json.loads(native.read_bytes()), raw, version)
    run(sys.executable, ROOT / "scripts/package_release.py", "--version", version,
        "--repository", REPOSITORY, "--goos", args.goos, "--goarch", args.goarch,
        "--library", library, "--report", native, "--output-dir", output)
    contents = validate_archive((output / archive).read_bytes(), version, args.goos, args.goarch, license_bytes(ROOT))
    if contents[library.name] != raw:
        raise ValueError("ZIP library bytes differ from the tested build")
    # Write only the validated root library, never blindly extract ZIP paths.
    packaged = build / "packaged"
    packaged.mkdir(exist_ok=False)
    with (packaged / library.name).open("xb") as stream:
        stream.write(raw)
    packed_report = build / "packaged-native-smoke.json"
    run(sys.executable, ROOT / "scripts/native_smoke.py", packaged / library.name, "--report", packed_report)
    validate_native_report(json.loads(packed_report.read_bytes()), raw, version)
    if source_fingerprint(ROOT) != fingerprint:
        raise ValueError("root Go module changed during validation")
    if capture("git", "status", "--porcelain", "--untracked-files=no") or capture("git", "rev-parse", "HEAD") != commit:
        raise ValueError("source checkout changed during validation")
    reports = {}
    for path in (native, packed_report):
        shutil.copyfile(path, output / path.name)
        reports[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    evidence = {"schema_version": 1, "plugin": "codexreflow", "version": version, "repository": REPOSITORY,
                "goos": args.goos, "goarch": args.goarch, "source_commit": commit,
                "root_go_source_sha256": fingerprint, "sdk_version": "8.0.13", "go_version": config["GOVERSION"],
                "archive": archive, "archive_sha256": hashlib.sha256((output / archive).read_bytes()).hexdigest(),
                "library_sha256": hashlib.sha256(raw).hexdigest(), "reports": reports,
                "go_unit_race_vet_fuzz_passed": True, "python_tests_passed": True,
                "native_case_executions": NATIVE_CASES, "packaged_native_case_executions": NATIVE_CASES,
                "validation_scope": "offline native ABI; not full CPA integration or live models",
                "production_changes": False, "billable_model_calls": 0, "published": False}
    with (output / "validation.json").open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(evidence, stream, indent=2)
        stream.write("\n")
    if os.environ.get("GITHUB_ENV"):
        with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"PACKAGE_VERSION={version}\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
