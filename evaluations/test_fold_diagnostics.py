import copy
import json
import unittest

from fold_diagnostics import REASONS, extract


class FoldDiagnosticsTests(unittest.TestCase):
    def fixture(self):
        return {"diagnostics_version": 1, "fold_decisions": dict.fromkeys(REASONS, 0),
                "reasoning_token_samples": [0, 516, 20], "reasoning_sample_drops": 0, "reasoning_missing_reports": 0}

    def test_old_metrics_remain_supported_and_new_payload_is_whitelisted(self):
        self.assertEqual(extract({"requests": 1}), {})
        raw = self.fixture()
        raw["secret"] = "PRIVATE_SENTINEL"
        raw["fold_decisions"]["PRIVATE_SENTINEL"] = 99
        parsed = extract(raw)
        self.assertTrue(parsed["fold_diagnostics_valid"])
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(parsed))
        parsed["reasoning_token_samples"][0] = 999
        self.assertEqual(raw["reasoning_token_samples"][0], 0)

    def test_invalid_numbers_versions_and_limits_are_not_trusted(self):
        mutations = [lambda r: r.update(diagnostics_version=True), lambda r: r.update(diagnostics_version=2),
                     lambda r: r.update(reasoning_token_samples=[0]*65), lambda r: r.update(reasoning_token_samples=[-1]),
                     lambda r: r.update(reasoning_token_samples=[True]), lambda r: r.update(reasoning_token_samples=["PRIVATE_SENTINEL"]),
                     lambda r: r.update(reasoning_sample_drops=-1), lambda r: r.update(reasoning_missing_reports=1.1),
                     lambda r: r["fold_decisions"].update(other=True), lambda r: r["fold_decisions"].pop("continue")]
        for mutate in mutations:
            raw = copy.deepcopy(self.fixture())
            mutate(raw)
            self.assertEqual(extract(raw), {"fold_diagnostics_valid": False})

    def test_missing_optional_empty_sample_array_is_valid(self):
        raw = self.fixture()
        del raw["reasoning_token_samples"]
        self.assertEqual(extract(raw)["reasoning_token_samples"], [])
