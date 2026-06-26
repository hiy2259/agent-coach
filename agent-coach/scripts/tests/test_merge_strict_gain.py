"""Tests for B: the merge gate requires a STRICTLY positive train gain, so a
+0.0 tie never merges even when eps_train == 0 (degenerate calibration)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from score_compare import score_compare  # noqa: E402


class TestStrictTrainGain(unittest.TestCase):
    def test_zero_eps_tie_does_not_merge(self):
        # eps_train=0 and a flat train score: must NOT merge (it would be a no-op).
        res = score_compare(train_b=1.0, train_a=1.0, held_b=1.0, held_a=1.0,
                            eps_train=0.0, eps_heldout=0.0, mode="merge")
        self.assertEqual(res["decision"], "DISCARD")

    def test_zero_eps_real_gain_merges(self):
        # eps_train=0 but a real positive train gain, no held-out regress: MERGE.
        res = score_compare(train_b=0.80, train_a=0.90, held_b=0.80, held_a=0.80,
                            eps_train=0.0, eps_heldout=0.0, mode="merge")
        self.assertEqual(res["decision"], "MERGE")

    def test_floored_eps_blocks_subfloor_gain(self):
        # With a 0.02 floor, a +0.01 gain is within noise -> DISCARD.
        res = score_compare(train_b=0.80, train_a=0.81, held_b=0.80, held_a=0.80,
                            eps_train=0.02, eps_heldout=0.02, mode="merge")
        self.assertEqual(res["decision"], "DISCARD")

    def test_clear_gain_above_floor_merges(self):
        res = score_compare(train_b=0.80, train_a=0.86, held_b=0.80, held_a=0.80,
                            eps_train=0.02, eps_heldout=0.02, mode="merge")
        self.assertEqual(res["decision"], "MERGE")


if __name__ == "__main__":
    unittest.main()
