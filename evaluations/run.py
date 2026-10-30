"""Plan paired trials by default. Live execution requires explicit arguments."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import random
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from tasks import ORACLES, STARTERS
from ledger_task import PROMPT as LEDGER_PROMPT
from scheduler_task import PROMPT as SCHEDULER_PROMPT
from scheduler_task import SKELETON as SCHEDULER_SKELETON, SKELETON_PROMPT as SCHEDULER_SKELETON_PROMPT
from event_diagnostics import EventDiagnostics
import workspace_fixture
import fold_diagnostics
import acceptance
from client_preflight import code_mode_host_probe, filesystem_probe

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grade(task, path):
    env = {k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
        env[key] = str(path.resolve().parent)
    try:
        process = subprocess.Popen([sys.executable, "-I", str(HERE / "score.py"), "--task", task,
                                    "--solution", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   stdin=subprocess.DEVNULL, text=True, cwd=path.resolve().parent, env=env,
                                   **spawn_options())
        stdout, _ = process.communicate(timeout=10)
        return json.loads(stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        stop(process)
        process.communicate()
        return {"status": "score_timeout", "passed": 0}
    except (ValueError, IndexError):
        return {"status": "score_error", "passed": 0}


def stop(process):
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def spawn_options():
    return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}


def trial_env(profile):
    keep = {"PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "PROGRAMDATA",
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}
    env = {k: v for k, v in os.environ.items() if k.upper() in keep}
    for name, relative in {"HOME": "", "USERPROFILE": "", "APPDATA": "appdata",
                           "LOCALAPPDATA": "localappdata", "TEMP": "temp", "TMP": "temp",
                           "CODEX_HOME": "codex-home"}.items():
        directory = profile / relative
        directory.mkdir(parents=True, exist_ok=True)
        env[name] = str(directory)
    env.update(NO_PROXY="127.0.0.1,localhost", RUST_LOG="error")
    return env


def execution_preflight(codex, report):
    """Check workspace writes before copying auth or making any model request."""
    if os.name != "nt":
        return {"kind": "windows_mxc", "status": "not_applicable", "model_calls": 0}
    with tempfile.TemporaryDirectory(prefix="preflight-", dir=report) as temporary:
        profile = Path(temporary).resolve()
        if not profile.is_relative_to(report.resolve()):
            raise RuntimeError("preflight directory escaped its report directory")
        env = trial_env(profile)
        work = profile / "workspace"
        work.mkdir()
        host = code_mode_host_probe(codex, env, spawn_options, stop)
        if not host["code_mode_host_launchable"]:
            return {"kind": "windows_mxc", "status": "fail", "reason": "code_mode_host_unavailable", **host,
                    "workspace_write_verified": False, "model_calls": 0}
        process = subprocess.Popen(
            [str(codex), "-c", 'windows.sandbox="mxc"', "sandbox", "--include-managed-config",
             "--permission-profile", ":workspace", "-C", str(work), "--", "cmd.exe", "/d", "/c",
             "echo REFLOW_SANDBOX_OK>probe.txt"],
            cwd=work, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, **spawn_options())
        timed_out = False
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            stop(process)
        probe = work / "probe.txt"
        written = probe.exists() and probe.read_text().strip() == "REFLOW_SANDBOX_OK"
        result = {"kind": "windows_mxc", "status": "fail", **host, "command_write_verified": written,
                  "workspace_write_verified": False, "exit_code": process.returncode,
                  "timed_out": timed_out, "model_calls": 0}
        if process.returncode != 0 or not written:
            result["reason"] = "command_write_failed"
            return result
        native = filesystem_probe(codex, profile, work, env, spawn_options, stop)
        result.update(native)
        result["workspace_write_verified"] = native["native_filesystem_write_verified"] and native["out_of_workspace_write_blocked"]
        result["status"] = "pass" if result["workspace_write_verified"] else "fail"
        return result


def start_proxy(binary, maximum, env):
    process = subprocess.Popen([str(binary), "-listen", "127.0.0.1:0", "-max-continue", str(maximum),"-metrics"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env, **spawn_options())
    addresses = queue.Queue()

    def listen():
        for line in process.stderr:
            match = re.search(r" listening on ([^;]+);", line)
            if match:
                addresses.put("http://" + match.group(1))

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
    try:
        return process, addresses.get(timeout=10), thread
    except queue.Empty:
        stop(process)
        thread.join(timeout=5)
        process.stderr.close()
        raise RuntimeError("proxy_start_failed") from None


def read_metrics(endpoint, timeout=3):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(endpoint + "/metrics", timeout=timeout) as response:
            raw = json.loads(response.read(8192))
        if raw.get("enabled") is not True or raw.get("scope") != "streaming_responses":
            return None
        numbers = ("requests", "continuations", "warmups", "completed", "failed", "usage_reports",
                   "parse_errors", "unsupported_responses", "input_tokens", "output_tokens", "cached_tokens",
                   "cache_write_tokens", "reasoning_tokens")
        if any(type(raw.get(key)) is not int or raw[key] < 0 for key in numbers):
            return None
        tool_numbers = ("continued_tool_responses", "continued_tool_calls", "continued_tool_results", "tool_tracking_drops")
        tool_metrics = {key: raw[key] for key in tool_numbers} if all(type(raw.get(key)) is int and raw[key] >= 0 for key in tool_numbers) else {}
        return {**{key: raw[key] for key in numbers}, **tool_metrics, **fold_diagnostics.extract(raw), "usage_complete": raw.get("usage_complete") is True,
                "scope": "streaming_responses"}
    except Exception:
        return None


def run_trial(args, trial, prompt, auth, report, *, require_inference=True):
    record = dict(trial)
    proxy_process = agent = None
    listener = reader = None
    with tempfile.TemporaryDirectory(prefix="trial-", dir=report) as temporary:
        profile = Path(temporary).resolve()
        if not profile.is_relative_to(report.resolve()):
            raise RuntimeError("temporary profile escaped its report directory")
        env = trial_env(profile)
        work = profile / "workspace"
        work.mkdir()
        solution = work / "solution.py"
        skeleton = getattr(args, "scheduler_skeleton", False)
        if skeleton and trial["task"] != "scheduler":
            raise ValueError("skeleton is only supported for scheduler")
        solution.write_text(SCHEDULER_SKELETON if skeleton else STARTERS[trial["task"]], encoding="utf-8")
        initial_solution = solution.read_bytes()
        record.update(starter_variant="skeleton" if skeleton else "seeded",
                      initial_solution_sha256=hashlib.sha256(initial_solution).hexdigest())
        fixture_hash = workspace_fixture.prepare(work, trial["task"]) if getattr(args, "workspace_smoke_check", False) else None
        reader_hash = workspace_fixture.prepare_reader(work) if getattr(args, "fixed_workspace_commands", False) else None
        (Path(env["CODEX_HOME"]) / "auth.json").write_text(auth, encoding="utf-8")
        usage = {key: 0 for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")}
        observed = {"completed_turns": 0, "error_events": 0, "command_events": 0,
                    "file_change_events": 0, "tool_failure_events": 0, "rate_limit_detected": False}
        event_trace = []
        trace_truncated = False
        try:
            proxy_process, endpoint, listener = start_proxy(args.reflow, trial["max_continue"], env)
            command = [str(args.codex), "-a", "never", "exec", "--ignore-user-config", "--ignore-rules",
                       "--skip-git-repo-check", "--ephemeral", "--json", "-s", "workspace-write", "-C", str(work),
                       "-m", args.model, "-c", 'cli_auth_credentials_store="file"',
                       "-c", f'openai_base_url="{endpoint}"', "-c", f'model_reasoning_effort="{args.effort}"',
                       "-c", "features.memories=false", "-c", "features.apps=false",
                       "-c", "features.multi_agent=false", "-c", "features.multi_agent_v2=false",
                       "-c", "features.code_mode=true", "-c", "features.code_mode_host=true"]
            if os.name == "nt":
                command += ["-c", 'windows.sandbox="mxc"']
            command.append(prompt)
            started = time.monotonic()
            diagnostics = EventDiagnostics(lambda: read_metrics(endpoint, timeout=0.2), started)
            agent = subprocess.Popen(command, cwd=work, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **spawn_options())

            def consume():
                nonlocal trace_truncated
                # Only whitelisted numbers survive parsing. Text and tool payloads
                # are discarded rather than written to diagnostic files.
                while True:
                    line = agent.stdout.readline(1 << 20)
                    if not line:
                        break
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if event.get("type") == "turn.completed":
                        observed["completed_turns"] += 1
                        for key in usage:
                            value = event.get("usage", {}).get(key)
                            if isinstance(value, int) and value >= 0:
                                usage[key] += value
                    elif event.get("type") in ("error", "turn.failed"):
                        observed["error_events"] += 1
                        error_text = json.dumps(event).lower()
                        if any(marker in error_text for marker in ("429", "rate_limit", "rate limit", "too many requests")):
                            observed["rate_limit_detected"] = True
                            stop(agent)
                    elif event.get("type") in ("item.started", "item.completed"):
                        item = event.get("item", {})
                        kind = item.get("type")
                        observed_at = round(time.monotonic() - started, 3)
                        extra = diagnostics.observe(event["type"], item, capture=len(event_trace) < 80)
                        if kind in ("command_execution", "file_change", "mcp_tool_call", "agent_message", "reasoning"):
                            entry = {"at_seconds": observed_at,
                                     "event": event["type"], "kind": kind, **extra}
                            if item.get("status") in ("in_progress", "completed", "failed"):
                                entry["status"] = item["status"]
                            if type(item.get("exit_code")) is int:
                                entry["exit_code"] = item["exit_code"]
                            if len(event_trace) < 80:
                                event_trace.append(entry)
                            else:
                                trace_truncated = True
                        if event["type"] != "item.completed":
                            continue
                        if kind == "command_execution":
                            observed["command_events"] += 1
                        elif kind == "file_change":
                            observed["file_change_events"] += 1
                        if kind in ("command_execution", "file_change", "mcp_tool_call") and (
                                item.get("status") == "failed" or
                                type(item.get("exit_code")) is int and item["exit_code"] != 0):
                            observed["tool_failure_events"] += 1

            reader = threading.Thread(target=consume, daemon=True)
            reader.start()
            timed_out = False
            try:
                agent.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                stop(agent)
            reader.join(timeout=5)
            record.update(status="agent_timeout" if timed_out else "finished" if agent.returncode == 0 else "agent_error",
                          exit_code=agent.returncode, elapsed_seconds=round(time.monotonic() - started, 3),
                          client_reported_usage=usage, **observed)
            record.update(event_trace=event_trace, event_trace_truncated=trace_truncated)
            record["event_diagnostics"] = diagnostics.summary()
            if observed["rate_limit_detected"]:
                record["status"] = "rate_limited"
            metrics = read_metrics(endpoint)
            record["upstream_metrics"] = metrics
            record["upstream_reported_usage"] = {key: metrics[key] for key in ("input_tokens", "output_tokens", "cached_tokens", "cache_write_tokens", "reasoning_tokens")} if metrics and metrics["usage_complete"] else None
            record["model_evidence_valid"] = bool(metrics and metrics["requests"] > 0 and observed["completed_turns"] > 0)
            record["upstream_inference_observed"] = bool(metrics and metrics["completed"] > 0)
            record["tool_roundtrip_metrics_available"] = bool(metrics and "continued_tool_results" in metrics)
            record["continuation_tool_result_observed"] = bool(metrics and metrics.get("continued_tool_results", 0) > 0)
            record["mode"] = "live" if require_inference else "synthetic_runner_check"
            record["artifact_changed"] = solution.exists() and solution.read_bytes() != initial_solution
            if fixture_hash is not None:
                record["workspace_fixture"] = {"enabled": True, "checker_sha256": fixture_hash,
                                               "unchanged": workspace_fixture.unchanged(work, fixture_hash)}
                if not record["workspace_fixture"]["unchanged"]:
                    record["status"] = "fixture_changed"
                if reader_hash is not None:
                    reader_unchanged = workspace_fixture.unchanged(work, reader_hash, workspace_fixture.READ_FILENAME)
                    record["workspace_fixture"].update(reader_sha256=reader_hash, reader_unchanged=reader_unchanged)
                    if not reader_unchanged:
                        record["status"] = "fixture_changed"
            if require_inference and record["status"] == "finished" and not record["model_evidence_valid"]:
                record["status"] = "proxy_inference_unverified"
            record["score"] = grade(trial["task"], solution)
            score = record["score"]
            record["success"] = record["status"] == "finished" and score.get("status") == "scored" and score["passed"] == score["total"]
        except Exception as exc:
            record.update(status="runner_error", error_type=type(exc).__name__, success=False)
        finally:
            stop(agent)
            stop(proxy_process)
            if reader:
                reader.join(timeout=5)
            if listener:
                listener.join(timeout=5)
            if agent is not None and agent.stdout is not None:
                agent.stdout.close()
            if proxy_process is not None and proxy_process.stderr is not None:
                proxy_process.stderr.close()
    return record


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run-live", action="store_true")
    mode.add_argument("--preflight-only", action="store_true", help="check the client without reading auth or making model calls")
    parser.add_argument("--codex", type=Path)
    parser.add_argument("--reflow", type=Path)
    parser.add_argument("--auth-file", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh"], default="high")
    parser.add_argument("--tasks", nargs="+", choices=sorted(STARTERS), default=sorted(set(STARTERS) - {"ledger", "scheduler"}))
    parser.add_argument("--conditions", nargs="+", choices=["off", "on"], default=["off", "on"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-continue", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--workspace-smoke-check", action="store_true",
                        help="supply an immutable local check and workspace facts for ledger or scheduler")
    parser.add_argument("--fixed-workspace-commands", action="store_true",
                        help="supply an immutable reader and fixed native-tool workflow for scheduler")
    parser.add_argument("--scheduler-skeleton", action="store_true",
                        help="implement the same scheduler specification from a skeleton; fixed commands required")
    parser.add_argument("--stop-on-continuation-success", action="store_true",
                        help="stop bounded on-only sampling after a clean continuation, or any non-clean trial")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20 or not 1 <= args.max_continue <= 7 or not 30 <= args.timeout <= 1800:
        parser.error("repeats 1..20, max-continue 1..7, timeout 30..1800 are required")
    if not 0 <= args.interval_seconds <= 60:
        parser.error("interval-seconds must be 0..60")
    if args.preflight_only and not args.codex:
        parser.error("preflight requires --codex")
    if len(args.tasks) != len(set(args.tasks)):
        parser.error("task ids must be unique; use --repeats for repeated trials")
    if len(args.conditions) != len(set(args.conditions)):
        parser.error("conditions must be unique")
    if args.workspace_smoke_check and args.tasks not in (["ledger"], ["scheduler"]):
        parser.error("--workspace-smoke-check requires exactly --tasks ledger or --tasks scheduler")
    if args.fixed_workspace_commands and (not args.workspace_smoke_check or args.tasks != ["scheduler"]):
        parser.error("--fixed-workspace-commands requires --tasks scheduler --workspace-smoke-check")
    if args.scheduler_skeleton and not args.fixed_workspace_commands:
        parser.error("--scheduler-skeleton requires --fixed-workspace-commands")
    if args.stop_on_continuation_success and (not args.fixed_workspace_commands or args.conditions != ["on"] or args.repeats > 3):
        parser.error("--stop-on-continuation-success requires fixed commands, on-only, and at most 3 trials")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    report = ROOT / "build" / "evaluations" / stamp
    report.mkdir(parents=True, exist_ok=False)
    if args.preflight_only:
        codex = args.codex.resolve(strict=True)
        summary = {"kind": "client_execution_preflight", "live_account": False, "model_calls": 0,
                   "binary_sha256": fingerprint(codex),
                   "source_sha256": {name: fingerprint(HERE / name) for name in ("run.py", "client_preflight.py")},
                   "execution_preflight": execution_preflight(codex, report)}
        host = codex.with_name("codex-code-mode-host" + (".exe" if os.name == "nt" else ""))
        summary["code_mode_host_sha256"] = fingerprint(host) if host.is_file() else None
        (report / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        status = summary["execution_preflight"]["status"]
        print(f"Client preflight {status}; no auth read or model calls. Evidence: {report}")
        if status == "fail":
            raise SystemExit(1)
        return
    if args.self_test:
        outcomes = {}
        for task in STARTERS:
            with tempfile.TemporaryDirectory(prefix="scorer-", dir=report) as temporary:
                path = Path(temporary) / "solution.py"
                path.write_text(ORACLES[task], encoding="utf-8")
                oracle = grade(task, path)
                path.write_text(STARTERS[task], encoding="utf-8")
                starter = grade(task, path)
                if oracle.get("status") != "scored" or oracle["passed"] != oracle["total"] or starter.get("passed", 0) >= oracle["total"]:
                    raise RuntimeError(f"grader validation failed for {task}")
                outcomes[task] = {"oracle": oracle, "starter": starter}
        summary = {"kind": "grader_self_test", "model_calls": 0, "tasks": outcomes}
        (report / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"Grader self-test passed for {len(outcomes)} tasks; no model calls. Evidence: {report}")
        return
    prompts = {item["id"]: item["prompt"] for item in json.loads((HERE / "prompts.json").read_text(encoding="utf-8"))}
    prompts["ledger"] = LEDGER_PROMPT
    prompts["scheduler"] = SCHEDULER_SKELETON_PROMPT if args.scheduler_skeleton else SCHEDULER_PROMPT
    if args.workspace_smoke_check:
        prompts[args.tasks[0]] += workspace_fixture.FIXED_GUIDANCE if args.fixed_workspace_commands else workspace_fixture.GUIDANCE
    trials = []
    task_index = {task: index for index, task in enumerate(sorted(args.tasks))}
    rng = random.Random(args.seed)
    for repeat in range(args.repeats):
        order = list(args.tasks)
        rng.shuffle(order)
        for task in order:
            conditions = ["off", "on"] if (repeat + task_index[task]) % 2 == 0 else ["on", "off"]
            for condition in conditions:
                if condition not in args.conditions:
                    continue
                trials.append({"task": task, "repeat": repeat, "condition": condition,
                               "max_continue": args.max_continue if condition == "on" else 0})
    plan = {"kind": "paired_task_evaluation" if len(args.conditions) == 2 else "single_condition_diagnostic",
            "seed": args.seed, "model": args.model,
            "effort": args.effort, "timeout_seconds": args.timeout, "live_execution": args.run_live,
            "trial_concurrency": 1, "native_subagents_enabled": False, "code_mode_enabled": True,
            "interval_seconds": args.interval_seconds,
            "workspace_smoke_check": args.workspace_smoke_check,
            "fixed_workspace_commands": args.fixed_workspace_commands,
            "starter_variant": "skeleton" if args.scheduler_skeleton else "seeded",
            "stop_on_continuation_success": args.stop_on_continuation_success,
            "runner_sha256": fingerprint(HERE / "run.py"),
            "task_sources": {name: fingerprint(HERE / name) for name in ("tasks.py", "score.py", "prompts.json", "client_preflight.py", "ledger_task.py", "event_diagnostics.py", "workspace_fixture.py", "fold_diagnostics.py", "scheduler_task.py", "acceptance.py")},
            "trials": trials, "results": []}
    if args.run_live:
        if not all((args.codex, args.reflow, args.auth_file, args.model)):
            parser.error("live execution requires --codex, --reflow, --auth-file and --model")
        args.codex, args.reflow = args.codex.resolve(strict=True), args.reflow.resolve(strict=True)
        plan["execution_preflight"] = execution_preflight(args.codex, report)
        if plan["execution_preflight"]["status"] == "fail":
            plan["stopped_early"] = True
            (report / "results.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"Execution preflight failed; no auth copied or model calls made. Evidence: {report}")
        auth = args.auth_file.resolve(strict=True).read_text(encoding="utf-8-sig")
        parsed = json.loads(auth)
        if parsed.get("auth_mode") != "chatgpt" or not parsed.get("tokens", {}).get("access_token"):
            parser.error("an explicit native ChatGPT auth file is required")
        plan["binary_sha256"] = {"codex": fingerprint(args.codex), "reflow": fingerprint(args.reflow)}
        for index, trial in enumerate(trials):
            if index:
                time.sleep(args.interval_seconds)
            result = run_trial(args, trial, prompts[trial["task"]], auth, report)
            plan["results"].append(result)
            (report / "results.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            if result["status"] != "finished":
                plan["stopped_early"] = True
                plan["stop_reason"] = result["status"]
                break
            if args.stop_on_continuation_success:
                reason = acceptance.stop_reason(result)
                if reason:
                    plan.update(stopped_early=True, stop_reason=reason)
                    break
    (report / "results.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(f"{'Executed' if args.run_live else 'Planned'} {len(plan['results']) if args.run_live else len(trials)} trials. Evidence: {report}")


if __name__ == "__main__":
    main()
