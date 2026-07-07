"""Tests for apply_change.py -- S4 staging-only application + idempotent promote.

The critical safety property: apply writes ONLY the candidate; the live target is
byte-invariant. Promote is idempotent.
"""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apply_change import apply_change_text, op_apply, op_promote  # noqa: E402


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class TestApplyTransform(unittest.TestCase):
    def test_unique_replacement(self):
        out = apply_change_text("alpha beta gamma", "beta", "BETA")
        self.assertEqual(out, "alpha BETA gamma")

    def test_refuses_multi_match(self):
        with self.assertRaises(ValueError):
            apply_change_text("foo bar foo", "foo", "X")

    def test_refuses_zero_match(self):
        with self.assertRaises(ValueError):
            apply_change_text("alpha beta", "zzz", "X")

    def test_subtraction_to_empty(self):
        out = apply_change_text("rule-A. rule-B. rule-C.", "rule-B. ", "")
        self.assertEqual(out, "rule-A. rule-C.")


class TestStagingIsolation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        # The LIVE target -- must never be touched by these scripts.
        self.live = os.path.join(self.dir, "live-target.md")
        with open(self.live, "w", encoding="utf-8") as fh:
            fh.write("LIVE: do not edit. alpha beta gamma")
        self.live_sha_before = _sha(self.live)

        self.current = os.path.join(self.dir, "prompt.current.md")
        with open(self.current, "w", encoding="utf-8") as fh:
            fh.write("alpha beta gamma")
        self.candidate = os.path.join(self.dir, "prompt.candidate.md")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_apply_writes_only_candidate_live_invariant(self):
        res = op_apply({
            "op": "apply",
            "current_file": self.current,
            "before": "beta",
            "after": "BETA",
            "candidate_file": self.candidate,
        })
        self.assertTrue(res["ok"])
        # Candidate now holds the change.
        with open(self.candidate, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "alpha BETA gamma")
        # The LIVE target is byte-identical (never written).
        self.assertEqual(_sha(self.live), self.live_sha_before)
        # The "current" staging copy is ALSO unchanged by apply (only candidate).
        with open(self.current, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "alpha beta gamma")

    def test_promote_copies_candidate_to_current_not_live(self):
        # stage a candidate first
        op_apply({
            "op": "apply", "current_file": self.current,
            "before": "beta", "after": "BETA", "candidate_file": self.candidate,
        })
        res = op_promote({
            "op": "promote",
            "current_file": self.current,
            "candidate_file": self.candidate,
            "confirmed": True,
        })
        self.assertTrue(res["ok"])
        self.assertTrue(res["promoted"])
        self.assertFalse(res["already_promoted"])
        with open(self.current, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "alpha BETA gamma")
        # Live STILL invariant after a promote.
        self.assertEqual(_sha(self.live), self.live_sha_before)

    def test_promote_is_idempotent(self):
        op_apply({
            "op": "apply", "current_file": self.current,
            "before": "beta", "after": "BETA", "candidate_file": self.candidate,
        })
        first = op_promote({
            "op": "promote", "current_file": self.current, "candidate_file": self.candidate,
            "confirmed": True,
        })
        self.assertTrue(first["promoted"])
        # Re-running promote: current already == candidate -> no-op.
        second = op_promote({
            "op": "promote", "current_file": self.current, "candidate_file": self.candidate,
            "confirmed": True,
        })
        self.assertTrue(second["ok"])
        self.assertFalse(second["promoted"])
        self.assertTrue(second["already_promoted"])
        with open(self.current, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "alpha BETA gamma")

    def test_promote_refuses_without_confirm(self):
        # S7 wall: promote must refuse (and NOT write current) without confirmed.
        op_apply({
            "op": "apply", "current_file": self.current,
            "before": "beta", "after": "BETA", "candidate_file": self.candidate,
        })
        res = op_promote({
            "op": "promote", "current_file": self.current, "candidate_file": self.candidate,
        })
        self.assertFalse(res["ok"])
        self.assertFalse(res["promoted"])
        # current is untouched -- the candidate change was NOT promoted.
        with open(self.current, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "alpha beta gamma")
        # confirmed must be exactly True, not a truthy value.
        res2 = op_promote({
            "op": "promote", "current_file": self.current, "candidate_file": self.candidate,
            "confirmed": "yes",
        })
        self.assertFalse(res2["ok"])


if __name__ == "__main__":
    unittest.main()
