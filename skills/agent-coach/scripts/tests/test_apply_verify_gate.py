"""Tests for D: apply_change is gated on verify_change -- a change that fails
locality (or uniqueness) is REFUSED at apply and never staged."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apply_change import op_apply  # noqa: E402


class TestApplyVerifyGate(unittest.TestCase):
    def _candidate_path(self):
        return os.path.join(tempfile.mkdtemp(), "prompt.candidate.md")

    def test_local_change_applies(self):
        cand = self._candidate_path()
        res = op_apply({
            "current_text": "alpha beta gamma",
            "before": "beta", "after": "BETA",
            "candidate_file": cand,
        })
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["wrote_candidate"])
        with open(cand, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "alpha BETA gamma")

    def test_nonlocal_change_refused_and_not_staged(self):
        cand = self._candidate_path()
        # before 10 chars; after adds 150 -> fails both ratio and abs floor.
        res = op_apply({
            "current_text": "prefix 0123456789 suffix",
            "before": "0123456789", "after": "0123456789" + "Z" * 150,
            "candidate_file": cand,
        })
        self.assertFalse(res["ok"])
        self.assertFalse(res["wrote_candidate"])
        self.assertIn("verify_change rejected", res["reason"])
        self.assertFalse(os.path.exists(cand))  # nothing was staged

    def test_ambiguous_change_refused_and_not_staged(self):
        cand = self._candidate_path()
        res = op_apply({
            "current_text": "foo bar foo",
            "before": "foo", "after": "FOO",
            "candidate_file": cand,
        })
        self.assertFalse(res["ok"])
        self.assertFalse(os.path.exists(cand))

    def test_subtraction_long_removal_applies_with_kind(self):
        # H1 regression: a >100-char rule removal passes apply when kind is given,
        # because apply re-runs verify with the same kind -> they agree.
        cand = self._candidate_path()
        rule = "X" * 130
        res = op_apply({
            "current_text": "KEEP. " + rule + " END.",
            "before": rule, "after": "",
            "kind": "subtraction",
            "candidate_file": cand,
        })
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["wrote_candidate"])

    def test_subtraction_long_removal_refused_without_kind(self):
        # Fail-safe: without kind, the default ratio cap rejects the >100-char
        # removal (rejects rather than silently over-applies); documents that
        # subtraction payloads MUST carry kind.
        cand = self._candidate_path()
        rule = "X" * 130
        res = op_apply({
            "current_text": "KEEP. " + rule + " END.",
            "before": rule, "after": "",
            "candidate_file": cand,
        })
        self.assertFalse(res["ok"])
        self.assertFalse(os.path.exists(cand))


if __name__ == "__main__":
    unittest.main()
