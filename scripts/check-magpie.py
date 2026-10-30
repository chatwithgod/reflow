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
module_source = parser.add_mutually_exclusive_group()
module_source.add_argument("--workspace", type=Path)
module_source.add_argument("--modfile", type=Path, help="alternate .mod file inside --magpie; relative paths start there")
parser.add_argument("--packages", nargs="+", default=["./..."])
parser.add_argument("--run")
parser.add_argument("--race", action="store_true", help="run the selected test suite with Go's race detector")
parser.add_argument("--serial", action="store_true", help="run one Go package and one parallel test at a time")
parser.add_argument("--compiler", type=Path, help="C compiler for race checks, if not available on PATH")
args = parser.parse_args()
if args.race and args.phase != "suite":
    parser.error("--race requires --phase suite")
project = Path(__file__).resolve().parent.parent
host = args.magpie.resolve(strict=True)
go = args.go.resolve(strict=True)
modfile = None
module_inputs = {}
if args.modfile:
    modfile = (args.modfile if args.modfile.is_absolute() else host / args.modfile).resolve(strict=True)
    if modfile.suffix != ".mod" or not modfile.is_relative_to(host):
        parser.error("--modfile must be a .mod file inside --magpie")
    for path in (host / "go.mod", host / "go.sum", modfile, modfile.with_suffix(".sum")):
        module_inputs[path.relative_to(host).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
report = project / "build" / "magpie-verification" / stamp
report.mkdir(parents=True, exist_ok=False)
command = [str(go), args.phase if args.phase != "suite" else "test"]
if modfile:
    command += ["-modfile=" + str(modfile), "-mod=readonly"]
if args.tags:
    command += ["-tags", args.tags]
if args.serial:
    command += ["-p=1"]
if args.phase == "suite":
    if args.race:
        command += ["-race"]
    command += ["-json", "-count=1", "-timeout=45m"]
    if args.serial:
        command += ["-parallel=1"]
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
if modfile:
    after = {name: hashlib.sha256((host / name).read_bytes()).hexdigest() for name in module_inputs}
    summary.update(modfile=modfile.relative_to(host).as_posix(), module_files_before=module_inputs,
                   module_files_after=after, module_lockfiles_unchanged=module_inputs == after)
    if module_inputs != after:
        summary.update(command_exit_code=result.returncode, exit_code=result.returncode or 1,
                       validation_error="module_lockfiles_changed")
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
raise SystemExit(summary["exit_code"])
