"""Score one solution in a separate process without retaining agent output."""
import argparse
import contextlib
import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest

solution = None


class Intervals(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(solution.merge_intervals([]), [])

    def test_unsorted_overlap(self):
        self.assertEqual(solution.merge_intervals([(7, 9), (1, 4), (3, 8)]), [(1, 9)])

    def test_nested(self):
        self.assertEqual(solution.merge_intervals([(1, 10), (2, 3), (5, 8)]), [(1, 10)])

    def test_touching(self):
        self.assertEqual(solution.merge_intervals([(4, 7), (1, 4), (9, 10)]), [(1, 7), (9, 10)])

    def test_negative_and_points(self):
        self.assertEqual(solution.merge_intervals([(-3, 0), (0, 0), (-5, -3), (2, 2)]), [(-5, 0), (2, 2)])

    def test_input_unchanged(self):
        values = [[5, 8], [1, 6]]
        before = copy.deepcopy(values)
        self.assertEqual(solution.merge_intervals(values), [(1, 8)])
        self.assertEqual(values, before)

    def test_reversed_rejected(self):
        with self.assertRaises(ValueError):
            solution.merge_intervals([(1, 10), (3, 2)])

    def test_generator(self):
        self.assertEqual(solution.merge_intervals(iter([(5, 5), (1, 2), (2, 5)])), [(1, 5)])


class Topo(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(solution.topological_order({}), [])

    def test_dependency_order(self):
        self.assertEqual(solution.topological_order({"a": ["z"], "z": []}), ["z", "a"])

    def test_current_ready_order(self):
        self.assertEqual(solution.topological_order({"a": ["z"], "z": [], "b": []}), ["b", "z", "a"])

    def test_dependency_only_and_duplicates(self):
        self.assertEqual(solution.topological_order({"build": ["parse", "parse"], "ship": ["build"], "lint": []}), ["lint", "parse", "build", "ship"])

    def test_self_cycle(self):
        with self.assertRaises(ValueError):
            solution.topological_order({"a": ["a"]})

    def test_cycle(self):
        with self.assertRaises(ValueError):
            solution.topological_order({"a": ["b"], "b": ["c"], "c": ["a"], "free": []})

    def test_input_unchanged(self):
        data = {"x": ["a", "a"], "a": []}
        before = copy.deepcopy(data)
        self.assertEqual(solution.topological_order(data), ["a", "x"])
        self.assertEqual(data, before)

    def test_long_chain(self):
        nodes = [f"n{i:03d}" for i in range(200)]
        data = {name: [nodes[i - 1]] if i else [] for i, name in enumerate(nodes)}
        self.assertEqual(solution.topological_order(data), nodes)


class NDJSON(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(solution.parse_chunks(iter([])), [])

    def test_one_chunk(self):
        self.assertEqual(solution.parse_chunks([b'{"a":1}\n{"b":2}\n']), [{"a": 1}, {"b": 2}])

    def test_whitespace_and_crlf(self):
        self.assertEqual(solution.parse_chunks([b' \r\n1\r', b'\n\t\n2\n']), [1, 2])

    def test_utf8_byte_boundaries(self):
        raw = ('{"text":"中文🙂"}\n"尾"\n').encode("utf-8")
        self.assertEqual(solution.parse_chunks(bytes([b]) for b in raw), [{"text": "中文🙂"}, "尾"])

    def test_final_line(self):
        self.assertEqual(solution.parse_chunks([b'{"key"', b': [1,2]}']), [{"key": [1, 2]}])

    def test_scalar_values(self):
        self.assertEqual(solution.parse_chunks([b'true\nnull\n-1.25\n[1,"a"]\n']), [True, None, -1.25, [1, "a"]])

    def test_unicode_separator_is_not_newline(self):
        self.assertEqual(solution.parse_chunks(['"a\u2028b"\n'.encode()]), ["a\u2028b"])

    def test_invalid_json(self):
        with self.assertRaises(ValueError):
            solution.parse_chunks([b'1\n{broken}\n2\n'])

    def test_invalid_utf8(self):
        with self.assertRaises(ValueError):
            solution.parse_chunks([b'"\xff"\n'])


class LRU(unittest.TestCase):
    def test_negative(self):
        with self.assertRaises(ValueError):
            solution.LRUCache(-1)

    def test_zero(self):
        cache = solution.LRUCache(0)
        cache.put("x", 1)
        self.assertEqual(cache.keys(), [])
        self.assertEqual(cache.get("x", "missing"), "missing")

    def test_hit_recency(self):
        cache = solution.LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.keys(), ["b", "a"])

    def test_miss_does_not_insert(self):
        cache = solution.LRUCache(2)
        cache.put("a", 1)
        self.assertEqual(cache.get("missing", 9), 9)
        self.assertEqual(cache.keys(), ["a"])

    def test_update_recency(self):
        cache = solution.LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("a", 3)
        self.assertEqual(cache.keys(), ["b", "a"])
        self.assertEqual(cache.get("a"), 3)

    def test_eviction(self):
        cache = solution.LRUCache(2)
        for key in ["a", "b", "c"]:
            cache.put(key, key)
        self.assertEqual(cache.keys(), ["b", "c"])
        self.assertIsNone(cache.get("a"))

    def test_none_and_false_values(self):
        cache = solution.LRUCache(2)
        cache.put("a", None)
        cache.put("b", False)
        self.assertIsNone(cache.get("a", "fallback"))
        self.assertIs(cache.get("b", "fallback"), False)

    def test_capacity_one(self):
        cache = solution.LRUCache(1)
        cache.put(1, "one")
        cache.put(2, "two")
        self.assertEqual(cache.keys(), [2])
        self.assertEqual(cache.get(1, "gone"), "gone")

    def test_keys_is_observation(self):
        cache = solution.LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.keys(), ["a", "b"])
        cache.put("c", 3)
        self.assertEqual(cache.keys(), ["b", "c"])


CASES = {"intervals": Intervals, "topo": Topo, "ndjson": NDJSON, "lru": LRU}


def main():
    global solution
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=CASES, required=True)
    parser.add_argument("--solution", type=Path, required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CASES[args.task])
    total = suite.countTestCases()
    result = unittest.TestResult()
    try:
        with open(os.devnull, "w") as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            spec = importlib.util.spec_from_file_location("solution", args.solution.resolve(strict=True))
            solution = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(solution)
            suite.run(result)
        failures = [case.id().split(".")[-1] for case, _ in result.failures + result.errors]
        report = {"status": "scored", "total": total, "passed": result.testsRun - len(failures), "failed": failures}
    except BaseException as exc:
        report = {"status": "load_error", "total": total, "passed": 0, "error_type": type(exc).__name__}
    print(json.dumps(report))


if __name__ == "__main__":
    main()
