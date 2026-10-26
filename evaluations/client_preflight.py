"""Fixed local client checks; no account access, model calls or saved RPC text."""
import base64
import json
from pathlib import Path
import queue
import subprocess
import threading
import time


def code_mode_host_probe(codex, env, spawn_options, stop):
    suffix = ".exe" if codex.suffix.lower() == ".exe" else ""
    host = codex.with_name("codex-code-mode-host" + suffix)
    result = {"code_mode_host_present": host.is_file(), "code_mode_host_launchable": False}
    if not result["code_mode_host_present"]:
        return result
    process = None
    try:
        process = subprocess.Popen([str(host), "--help"], cwd=env["CODEX_HOME"], env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, **spawn_options())
        process.wait(timeout=10)
        result["code_mode_host_launchable"] = process.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        stop(process)
    return result


def filesystem_probe(codex, profile, work, env, spawn_options, stop):
    """Exercise the filesystem RPC used by apply_patch, with explicit MXC policy.

    Also try one write outside the allowed workspace but inside the temporary
    profile. A successful RPC alone cannot pass the probe: inspect both files.
    """
    process = None
    readers = []
    output = {"native_filesystem_write_verified": False, "out_of_workspace_write_blocked": False,
              "native_filesystem_reason": "filesystem_probe_failed"}
    messages = queue.Queue(maxsize=16)
    protocol_error = threading.Event()
    marker = b"REFLOW_NATIVE_PREFLIGHT_OK\n"
    target, blocked = work / "native-probe.txt", profile / "blocked-probe.txt"
    system_root = next((Path(value) for name, value in env.items() if name.upper() == "SYSTEMROOT"), None)
    if system_root is None or not system_root.is_absolute():
        output["native_filesystem_reason"] = "host_systemroot_unavailable"
        return output
    roots = sorted({work.anchor, codex.anchor, system_root.anchor})
    entries = [{"path": {"type": "path", "path": Path(root).as_uri()}, "access": "read"} for root in roots]
    entries.append({"path": {"type": "path", "path": work.as_uri()}, "access": "write"})
    sandbox = {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": entries},
                               "network": "restricted"},
               "cwd": work.as_uri(), "workspaceRoots": [work.as_uri()], "userHomeDir": profile.as_uri(),
               "windowsSandboxLevel": "mxc"}
    try:
        process = subprocess.Popen([str(codex), "exec-server", "--listen", "stdio", "--concurrent-requests", "1"],
                                   cwd=work, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, **spawn_options())

        def consume():
            while True:
                line = process.stdout.readline(1 << 20)
                if not line:
                    break
                if len(line) >= 1 << 20:
                    protocol_error.set()
                    break
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                try:
                    messages.put_nowait(message)
                except queue.Full:
                    protocol_error.set()
                    break
            try:
                messages.put_nowait(None)
            except queue.Full:
                pass

        reader = threading.Thread(target=consume, daemon=True)
        readers.append(reader)
        reader.start()
        deadline = time.monotonic() + 20

        def send(message):
            process.stdin.write(json.dumps(message).encode() + b"\n")
            process.stdin.flush()

        def receive(request_id):
            while time.monotonic() < deadline and not protocol_error.is_set():
                message = messages.get(timeout=max(0.001, deadline - time.monotonic()))
                if message is None:
                    raise RuntimeError("client_closed")
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message
            raise RuntimeError("client_protocol_error")

        def write_request(request_id, path):
            send({"id": request_id, "method": "fs/writeFile", "params": {
                "path": path.as_uri(), "dataBase64": base64.b64encode(marker).decode(), "sandbox": sandbox}})
            return receive(request_id)

        send({"id": 1, "method": "initialize", "params": {"clientName": "reflow-execution-preflight"}})
        if "error" in receive(1):
            return output
        send({"method": "initialized", "params": None})
        response = write_request(2, target)
        if "error" in response:
            error = response.get("error")
            message = error.get("message", "") if isinstance(error, dict) else ""
            if isinstance(message, str) and "SYSTEMROOT" in message and "missing" in message.lower():
                output["native_filesystem_reason"] = "missing_systemroot"
            return output
        output["native_filesystem_write_verified"] = target.exists() and target.read_bytes() == marker
        if not output["native_filesystem_write_verified"]:
            return output
        response = write_request(3, blocked)
        output["out_of_workspace_write_blocked"] = "error" in response and not blocked.exists()
        output["native_filesystem_reason"] = "pass" if output["out_of_workspace_write_blocked"] else "write_boundary_failed"
        return output
    except (OSError, RuntimeError, queue.Empty, subprocess.TimeoutExpired):
        return output
    finally:
        if process is not None:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                stop(process)
            for reader in readers:
                reader.join(timeout=3)
            if process.stdout is not None:
                process.stdout.close()
