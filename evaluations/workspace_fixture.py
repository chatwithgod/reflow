"""Optional, immutable smoke-check entry point for the existing ledger task."""
import hashlib

FILENAME = "verify_fixture.py"
READ_FILENAME = "read_fixture.py"
READER = '''"""Read only the two supplied fixture files; do not modify this helper."""
from pathlib import Path
root = Path(__file__).resolve().parent
for name in ("solution.py", "verify_fixture.py"):
    print(name)
    print((root / name).read_text(encoding="utf-8"))
'''
FIXED_GUIDANCE = """
This acceptance workspace contains solution.py, verify_fixture.py and read_fixture.py.
Parent directories and any containing repository are outside the task.
Use exactly `python read_fixture.py` to read the supplied source and checks.
Use the native apply_patch tool to edit solution.py; discover it through available tool metadata if needed.
Do not invoke an apply_patch executable through a shell. Do not use shell snippets to rewrite files.
After repairing, use exactly `python verify_fixture.py` for validation, then finish with a short summary.
These are the only shell commands needed; do not run search, Git, environment probes or ad-hoc invalid-input snippets.
Keep both helper files byte-for-byte unchanged. The independent final grader still covers the full specification.
"""
GUIDANCE = """
Workspace facts for this run: solution.py and verify_fixture.py are the only supplied files.
No tests or AGENTS.md are supplied inside this workspace. Parent directories and any containing repository are outside this task.
Repair solution.py first. Then run `python verify_fixture.py` from the workspace to check the supplied examples.
Use native file tools or PowerShell to read these exact filenames. Keep verify_fixture.py byte-for-byte unchanged.
The supplied smoke check is a small subset; your solution must still satisfy the full specification above.
"""
CHECKER = '''"""Fixed local smoke checks. Do not modify this file."""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("solution", Path(__file__).with_name("solution.py"))
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)

first = {"scope": "s", "response_id": "r", "event_id": "a", "kind": "round", "round": 1,
         "retained": False, "status": "completed", "calls": ["discard"],
         "usage": {"input": 100, "output": 30, "cached": 20, "reasoning": 10}}
last = dict(first, event_id="b", round=2, retained=True, calls=["keep"],
            usage={"input": 200, "output": 60, "cached": 40, "reasoning": 20})
reply = {"scope": "s", "response_id": "r", "event_id": "c", "kind": "result", "call_id": "keep", "success": True}
assert solution.reconcile(iter([])) == []
rows = solution.reconcile([reply, last, first, dict(first)])
assert len(rows) == 1
assert rows[0]["billed"] == {"input": 300, "output": 90, "cached": 60, "reasoning": 30}
assert rows[0]["client"] == {"input": 100, "output": 70, "cached": 20, "reasoning": 30}
assert rows[0]["tools"] == {"issued": 1, "returned": 1, "succeeded": 1}
try:
    solution.reconcile([last])
except ValueError:
    pass
else:
    raise AssertionError("round gap must be rejected")
print(json.dumps({"smoke_checks": 6, "passed": 6}))
'''


def checker(task):
    if task == "ledger":
        return CHECKER
    if task == "scheduler":
        from scheduler_task import CHECKER as scheduler_checker
        return scheduler_checker
    raise ValueError("workspace checker requires ledger or scheduler")


def prepare(work, task="ledger"):
    path = work / FILENAME
    path.write_text(checker(task), encoding="utf-8", newline="\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_reader(work):
    path = work / READ_FILENAME
    path.write_text(READER, encoding="utf-8", newline="\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unchanged(work, expected, filename=FILENAME):
    if filename not in (FILENAME, READ_FILENAME):
        raise ValueError("unknown fixture helper")
    path = work / filename
    return path.is_file() and not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == expected
