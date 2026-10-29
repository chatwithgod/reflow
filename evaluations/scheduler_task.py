"""Opt-in resource-constrained build-planner repair; no real jobs are launched."""
import copy
import itertools
import random
import unittest

PROMPT = """Repair schedule_builds(tasks, slots, memory_limit) in solution.py. It plans a small build pipeline offline; never launch the planned jobs or access the network.
The supplied implementation is nearly complete but has interacting search/pruning and ordering bugs. Preserve the function signature and use only the Python standard library. Repair the implementation, rather than the checker.

tasks is a dict with at most 6 jobs, keyed by distinct nonempty string names. Each job is a dict with required fields: needs (a list of job names), duration (integer 1..5), memory (positive integer no greater than memory_limit). Ignore extra fields; repeated dependency names count once. Dependencies must name existing jobs; cycles, including self-cycles, are invalid. slots and memory_limit must be positive integers. Never accept bool as an integer. Malformed required values raise ValueError, including for invalid capacities with empty tasks. Do not mutate input dictionaries or lists. Empty valid tasks return [].

Every job starts at a nonnegative integer time, occupies one slot and its memory for the half-open interval [start,end), and runs nonpreemptively for exactly duration time units. All dependencies must finish before it starts. At every instant concurrent job count <= slots and concurrent memory <= memory_limit. A job ending at t releases capacity before jobs starting at t. Deliberately leaving resources idle can be optimal; maximizing immediate starts is not a valid optimization rule.

Return a list of (name,start,end) tuples sorted by (start,name). First minimize overall completion time (maximum end). Among ALL schedules with that minimum completion time, minimize the lexicographic tuple of (start,name,end) entries in that same sorted order. Names alone are not the tie-break key. Absolute time and the remaining running work can affect whether search states are equivalent.

This is a bounded maintenance fixture. Read only the supplied workspace files; use native file tools or PowerShell, run tools serially, and use no subagents. After repairing, run python verify_fixture.py. It already handles expected exceptions in negative examples; do not run intentionally invalid calls as uncaught failing shell snippets. Keep verify_fixture.py unchanged. Finish with a short result summary. The independent final grader covers more cases than the supplied smoke check.
"""

SKELETON = '''def schedule_builds(tasks, slots, memory_limit):
    """Implement the bounded build planner described in the task."""
    raise NotImplementedError("build planner is not implemented")
'''
SKELETON_PROMPT = (
    "Implement schedule_builds(tasks, slots, memory_limit) in solution.py from the supplied function skeleton. "
    "It plans a small build pipeline offline; never launch the planned jobs or access the network.\n"
    "Preserve the function signature and use only the Python standard library. Implement solution.py, not the checker.\n\n"
    + PROMPT.split("\n\n", 1)[1].replace("After repairing,", "After implementing,")
)

ORACLE = '''def schedule_builds(tasks, slots, memory_limit):
    if type(slots) is not int or slots < 1 or type(memory_limit) is not int or memory_limit < 1:
        raise ValueError("invalid capacities")
    if not isinstance(tasks, dict) or len(tasks) > 6 or any(not isinstance(k, str) or not k for k in tasks):
        raise ValueError("invalid jobs")
    names = sorted(tasks)
    positions = {name: i for i, name in enumerate(names)}
    duration, memory, dependencies = [], [], []
    for name in names:
        job = tasks[name]
        if not isinstance(job, dict) or not all(k in job for k in ("needs", "duration", "memory")):
            raise ValueError("invalid job")
        d, m, needs = job["duration"], job["memory"], job["needs"]
        if type(d) is not int or not 1 <= d <= 5 or type(m) is not int or not 1 <= m <= memory_limit:
            raise ValueError("invalid resources")
        if not isinstance(needs, list) or any(not isinstance(x, str) or x not in positions for x in needs):
            raise ValueError("unknown dependency")
        duration.append(d)
        memory.append(m)
        dependencies.append(sum(1 << positions[x] for x in set(needs)))
    full = (1 << len(names)) - 1
    seen = 0
    while seen != full:
        grown = seen
        for i in range(len(names)):
            if dependencies[i] & ~seen == 0:
                grown |= 1 << i
        if grown == seen:
            raise ValueError("cycle")
        seen = grown
    memo = {}
    def visit(now, done, active):
        if done == full:
            return now, ()
        state = (now, done, active)
        if state in memo:
            return memo[state]
        busy = sum(1 << job for job, end in active)
        ready = [i for i in range(len(names)) if not (done | busy) & (1 << i) and not dependencies[i] & ~done]
        free_slots = slots - len(active)
        free_memory = memory_limit - sum(memory[job] for job, end in active)
        choices = []
        for mask in range(1 << len(ready)):
            chosen = tuple(ready[i] for i in range(len(ready)) if mask & (1 << i))
            if len(chosen) <= free_slots and sum(memory[i] for i in chosen) <= free_memory and (chosen or active):
                choices.append(chosen)
        # Keep every feasible choice, including an idle interval while other jobs run.
        best = None
        for chosen in choices:
            running = active + tuple((i, now + duration[i]) for i in chosen)
            next_time = min(end for i, end in running)
            next_done = done | sum(1 << i for i, end in running if end == next_time)
            next_active = tuple(sorted((i, end) for i, end in running if end > next_time))
            finish, later = visit(next_time, next_done, next_active)
            starts = tuple((now, names[i], now + duration[i]) for i in chosen)
            candidate = (finish, starts + later)
            if best is None or candidate < best:
                best = candidate
        memo[state] = best
        return best
    finish, starts = visit(0, 0, ())
    return [(name, start, end) for start, name, end in starts]
'''

DEFECTS = {
    "state_alias": ('state = (now, done, active)', 'state = (done, tuple(job for job, end in active))'),
    "greedy_starts": ('# Keep every feasible choice, including an idle interval while other jobs run.',
                      'choices = [choice for choice in choices if len(choice) == max(map(len, choices))]'),
    "name_only_tie": ('if best is None or candidate < best:',
                      'if best is None or (candidate[0], tuple((name, start, end) for start, name, end in candidate[1])) < (best[0], tuple((name, start, end) for start, name, end in best[1])):'),
}
STARTER = ORACLE
for before, after in DEFECTS.values():
    assert STARTER.count(before) == 1
    STARTER = STARTER.replace(before, after)

CHECKER = '''"""Fixed local build-planner checks. Do not modify this file."""
import copy
import importlib.util
import json
from pathlib import Path
spec = importlib.util.spec_from_file_location("solution", Path(__file__).with_name("solution.py"))
solution = importlib.util.module_from_spec(spec)
spec.loader.exec_module(solution)
def job(d, m, needs=()):
    return {"duration": d, "memory": m, "needs": list(needs)}
assert solution.schedule_builds({}, 1, 1) == []
assert solution.schedule_builds({"a": job(2, 1), "b": job(1, 1)}, 2, 2) == [("a", 0, 2), ("b", 0, 1)]
tasks = {"a": job(1, 1), "b": job(4, 2), "c": job(1, 3, ["a"]), "d": job(4, 1, ["c"])}
before = copy.deepcopy(tasks)
assert solution.schedule_builds(tasks, 2, 3) == [("a", 0, 1), ("c", 1, 2), ("b", 2, 6), ("d", 2, 6)]
assert tasks == before
for tasks, slots in (({"a": job(1, 1, ["a"])}, 1), ({}, True)):
    try:
        solution.schedule_builds(tasks, slots, 3)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid input must be rejected")
print(json.dumps({"smoke_checks": 6, "passed": 6}))
'''


def job(duration, memory=1, needs=()):
    return {"duration": duration, "memory": memory, "needs": list(needs)}


def grid_oracle(tasks, slots, memory_limit):
    """Independent exhaustive integer-time search for valid small grading cases.

    Unlike the supplied event-jump code, this advances one time unit per layer
    and stores remaining durations. An earlier identical future state dominates
    a later one for minimum completion time; same-time states keep the best prefix.
    """
    names = sorted(tasks)
    index = {name: i for i, name in enumerate(names)}
    full = (1 << len(names)) - 1
    deps = [sum(1 << index[x] for x in set(tasks[name]["needs"])) for name in names]
    durations = [tasks[name]["duration"] for name in names]
    weights = [tasks[name]["memory"] for name in names]
    frontier = {(0, ()): ()}
    first_time = {(0, ()): 0}
    for now in range(sum(durations) + 1):
        if (full, ()) in frontier:
            return [(name, start, end) for start, name, end in frontier[(full, ())]]
        following = {}
        for (done, active), prefix in frontier.items():
            busy = {i for i, remaining in active}
            ready = [i for i in range(len(names)) if i not in busy and not done & (1 << i) and not deps[i] & ~done]
            for length in range(min(slots - len(active), len(ready)) + 1):
                for selected in itertools.combinations(ready, length):
                    if sum(weights[i] for i, remaining in active) + sum(weights[i] for i in selected) > memory_limit:
                        continue
                    running = active + tuple((i, durations[i]) for i in selected)
                    new_done = done | sum(1 << i for i, remaining in running if remaining == 1)
                    new_active = tuple(sorted((i, remaining - 1) for i, remaining in running if remaining > 1))
                    state = (new_done, new_active)
                    if first_time.get(state, now + 1) < now + 1:
                        continue
                    first_time[state] = now + 1
                    plan = prefix + tuple((now, names[i], now + durations[i]) for i in selected)
                    if state not in following or plan < following[state]:
                        following[state] = plan
        frontier = following
    raise AssertionError("valid bounded input has no schedule")


class SchedulerCases(unittest.TestCase):
    solution = None

    def check(self, tasks, slots, memory):
        before = copy.deepcopy(tasks)
        result = self.solution.schedule_builds(tasks, slots, memory)
        self.assertEqual(result, grid_oracle(tasks, slots, memory))
        self.assertEqual(tasks, before)

    def test_empty(self):
        self.check({}, 1, 1)

    def test_parallel(self):
        self.check({"a": job(2), "b": job(1)}, 2, 2)

    def test_chain(self):
        self.check({"a": job(2), "b": job(3, needs=["a"]), "c": job(1, needs=["b"])}, 3, 3)

    def test_duplicate_dependencies(self):
        self.check({"a": job(1), "b": job(2, needs=["a", "a"])}, 2, 2)

    def test_single_slot_lex_ready_order(self):
        self.check({"a": job(1, needs=["z"]), "z": job(2), "b": job(1)}, 1, 3)

    def test_memory_limits(self):
        self.check({"a": job(2, 2), "b": job(3, 2), "c": job(1, 1)}, 3, 3)

    def test_do_not_fill_initial_resources_greedily(self):
        self.check({"a": job(1, 1), "b": job(4, 2), "c": job(1, 3, ["a"]), "d": job(4, 1, ["c"])}, 2, 3)

    def test_idle_while_another_job_runs(self):
        self.check({"a": job(3, 1), "p": job(1, 1), "l": job(4, 2, ["p"]),
                    "c": job(1, 3, ["a"]), "d": job(4, 1, ["c"])}, 2, 3)

    def test_simultaneous_completion(self):
        self.check({"a": job(2), "b": job(2), "c": job(3, needs=["a", "b"])}, 2, 2)

    def test_tie_prefers_earlier_start_before_name(self):
        self.check({"a": job(1), "z": job(1), "b": job(2, needs=["a"])}, 2, 2)

    def test_dense_dag(self):
        self.check({"a": job(2), "b": job(1), "c": job(2, needs=["a", "b"]),
                    "d": job(3, needs=["b"]), "e": job(1, needs=["c", "d"])}, 2, 2)

    def test_six_jobs(self):
        self.check({name: job(1) for name in "abcdef"}, 3, 3)

    def test_cycles(self):
        for tasks in ({"a": job(1, needs=["a"])}, {"a": job(1, needs=["b"]), "b": job(1, needs=["a"])}):
            with self.subTest(tasks=tasks), self.assertRaises(ValueError):
                self.solution.schedule_builds(tasks, 2, 2)

    def test_unknown_dependency(self):
        with self.assertRaises(ValueError):
            self.solution.schedule_builds({"a": job(1, needs=["missing"])}, 1, 2)

    def test_invalid_required_values(self):
        cases = [({}, True, 1), ({}, 0, 1), ({}, 1.5, 1), ({}, 1, False), ({}, 1, 0), ({}, 1, 1.5), ([], 1, 1),
                 ({"": job(1)}, 1, 1), ({1: job(1)}, 1, 1), ({"a": job(True)}, 1, 1),
                 ({"a": job(0)}, 1, 1), ({"a": job(1.5)}, 1, 2), ({"a": job(6)}, 1, 1), ({"a": job(1, True)}, 1, 1),
                 ({"a": job(1, 0)}, 1, 1), ({"a": job(1, 1.5)}, 1, 2), ({"a": job(1, 2)}, 1, 1), ({"a": {}}, 1, 1),
                 ({"a": dict(job(1), needs="a")}, 1, 1), ({name: job(1) for name in "abcdefg"}, 2, 2)]
        for tasks, slots, memory in cases:
            with self.subTest(tasks=tasks, slots=slots, memory=memory), self.assertRaises(ValueError):
                self.solution.schedule_builds(tasks, slots, memory)

    def test_input_unchanged(self):
        self.check({"c": job(1, needs=["b", "a", "b"]), "b": job(2), "a": job(1)}, 2, 3)

    def test_deterministic_small_cases(self):
        rng = random.Random(31)
        for trial in range(12):
            names = list("abcde"[:3 + trial % 3])
            tasks = {name: job(rng.randint(1, 4), rng.randint(1, 3),
                         [earlier for earlier in names[:i] if rng.randrange(3) == 0]) for i, name in enumerate(names)}
            with self.subTest(trial=trial):
                self.check(tasks, 1 + trial % 3, 3 + trial % 2)

    def test_repeated_calls_do_not_share_search_state(self):
        for duration in (1, 5, 2):
            self.check({"a": job(duration), "b": job(1, needs=["a"])}, 2, 2)
