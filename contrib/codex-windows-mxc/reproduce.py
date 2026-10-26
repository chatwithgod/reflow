"""Diagnose Codex's MXC filesystem-helper environment; never calls a model.

Uses private interfaces verified at openai/codex rust-v0.164.0. No credentials,
user config or permissions are copied. All writes target a temporary directory.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading


def stop(process):
    if process.poll() is None:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        process.wait(timeout=5)


def spawn(command, cwd, env):
    return subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)


def isolated_env(profile):
    keep = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "PROGRAMDATA"}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep}
    for key, name in {"CODEX_HOME": "codex-home", "HOME": "", "USERPROFILE": "",
                      "APPDATA": "appdata", "LOCALAPPDATA": "localappdata", "TEMP": "temp", "TMP": "temp"}.items():
        directory = profile / name
        directory.mkdir(parents=True, exist_ok=True)
        env[key] = str(directory)
    env["RUST_LOG"] = "error"
    return env


def run_rpc(codex, work, env, request):
    process = spawn([str(codex), "exec-server", "--listen", "stdio", "--concurrent-requests", "1"], work, env)
    messages, stderr = queue.Queue(), bytearray()

    def read_output():
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except ValueError:
                pass
        messages.put(None)

    def read_errors():
        for line in process.stderr:
            stderr.extend(line[:max(0, 4096 - len(stderr))])

    readers = [threading.Thread(target=read_output, daemon=True), threading.Thread(target=read_errors, daemon=True)]
    for reader in readers:
        reader.start()

    def send(message):
        process.stdin.write(json.dumps(message).encode() + b"\n")
        process.stdin.flush()

    def receive(request_id):
        for _ in range(10):
            message = messages.get(timeout=15)
            if message is None:
                raise RuntimeError("exec-server closed before responding")
            if message.get("id") == request_id:
                return message
        raise RuntimeError("too many unrelated responses")

    try:
        send({"id": 1, "method": "initialize", "params": {"clientName": "reflow-offline-fs-probe"}})
        initial = receive(1)
        if "error" in initial:
            return {"initialization_error": initial["error"]}
        send({"method": "initialized", "params": None})
        send({"id": 2, "method": "fs/writeFile", "params": request})
        return {"write_response": receive(2)}
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            stop(process)
        for reader in readers:
            reader.join(timeout=2)
        process.stdout.close()
        process.stderr.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("this reproduction requires Windows with native MXC support")
    codex, report = args.codex.resolve(strict=True), args.report_dir.resolve()
    report.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    with tempfile.TemporaryDirectory(prefix="mxc-repro-", dir=report) as temporary:
        profile = Path(temporary).resolve()
        if not profile.is_relative_to(report):
            raise RuntimeError("temporary directory escaped the report root")
        env = isolated_env(profile)
        version = subprocess.check_output([str(codex), "--version"], env=env, timeout=10).decode().strip()
        if version not in {"codex-cli 0.164.0", "codex-cli 0.164.0-alpha.11.1"}:
            raise RuntimeError("private interfaces have only been verified with CLI 0.164.0 and 0.164.0-alpha.11.1")
        work = profile / "workspace"
        work.mkdir()
        target = work / "probe.txt"
        marker = b"REFLOW_MXC_HELPER_OK\n"
        roots = sorted({work.anchor, codex.anchor, Path(os.environ["SystemRoot"]).anchor})
        entries = [{"path": {"type": "path", "path": Path(root).as_uri()}, "access": "read"} for root in roots]
        entries.append({"path": {"type": "path", "path": work.as_uri()}, "access": "write"})
        permissions = {"type": "managed", "file_system": {"type": "restricted", "entries": entries}, "network": "restricted"}
        sandbox = {"permissions": permissions, "cwd": work.as_uri(), "workspaceRoots": [work.as_uri()],
                   "userHomeDir": profile.as_uri(), "windowsSandboxLevel": "mxc"}
        request = {"path": target.as_uri(), "dataBase64": base64.b64encode(marker).decode(), "sandbox": sandbox}
        rpc = run_rpc(codex, work, env, request)
        rpc["host_file_updated"] = target.exists() and target.read_bytes() == marker
        control_target = work / "control.txt"
        native_entries = [{"path": {"type": "path", "path": root}, "access": "read"} for root in roots]
        native_entries.append({"path": {"type": "path", "path": str(work)}, "access": "write"})
        payload = json.dumps({"permissions": {**permissions, "file_system": {"type": "restricted", "entries": native_entries}},
                              "sandbox_policy_cwd": str(work), "managed_network": None,
                              "command": [str(codex), "--codex-run-as-fs-helper"], "default_child_env": False},
                             ensure_ascii=True, separators=(",", ":"))
        if len(payload.encode()) >= 16384:
            raise RuntimeError("reproduction exceeds the single launcher transport chunk")
        cases = []
        for name, preserve, destination in (("without_systemroot", False, control_target),
                                             ("with_systemroot", True, control_target),
                                             ("with_systemroot_outside_write_root", True, profile / "denied.txt")):
            allowed = {"PATH", "TMPDIR", "TMP", "TEMP", "SYSTEMDRIVE", "LOCALAPPDATA"}
            if preserve:
                allowed.add("SYSTEMROOT")
            child_env = {key: value for key, value in env.items() if key.upper() in allowed}
            keys = sorted(key.upper() for key in child_env)
            child_env.update(CODEX_SANDBOX_LAUNCH_COUNT="1", CODEX_SANDBOX_LAUNCH_BYTES=str(len(payload.encode())),
                             CODEX_SANDBOX_LAUNCH_0=payload)
            helper_request = {"operation": "fs/writeFile", "params": {"path": destination.as_uri(),
                              "dataBase64": base64.b64encode(marker).decode(), "sandbox": None}}
            process = spawn([str(codex), "--__codex-windows-mxc"], Path(work.anchor), child_env)
            try:
                stdout, stderr = process.communicate(json.dumps(helper_request).encode() + b"\n", timeout=30)
            finally:
                stop(process)
            cases.append({"case": name, "child_environment_keys": keys, "exit_code": process.returncode,
                          "host_file_updated": destination.exists() and destination.read_bytes() == marker,
                          "stdout": stdout.decode("utf-8", "replace")[:4096], "stderr": stderr.decode("utf-8", "replace")[:4096]})
        error = rpc.get("write_response", {}).get("error", {}).get("message", "")
        reproduced = "SYSTEMROOT" in error and not rpc["host_file_updated"]
        controls_passed = (cases[0]["exit_code"] != 0 and not cases[0]["host_file_updated"] and
                           "SYSTEMROOT" in cases[0]["stderr"] and cases[1]["exit_code"] == 0 and cases[1]["host_file_updated"] and
                           not cases[2]["host_file_updated"] and json.loads(cases[2]["stdout"]).get("status") == "error")
        record = {"kind": "codex_mxc_missing_systemroot_reproduction", "client_version": version,
                  "client_sha256": hashlib.sha256(codex.read_bytes()).hexdigest(), "live_account": False, "model_calls": 0,
                  "max_concurrent_processes": 1, "sandbox_permissions_unchanged_between_controls": True,
                  "native_rpc_problem_reproduced": reproduced, "environment_controls_passed": controls_passed,
                  "native_patch_compatibility_accepted": False, "rpc": rpc, "controls": cases}
        encoded = json.dumps(record, indent=2).replace(str(profile).replace("\\", "\\\\"), "[temporary]")
        encoded = encoded.replace(profile.as_uri(), "file:///[temporary]")
        output = report / f"mxc-systemroot-{stamp}.json"
        output.write_text(encoded, encoding="utf-8")
        print(json.dumps({"report": str(output), "problem_reproduced": reproduced, "controls_passed": controls_passed, "model_calls": 0}))
        return 0 if reproduced and controls_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
