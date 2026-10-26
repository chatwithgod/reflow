"""Build and check the evaluation runner using synthetic credentials only."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "evaluations"))
from tasks import ORACLES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go", default="go")
    parser.add_argument("--proxy", type=Path, help="optional already-built Reflow binary")
    args = parser.parse_args()
    go = shutil.which(args.go)
    if not go:
        parser.error("Go executable not found")
    proxy = args.proxy.resolve(strict=True) if args.proxy else None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    report = ROOT / "build" / "evaluation-process" / stamp
    report.mkdir(parents=True, exist_ok=False)
    exe = ".exe" if os.name == "nt" else ""
    fixture = report / ("agent" + exe)
    (report / "oracles.json").write_text(json.dumps(ORACLES), encoding="utf-8")
    summary = {"live_account": False, "live_model": False, "production_modified": False,
               "status": "running", "steps": []}
    keep = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PROGRAMDATA",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    env.update(GOTOOLCHAIN="local", GOENV="off", GOWORK="off", CGO_ENABLED="0",
               GOPATH=str(ROOT / ".tools" / "gopath"),
               GOMODCACHE=str(ROOT / ".tools" / "gopath" / "pkg" / "mod"),
               GOCACHE=str(ROOT / ".tools" / "gocache"),
               NO_PROXY="127.0.0.1,localhost")
    log = report / "output.log"

    def run(label, command):
        summary["steps"].append({"name": label})
        with log.open("a", encoding="utf-8") as output:
            result = subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.STDOUT)
        summary["steps"][-1]["exit_code"] = result.returncode
        if result.returncode:
            raise subprocess.CalledProcessError(result.returncode, command)

    code = 0
    try:
        with tempfile.TemporaryDirectory(prefix="profile-", dir=report) as temporary:
            home = Path(temporary)
            for key, sub in {"HOME": "", "USERPROFILE": "", "APPDATA": "appdata",
                             "LOCALAPPDATA": "localappdata", "TEMP": "temp", "TMP": "temp",
                             "CODEX_HOME": "codex-home"}.items():
                directory = home / sub
                directory.mkdir(parents=True, exist_ok=True)
                env[key] = str(directory)
            if proxy is None:
                proxy = report / ("reflow" + exe)
                run("build_proxy", [go, "build", "-trimpath", "-o", str(proxy), "./cmd/reflow"])
            run("build_synthetic_agent", [go, "build", "-trimpath", "-o", str(fixture),
                                          "./evaluations/testfixture/agent.go"])
            env.update(REFLOW_EVAL_FAKE_CODEX=str(fixture), REFLOW_EVAL_REFLOW_BIN=str(proxy))
            run("runner_process_tests", [sys.executable, "-W", "error::ResourceWarning", "-m", "unittest",
                                         "discover", "-s", "evaluations", "-p", "test_runner.py", "-v"])
            output = log.read_text(encoding="utf-8")
            count = re.search(r"Ran (\d+) tests? in", output)
            if not count or int(count.group(1)) < 4 or "skipped=" in output:
                raise RuntimeError("evaluation process tests did not all run")
            summary["process_tests_passed"] = int(count.group(1))
            run("grader_self_test", [sys.executable, "evaluations/run.py", "--self-test"])
            summary.update(status="pass", proxy_sha256=hashlib.sha256(proxy.read_bytes()).hexdigest())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        code = 1
        summary.update(status="fail", error_type=type(error).__name__)
    (report / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Synthetic evaluation check {summary['status']}: {report}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
