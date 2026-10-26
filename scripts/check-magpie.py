"""Run a Magpie development check in an isolated profile and keep its evidence."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--magpie", type=Path, required=True)
parser.add_argument("--go", type=Path, required=True)
parser.add_argument("--phase", choices=["suite", "vet", "build"], required=True)
parser.add_argument("--goos", choices=["windows", "linux", "darwin"])
parser.add_argument("--tags", default="nogui")
parser.add_argument("--workspace", type=Path)
parser.add_argument("--packages", nargs="+", default=["./..."])
parser.add_argument("--run")
parser.add_argument("--race", action="store_true", help="run the selected test suite with Go's race detector")
parser.add_argument("--compiler", type=Path, help="C compiler for race checks, if not available on PATH")
args = parser.parse_args()
if args.race and args.phase != "suite":
    parser.error("--race requires --phase suite")
project = Path(__file__).resolve().parent.parent
host = args.magpie.resolve(strict=True)
go = args.go.resolve(strict=True)
stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
report = project / "build" / "magpie-verification" / stamp
report.mkdir(parents=True, exist_ok=False)
command = [str(go), args.phase if args.phase != "suite" else "test"]
if args.tags:
    command += ["-tags", args.tags]
if args.phase == "suite":
    if args.race:
        command += ["-race"]
    command += ["-json", "-count=1", "-timeout=45m"]
    if args.run:
        command += ["-run", args.run]
    command += args.packages
elif args.phase == "vet":
    command += args.packages
else:
    command += ["-o", str(report / ("magpie.exe" if args.goos in (None, "windows") else "magpie")), "."]

env = {key: value for key, value in os.environ.items() if key.upper() in {
    "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PROGRAMDATA",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
}}
env.update({
    "GOPATH": str(project / ".tools" / "gopath"),
    "GOMODCACHE": str(project / ".tools" / "gopath" / "pkg" / "mod"),
    "GOCACHE": str(project / ".tools" / "magpie-gocache"),
    "GOTOOLCHAIN": "local", "GOENV": "off", "CGO_ENABLED": "1" if args.race else "0",
    "GOPROXY": "off",
    "GOWORK": str(args.workspace.resolve(strict=True)) if args.workspace else "off",
    "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.longpaths", "GIT_CONFIG_VALUE_0": "true",
})
if args.goos:
    env["GOOS"] = args.goos
if args.compiler:
    env["CC"] = str(args.compiler.resolve(strict=True))

head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=host, text=True).strip()
paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=host).split(b"\0")
digest = hashlib.sha256()
for raw in sorted(set(paths)):
    if not raw:
        continue
    path = host / os.fsdecode(raw)
    if path.is_file():
        digest.update(raw + b"\0" + hashlib.sha256(path.read_bytes()).digest())

print(f"Magpie {args.phase}: evidence -> {report}", flush=True)
temporary_root = Path(tempfile.gettempdir()).resolve()
with tempfile.TemporaryDirectory(prefix="rf-", dir=temporary_root) as profile:
    home = Path(profile).resolve()
    if not home.is_relative_to(temporary_root):
        raise RuntimeError("temporary profile escaped its report directory")
    for name, sub in {
        "HOME": "", "USERPROFILE": "",
        "APPDATA": "appdata", "LOCALAPPDATA": "localappdata",
        "XDG_CONFIG_HOME": "config", "XDG_CACHE_HOME": "cache",
        "XDG_DATA_HOME": "data", "TEMP": "temp", "TMP": "temp",
    }.items():
        directory = home / sub
        directory.mkdir(parents=True, exist_ok=True)
        env[name] = str(directory)
    with (report / "output.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=host, env=env, stdout=log, stderr=subprocess.STDOUT)

summary = {"phase": args.phase, "race": args.race, "command": command, "base_commit": head,
           "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "source_sha256": digest.hexdigest(), "exit_code": result.returncode,
           "goos": args.goos or "host", "live_account": False, "production_modified": False}
if args.phase == "suite":
    counts = {"pass": 0, "skip": 0, "fail": 0}
    failures = []
    for line in (report / "output.log").read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        action = event.get("Action")
        if event.get("Test") and action in counts:
            counts[action] += 1
        if action == "fail":
            failures.append({key: event[key] for key in ("Package", "Test") if key in event})
    summary.update(test_items=counts, failures=failures)
(report / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False), flush=True)
raise SystemExit(result.returncode)
