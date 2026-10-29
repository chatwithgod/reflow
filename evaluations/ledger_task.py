"""Opt-in continuation-accounting maintenance fixture; never production data."""
import copy
import unittest


PROMPT = """Repair reconcile(events) in solution.py, a response-usage ledger for a continuation proxy.
Use Python standard library only. Preserve the signature, do not edit grading files, and do not access the network.
Work in this Windows workspace. Use native file tools or PowerShell, not POSIX shell syntax. Run tools serially, use no subagents, and verify your implementation with local examples before finishing.

Input is a finite iterable of event dictionaries, in arbitrary arrival order, possibly replayed after reconnect. Do not mutate it. Each event has nonempty string scope, response_id, event_id, and kind.
kind='round': additionally round (positive integer, never bool), retained (bool), status ('completed', 'failed', 'cancelled'), usage (None or a dict of input, output, cached, reasoning), calls (list of distinct nonempty string call IDs).
kind='result': additionally call_id (nonempty string) and success (bool).
Only these two kinds are allowed. Usage counters must be nonnegative integers, never bool; cached <= input and reasoning <= output. Reject malformed required fields with ValueError. Ignore extra fields.

Deduplicate events by (scope,event_id). Their normalized required fields must agree; a conflicting replay raises ValueError, even across response IDs. Different event IDs may describe the same logical round (scope,response_id,round) or tool result (scope,response_id,call_id): accept identical normalized data once, reject conflicting data. Event IDs and ignored extras do not affect this second comparison.

Group by (scope,response_id). A result may precede its round. Every group must contain rounds numbered exactly 1..N. Exactly round N is retained. Earlier rounds must be completed. The retained round may have any allowed status; failed/cancelled rounds must have no calls. Unknown or discarded-round tool results do not contribute to counts. Calls in discarded rounds must never be counted as issued; a call ID reused in the retained round is counted once there. Results and calls cannot leak across scopes or responses.

Return a list sorted by (scope,response_id), one dictionary per group with EXACTLY:
scope, response_id, rounds=N, continuations=N-1, status=retained status,
usage_complete=all rounds have usage,
billed={input,output,cached,reasoning}: sum each counter from every round with known usage, including discarded/failed/cancelled rounds,
client=None unless status completed AND usage_complete. Otherwise client={input: first round input, cached: first round cached, reasoning: sum of all round reasoning, output: sum of all round reasoning + retained round output - retained round reasoning},
tools={issued,returned,succeeded}: consider only calls from a completed retained round, count unique call IDs, matching result IDs, and matching results with success true, respectively.
An empty iterable returns []. A results-only group, gap in rounds, invalid retention, conflicting duplicate, or invalid schema raises ValueError. This is an offline maintenance fixture, not a model-quality comparison.
"""

STARTER = '''def reconcile(events):
    rows = {}
    for event in events:
        if event.get("kind") != "round":
            continue
        key = event["response_id"]
        row = rows.setdefault(key, {"scope": event["scope"], "response_id": key,
            "rounds": 0, "continuations": 0, "status": event["status"],
            "usage_complete": True, "billed": dict.fromkeys(("input", "output", "cached", "reasoning"), 0),
            "client": None, "tools": {"issued": 0, "returned": 0, "succeeded": 0}})
        row["rounds"] += 1
        row["continuations"] = row["rounds"] - 1
        if event["usage"]:
            for name, value in event["usage"].items():
                row["billed"][name] += value
        row["tools"]["issued"] += len(event["calls"])
    return list(rows.values())
'''

# Independent reference for grader self-check only; never copied to the live workspace.
ORACLE = '''def reconcile(events):
    import json
    fields = ("input", "output", "cached", "reasoning")
    def fail():
        raise ValueError("invalid ledger")
    def text(value):
        if not isinstance(value, str) or not value:
            fail()
        return value
    def integer(value, minimum=0):
        if type(value) is not int or value < minimum:
            fail()
        return value
    def signature(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    seen, groups = {}, {}
    for raw in events:
        try:
            scope, response, event = (text(raw[k]) for k in ("scope", "response_id", "event_id"))
            kind = raw["kind"]
            if kind == "round":
                number = integer(raw["round"], 1)
                retained, status, usage, calls = (raw[k] for k in ("retained", "status", "usage", "calls"))
                if type(retained) is not bool or status not in ("completed", "failed", "cancelled"):
                    fail()
                if not isinstance(calls, list):
                    fail()
                calls = [text(x) for x in calls]
                if len(set(calls)) != len(calls) or (status != "completed" and calls):
                    fail()
                if usage is not None:
                    usage = {k: integer(usage[k]) for k in fields}
                    if usage["cached"] > usage["input"] or usage["reasoning"] > usage["output"]:
                        fail()
                payload = dict(round=number, retained=retained, status=status, usage=usage, calls=calls)
                bucket, identity = "rounds", number
            elif kind == "result":
                call, success = text(raw["call_id"]), raw["success"]
                if type(success) is not bool:
                    fail()
                payload = dict(call_id=call, success=success)
                bucket, identity = "results", call
            else:
                fail()
        except (KeyError, TypeError, AttributeError):
            fail()
        normalized = signature(dict(response_id=response, kind=kind, **payload))
        key = (scope, event)
        if key in seen and seen[key] != normalized:
            fail()
        seen[key] = normalized
        group = groups.setdefault((scope, response), {"rounds": {}, "results": {}})
        target = group[bucket]
        if identity in target and signature(target[identity]) != signature(payload):
            fail()
        target[identity] = payload
    output = []
    for (scope, response), group in sorted(groups.items()):
        table, results = group["rounds"], group["results"]
        n = len(table)
        if not n or sorted(table) != list(range(1, n + 1)):
            fail()
        rounds = [table[i] for i in range(1, n + 1)]
        if any(r["retained"] != (i == n - 1) or (i < n - 1 and r["status"] != "completed") for i, r in enumerate(rounds)):
            fail()
        final = rounds[-1]
        known = [r["usage"] for r in rounds if r["usage"] is not None]
        billed = {k: sum(u[k] for u in known) for k in fields}
        complete = len(known) == n
        client = None
        if complete and final["status"] == "completed":
            client = dict(input=known[0]["input"], cached=known[0]["cached"], reasoning=billed["reasoning"],
                output=billed["reasoning"] + known[-1]["output"] - known[-1]["reasoning"])
        calls = set(final["calls"]) if final["status"] == "completed" else set()
        matched = calls.intersection(results)
        output.append(dict(scope=scope, response_id=response, rounds=n, continuations=n - 1,
            status=final["status"], usage_complete=complete, billed=billed, client=client,
            tools=dict(issued=len(calls), returned=len(matched), succeeded=sum(results[c]["success"] for c in matched))))
    return output
'''


def round_event(number=1, *, scope="s", response="r", retained=True, status="completed", calls=(), usage=True, event=None):
    return {"scope": scope, "response_id": response, "event_id": event or f"round-{number}",
            "kind": "round", "round": number, "retained": retained, "status": status,
            "calls": list(calls), "usage": {"input": 100 * number, "output": 30 * number,
            "cached": 20 * number, "reasoning": 10 * number} if usage else None}


def result_event(call="keep", *, scope="s", response="r", success=True, event=None):
    return {"scope": scope, "response_id": response, "event_id": event or f"result-{call}",
            "kind": "result", "call_id": call, "success": success}


class LedgerCases(unittest.TestCase):
    solution = None

    def reconcile(self, events):
        return self.solution.reconcile(events)

    def test_empty_generator(self):
        self.assertEqual(self.reconcile(iter([])), [])

    def test_single_round_exact_schema(self):
        self.assertEqual(self.reconcile([round_event()]), [{"scope": "s", "response_id": "r", "rounds": 1,
            "continuations": 0, "status": "completed", "usage_complete": True,
            "billed": {"input": 100, "output": 30, "cached": 20, "reasoning": 10},
            "client": {"input": 100, "output": 30, "cached": 20, "reasoning": 10},
            "tools": {"issued": 0, "returned": 0, "succeeded": 0}}])

    def test_folded_billed_and_visible_usage_differ(self):
        row = self.reconcile([round_event(2), round_event(1, retained=False)])[0]
        self.assertEqual(row["billed"], {"input": 300, "output": 90, "cached": 60, "reasoning": 30})
        self.assertEqual(row["client"], {"input": 100, "output": 70, "cached": 20, "reasoning": 30})
        self.assertEqual((row["rounds"], row["continuations"]), (2, 1))

    def test_replay_and_extra_fields_do_not_double_count(self):
        first = round_event()
        extra = dict(first, debug="ignored")
        extra["usage"] = dict(first["usage"], ignored=99)
        self.assertEqual(self.reconcile([first, copy.deepcopy(first), extra]), self.reconcile([first]))

    def test_logical_duplicate_with_new_event_id(self):
        first = round_event(calls=["keep"])
        result = result_event()
        self.assertEqual(self.reconcile([first, dict(first, event_id="again"), result, dict(result, event_id="again-result")]),
                         self.reconcile([first, result]))

    def test_conflicting_event_id_across_responses(self):
        with self.assertRaises(ValueError):
            self.reconcile([round_event(), round_event(response="other")])

    def test_conflicting_round_with_distinct_event_id(self):
        with self.assertRaises(ValueError):
            self.reconcile([round_event(), round_event(event="other", calls=["new"])])

    def test_conflicting_tool_result(self):
        with self.assertRaises(ValueError):
            self.reconcile([round_event(calls=["keep"]), result_event(), result_event(success=False, event="different")])

    def test_scopes_and_responses_are_isolated_and_sorted(self):
        events = [round_event(scope="b", calls=["keep"]), round_event(scope="a", calls=["keep"]),
                  round_event(scope="a", response="z", event="z-round", calls=["keep"]), result_event(scope="b")]
        rows = self.reconcile(events)
        self.assertEqual([(r["scope"], r["response_id"]) for r in rows], [("a", "r"), ("a", "z"), ("b", "r")])
        self.assertEqual([r["tools"]["returned"] for r in rows], [0, 0, 1])

    def test_only_retained_calls_and_matching_successes(self):
        events = [result_event("discard"), result_event("keep"), result_event("bad", success=False), result_event("unknown"),
                  round_event(1, retained=False, calls=["discard"]), round_event(2, calls=["keep", "bad", "pending"])]
        self.assertEqual(self.reconcile(events)[0]["tools"], {"issued": 3, "returned": 2, "succeeded": 1})

    def test_call_reused_in_retained_round(self):
        row = self.reconcile([round_event(1, retained=False, calls=["keep"]), result_event(), round_event(2, calls=["keep"])])[0]
        self.assertEqual(row["tools"], {"issued": 1, "returned": 1, "succeeded": 1})

    def test_missing_usage_is_not_zero_or_complete(self):
        row = self.reconcile([round_event(1, retained=False), round_event(2, usage=False)])[0]
        self.assertFalse(row["usage_complete"])
        self.assertIsNone(row["client"])
        self.assertEqual(row["billed"], {"input": 100, "output": 30, "cached": 20, "reasoning": 10})

    def test_failed_and_cancelled_retained_rounds(self):
        for status in ("failed", "cancelled"):
            with self.subTest(status=status):
                row = self.reconcile([round_event(1, retained=False, calls=["keep"]), result_event(), round_event(2, status=status)])[0]
                self.assertEqual(row["status"], status)
                self.assertIsNone(row["client"])
                self.assertEqual(row["billed"]["input"], 300)
                self.assertEqual(row["tools"], {"issued": 0, "returned": 0, "succeeded": 0})

    def test_round_gaps_and_results_only_rejected(self):
        for events in ([round_event(2)], [round_event(1, retained=False), round_event(3)], [result_event()]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                self.reconcile(events)

    def test_invalid_retention_and_intermediate_status(self):
        for events in ([round_event(retained=False)], [round_event(), round_event(2)],
                       [round_event(1, retained=False, status="failed"), round_event(2)]):
            with self.subTest(events=events), self.assertRaises(ValueError):
                self.reconcile(events)

    def test_schema_numbers_and_usage_bounds(self):
        invalid = [dict(round_event(), round=True), dict(round_event(), round=0), dict(round_event(), retained=1),
                   dict(round_event(), kind="unknown"), dict(round_event(), scope=""),
                   dict(round_event(), calls=["x", "x"]), round_event(status="failed", calls=["x"]),
                   dict(round_event(), calls="x"), dict(round_event(), status="other"),
                   dict(result_event(), success=1), dict(result_event(), call_id="")]
        for key, value in (("input", -1), ("input", True), ("output", 1.5), ("cached", 101), ("reasoning", 31)):
            event = round_event()
            event["usage"][key] = value
            invalid.append(event)
        event = round_event()
        del event["usage"]["cached"]
        invalid.append(event)
        for event in invalid:
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.reconcile([event])

    def test_input_unchanged_and_one_shot_iterable(self):
        events = [result_event(), round_event(calls=["keep"])]
        before = copy.deepcopy(events)
        self.assertEqual(self.reconcile(iter(events))[0]["tools"]["succeeded"], 1)
        self.assertEqual(events, before)

    def test_many_interleaved_rounds_and_replays(self):
        events = []
        for n in range(1, 25):
            item = round_event(n, retained=n == 24, calls=["keep"])
            events.extend([item, dict(item, event_id=f"duplicate-{n}")])
        events.append(result_event())
        row = self.reconcile(reversed(events))[0]
        self.assertEqual((row["rounds"], row["continuations"]), (24, 23))
        self.assertEqual(row["billed"]["input"], 30000)
        self.assertEqual(row["client"]["output"], 3480)
        self.assertEqual(row["tools"], {"issued": 1, "returned": 1, "succeeded": 1})
