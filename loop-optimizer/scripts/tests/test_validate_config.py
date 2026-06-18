"""Tests for G: validate_config.py -- run-config actor-separation + setup checks."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validate_config import validate_config  # noqa: E402


def _good():
    return {
        "runner":   {"model": "opus", "temperature": 0.7},
        "grader":   {"model": "sonnet", "temperature": 0, "version_id": "v1"},
        "proposer": {"model": "opus", "temperature": 0.3},
        "calibration": {"k_calib": 5},
        "budget": {"max_usd_total": 10},
    }


class TestValidateConfig(unittest.TestCase):
    def test_good_config_ok_no_warnings(self):
        res = validate_config(_good())
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["warnings"], [])

    def test_proposer_equals_grader_errors(self):
        c = _good(); c["proposer"]["model"] = "sonnet"  # == grader
        res = validate_config(c)
        self.assertFalse(res["ok"])
        self.assertTrue(any("proposer.model == grader.model" in e for e in res["errors"]))

    def test_bootstrapper_equals_grader_errors(self):
        c = _good(); c["bootstrapper"] = {"model": "sonnet", "temperature": 0.7}
        res = validate_config(c)
        self.assertFalse(res["ok"])
        self.assertTrue(any("bootstrapper.model == grader.model" in e for e in res["errors"]))

    def test_grader_nonzero_temp_errors(self):
        c = _good(); c["grader"]["temperature"] = 0.2
        res = validate_config(c)
        self.assertFalse(res["ok"])
        self.assertTrue(any("grader.temperature must be 0" in e for e in res["errors"]))

    def test_missing_block_errors(self):
        c = _good(); del c["proposer"]
        res = validate_config(c)
        self.assertFalse(res["ok"])
        self.assertTrue(any("proposer" in e for e in res["errors"]))

    def test_runner_temp_zero_warns_not_errors(self):
        c = _good(); c["runner"]["temperature"] = 0
        res = validate_config(c)
        self.assertTrue(res["ok"])
        self.assertTrue(any("runner.temperature == 0" in w for w in res["warnings"]))

    def test_low_kcalib_warns(self):
        c = _good(); c["calibration"]["k_calib"] = 3
        res = validate_config(c)
        self.assertTrue(res["ok"])
        self.assertTrue(any("k_calib" in w for w in res["warnings"]))

    def test_case_insensitive_model_collision_caught(self):
        # "Sonnet" vs "sonnet" must still trip the actor-separation check.
        c = _good(); c["proposer"]["model"] = "Sonnet"
        res = validate_config(c)
        self.assertFalse(res["ok"])
        self.assertTrue(any("proposer.model == grader.model" in e for e in res["errors"]))

    def test_runner_equals_grader_warns_not_errors(self):
        # GAP-2: same model for runner and grader weakens player/referee separation,
        # but is a deliberate (if weaker) choice -> WARNING, not a blocking error.
        c = _good(); c["runner"]["model"] = "sonnet"  # == grader; temp stays 0.7
        res = validate_config(c)
        self.assertTrue(res["ok"], res)
        self.assertTrue(any("runner.model == grader.model" in w for w in res["warnings"]))

    def test_nonnumeric_grader_temp_returns_structured_error(self):
        # Must return a structured error, not raise, when called as a library.
        c = _good(); c["grader"]["temperature"] = "high"
        res = validate_config(c)
        self.assertFalse(res["ok"])
        self.assertTrue(any("grader.temperature must be 0" in e for e in res["errors"]))

    def test_tools_mode_non_none_errors(self):
        # F-26: only tools.mode "none" is implemented; "mocked" must block the run.
        c = _good(); c["tools"] = {"mode": "mocked"}
        res = validate_config(c)
        self.assertFalse(res["ok"])
        self.assertTrue(any("tools.mode" in e for e in res["errors"]))

    def test_tools_mode_none_ok(self):
        c = _good(); c["tools"] = {"mode": "none"}
        res = validate_config(c)
        self.assertTrue(res["ok"], res)


if __name__ == "__main__":
    unittest.main()
