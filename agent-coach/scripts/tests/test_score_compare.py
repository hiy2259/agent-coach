"""Tests for score_compare.py -- S1/S2/S7 merge gate (pure arithmetic).

Covers the mandated cases:
  - a change inside eps is NOT merged (noise, not progress)
  - held-out noise within eps_heldout does NOT false-HALT
  - genuine overfit (train up, held-out down beyond eps_heldout) DOES HALT
  - subtraction SUB_KEEP vs SUB_DROP
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from score_compare import score_compare  # noqa: E402


EPS_T = 0.03
EPS_H = 0.04


class TestMergeMode(unittest.TestCase):
    def test_real_gain_merges(self):
        # train +0.08 (>= eps_train), held-out +0.05 (no regress) -> MERGE
        r = score_compare(0.70, 0.78, 0.65, 0.70, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "MERGE")

    def test_gain_exactly_at_threshold_merges(self):
        # train_after == train_before + eps_train exactly (>= is inclusive) -> MERGE
        r = score_compare(0.70, 0.73, 0.65, 0.65, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "MERGE")

    def test_change_inside_eps_not_merged(self):
        # train only +0.01 < eps_train 0.03 -> noise -> DISCARD (mandated)
        r = score_compare(0.78, 0.79, 0.70, 0.70, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "DISCARD")

    def test_train_gain_but_heldout_noise_within_margin_merges_not_halt(self):
        # train +0.08 real; held-out -0.03 which is within eps_heldout 0.04.
        # Must NOT HALT and (since gain is real and no real regress) -> MERGE.
        r = score_compare(0.70, 0.78, 0.70, 0.67, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "MERGE")
        self.assertNotEqual(r["decision"], "HALT")

    def test_heldout_noise_within_eps_does_not_false_halt(self):
        # train rose a hair (+0.01, below eps so not a real gain) and held-out
        # dipped within margin (-0.03 < eps_heldout). This is the classic false
        # HALT trap: must be DISCARD, NOT HALT (mandated).
        r = score_compare(0.78, 0.79, 0.70, 0.67, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "DISCARD")
        self.assertNotEqual(r["decision"], "HALT")

    def test_genuine_overfit_halts(self):
        # train up +0.07, held-out down -0.12 (beyond eps_heldout 0.04) -> HALT (mandated)
        r = score_compare(0.78, 0.85, 0.70, 0.58, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "HALT")
        self.assertIn("overfitting", r["reason"])

    def test_subeps_train_rise_with_heldout_crater_discards_not_halt(self):
        # F-08: train rose only +0.01 (below eps_train) while held-out cratered
        # -0.12 (beyond eps_heldout). There is no REAL train gain, so this is not a
        # demonstrated overfit trajectory -> DISCARD (blocked), NOT a terminal HALT.
        r = score_compare(0.78, 0.79, 0.70, 0.58, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "DISCARD")
        self.assertNotEqual(r["decision"], "HALT")

    def test_heldout_regress_exactly_at_margin_is_not_halt(self):
        # held-out_after == held_before - eps_heldout exactly. HALT needs strict
        # `<`, MERGE needs `>=`; at the boundary it is NOT a real regress.
        # train rose only +0.01 (below eps) so overall -> DISCARD, not HALT.
        r = score_compare(0.78, 0.79, 0.70, 0.66, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "DISCARD")

    def test_heldout_just_beyond_margin_with_real_train_gain_halts(self):
        # held-out_after just below the floor (held_b - eps_h - tiny) + real train
        # gain -> HALT.
        r = score_compare(0.70, 0.80, 0.70, 0.6599, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "HALT")

    def test_train_flat_heldout_up_discards(self):
        # No train movement, held-out up: not a train gain -> DISCARD (not HALT).
        r = score_compare(0.70, 0.70, 0.65, 0.72, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "DISCARD")

    def test_train_drop_heldout_drop_discards_not_halt(self):
        # train fell -> HALT condition (train must RISE) is false -> DISCARD.
        r = score_compare(0.78, 0.70, 0.70, 0.50, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "DISCARD")

    def test_default_mode_is_merge(self):
        r = score_compare(0.70, 0.78, 0.65, 0.70, EPS_T, EPS_H)
        self.assertEqual(r["mode"], "merge")


class TestSubtractionMode(unittest.TestCase):
    def test_sub_keep_when_harmless(self):
        # Removing a rule: train flat, held-out flat -> within both margins -> SUB_KEEP
        r = score_compare(0.78, 0.78, 0.70, 0.70, EPS_T, EPS_H, mode="subtraction")
        self.assertEqual(r["decision"], "SUB_KEEP")

    def test_sub_keep_with_small_dip_within_margin(self):
        # train -0.02 (within eps_train), held-out -0.03 (within eps_heldout) -> SUB_KEEP
        r = score_compare(0.78, 0.76, 0.70, 0.67, EPS_T, EPS_H, mode="subtraction")
        self.assertEqual(r["decision"], "SUB_KEEP")

    def test_sub_drop_when_train_falls_too_much(self):
        # train -0.10 beyond eps_train -> the rule mattered -> SUB_DROP (restore)
        r = score_compare(0.78, 0.68, 0.70, 0.70, EPS_T, EPS_H, mode="subtraction")
        self.assertEqual(r["decision"], "SUB_DROP")

    def test_sub_drop_when_heldout_falls_too_much(self):
        # held-out -0.10 beyond eps_heldout -> SUB_DROP
        r = score_compare(0.78, 0.78, 0.70, 0.60, EPS_T, EPS_H, mode="subtraction")
        self.assertEqual(r["decision"], "SUB_DROP")

    def test_sub_keep_boundary_inclusive(self):
        # exactly at the floor on both -> inclusive >= -> SUB_KEEP
        r = score_compare(0.78, 0.75, 0.70, 0.66, EPS_T, EPS_H, mode="subtraction")
        self.assertEqual(r["decision"], "SUB_KEEP")


class TestFloatBoundary(unittest.TestCase):
    """F-02: fractional scores that land EXACTLY on a threshold must resolve in
    the intended (inclusive) direction despite IEEE-754 dust. These cases use
    values where naive >=/< flips the verdict (0.1+0.2 != 0.3, 0.8-0.1 != 0.7).
    Each FAILS on the pre-fix (no-tolerance) gate and PASSES with _TOL."""

    def test_real_gain_exactly_on_merge_line_is_not_false_discarded(self):
        # train 0.1 -> 0.3 is a real +0.2 gain == eps_train exactly. But
        # 0.1 + 0.2 == 0.30000000000000004 > 0.3, so a bare >= would DISCARD it.
        self.assertNotEqual(0.1 + 0.2, 0.3)  # document the dust
        r = score_compare(0.1, 0.3, 0.5, 0.5, eps_train=0.2, eps_heldout=0.04, mode="merge")
        self.assertEqual(r["decision"], "MERGE")

    def test_heldout_dip_exactly_on_margin_does_not_false_halt(self):
        # held-out 0.8 -> 0.7 falls exactly eps_heldout (0.1) -> within margin,
        # NOT a real regress. But 0.8 - 0.1 == 0.7000000000000001 > 0.7, so a bare
        # `<` would read it as a regress and (train having really risen) HALT --
        # killing the whole run on noise. Must MERGE (real train gain, held in band).
        self.assertNotEqual(0.8 - 0.1, 0.7)  # document the dust
        r = score_compare(0.5, 0.7, 0.8, 0.7, eps_train=0.1, eps_heldout=0.1, mode="merge")
        self.assertNotEqual(r["decision"], "HALT")
        self.assertEqual(r["decision"], "MERGE")

    def test_subtraction_loss_exactly_on_floor_is_kept(self):
        # removal drops held-out exactly eps_heldout -> within margin -> SUB_KEEP.
        r = score_compare(0.5, 0.5, 0.8, 0.7, eps_train=0.1, eps_heldout=0.1, mode="subtraction")
        self.assertEqual(r["decision"], "SUB_KEEP")


class TestConfirmGate(unittest.TestCase):
    """S7 / F-01: a promote decision is provisional until a confirm re-run
    reproduces it. score_compare expresses this with confirm_required / confirmed
    and downgrades when the confirm scores contradict the first measurement."""

    def test_merge_without_confirm_is_provisional(self):
        r = score_compare(0.70, 0.80, 0.65, 0.70, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "MERGE")
        self.assertTrue(r["confirm_required"])
        self.assertFalse(r["confirmed"])

    def test_merge_confirmed_when_gain_holds(self):
        # confirm re-run reproduces the gain against a FRESHLY re-measured baseline
        # (train_b2/held_b2) -> final, confirmed MERGE.
        r = score_compare(0.70, 0.80, 0.65, 0.70, EPS_T, EPS_H, mode="merge",
                          train_a2=0.79, held_a2=0.69, train_b2=0.70, held_b2=0.65)
        self.assertEqual(r["decision"], "MERGE")
        self.assertTrue(r["confirmed"])
        self.assertFalse(r["confirm_required"])
        self.assertTrue(r["confirm"]["baseline_remeasured"])

    def test_merge_downgraded_when_confirm_evaporates(self):
        # the gain vanishes on the fresh run (candidate back to the re-measured
        # baseline) -> noise.
        r = score_compare(0.70, 0.80, 0.65, 0.70, EPS_T, EPS_H, mode="merge",
                          train_a2=0.70, held_a2=0.70, train_b2=0.70, held_b2=0.65)
        self.assertEqual(r["decision"], "DISCARD")
        self.assertFalse(r["confirmed"])
        self.assertIn("confirm", r["reason"])

    def test_sub_keep_downgraded_to_sub_drop_when_confirm_shows_loss(self):
        # provisional SUB_KEEP, but the confirm run reveals a real train loss
        # against the re-measured baseline.
        r = score_compare(0.78, 0.78, 0.70, 0.70, EPS_T, EPS_H, mode="subtraction",
                          train_a2=0.60, held_a2=0.70, train_b2=0.78, held_b2=0.70)
        self.assertEqual(r["decision"], "SUB_DROP")
        self.assertFalse(r["confirmed"])

    def test_non_promote_decisions_need_no_confirm(self):
        # A DISCARD is never "confirm_required" (nothing to promote).
        r = score_compare(0.78, 0.785, 0.70, 0.70, EPS_T, EPS_H, mode="merge")
        self.assertEqual(r["decision"], "DISCARD")
        self.assertFalse(r["confirm_required"])


class TestConfirmBaselineIndependence(unittest.TestCase):
    """H4: the confirm re-run must compare the candidate's fresh score against a
    FRESHLY re-measured baseline (train_b2/held_b2), not reuse the first-call
    baseline (train_b/held_b). Reusing it correlates the two gate checks and
    roughly halves confirm's noise filtering. The code ENFORCES the re-measured
    baseline rather than trusting the orchestrator to supply it (S2/S7)."""

    def test_confirm_after_scores_without_remeasured_baseline_is_an_error(self):
        # train_a2/held_a2 given but no train_b2/held_b2 -> contract violation,
        # never a silent fallback to the (correlated) first baseline.
        with self.assertRaises(ValueError):
            score_compare(0.70, 0.80, 0.65, 0.70, EPS_T, EPS_H, mode="merge",
                          train_a2=0.79, held_a2=0.69)

    def test_partial_remeasured_baseline_is_an_error(self):
        # one of the pair missing is still a violation (no half-independent gate).
        with self.assertRaises(ValueError):
            score_compare(0.70, 0.80, 0.65, 0.70, EPS_T, EPS_H, mode="merge",
                          train_a2=0.79, held_a2=0.69, train_b2=0.70)  # held_b2 absent

    def test_independent_baseline_flips_a_reused_baseline_merge_to_discard(self):
        # The crux of H4. First gate: train 0.60 -> 0.80 clears +eps -> provisional
        # MERGE. Confirm: the candidate re-measures at 0.80 (the gain "holds"
        # against the OLD low 0.60 baseline). But the baseline ALSO re-measures
        # high, at 0.80 -- so against the independent baseline there is NO gain and
        # the merge is correctly rejected as noise.
        r = score_compare(0.60, 0.80, 0.60, 0.65, EPS_T, EPS_H, mode="merge",
                          train_a2=0.80, held_a2=0.65, train_b2=0.80, held_b2=0.65)
        self.assertEqual(r["decision"], "DISCARD")
        self.assertFalse(r["confirmed"])

    def test_reusing_stale_baseline_would_have_wrongly_confirmed(self):
        # Same fresh candidate score (0.80) as above, but the confirm baseline is
        # the stale low 0.60 (what the H4 bug did). It WRONGLY confirms -- this
        # documents exactly the false MERGE the re-measured baseline prevents.
        buggy = score_compare(0.60, 0.80, 0.60, 0.65, EPS_T, EPS_H, mode="merge",
                              train_a2=0.80, held_a2=0.65, train_b2=0.60, held_b2=0.60)
        self.assertEqual(buggy["decision"], "MERGE")
        self.assertTrue(buggy["confirmed"])


if __name__ == "__main__":
    unittest.main()
