"""Tests for resume.py -- M1 idempotent state machine + no-progress rule.

Covers the mandated cases:
  - resume idempotency: re-running a phase = no change
  - interrupted -> resumed run has no duplicate / missing turns
  - no_progress_count: reset on MERGE/SUB_KEEP, +1 on DISCARD/SUB_DROP, HALT terminal
  - idempotent promote marker (current_prompt_hash)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resume import (  # noqa: E402
    init_state,
    advance_phase,
    record_decision,
    promote_done,
    record_scores,
    should_stop,
)


class TestAdvanceIdempotency(unittest.TestCase):
    def test_replay_same_phase_is_noop(self):
        s = init_state()
        s, changed1 = advance_phase(s, turn=1, phase="proposed")
        self.assertTrue(changed1)
        # Re-running the exact same phase: idempotent no-op.
        s2, changed2 = advance_phase(s, turn=1, phase="proposed")
        self.assertFalse(changed2)
        self.assertEqual(s2["turn"], 1)
        self.assertEqual(s2["phase"], "proposed")

    def test_forward_progression_within_turn(self):
        s = init_state()
        for phase in ("proposed", "applied", "graded"):
            s, changed = advance_phase(s, turn=1, phase=phase)
            self.assertTrue(changed)
        self.assertEqual(s["phase"], "graded")

    def test_replay_earlier_phase_same_turn_is_noop(self):
        # M1: an interrupted turn is resumed by re-driving it from its first
        # phase. Re-issuing an earlier phase of the CURRENT (not-yet-decided)
        # turn must be a silent no-op, NOT an error -- the phase high-water mark
        # does not regress.
        s = init_state()
        s, _ = advance_phase(s, turn=1, phase="graded")
        s2, changed = advance_phase(s, turn=1, phase="proposed")
        self.assertFalse(changed)
        self.assertEqual(s2["phase"], "graded")  # high-water mark preserved

    def test_turn_regression_rejected(self):
        # Recording a phase for a turn older than the current turn is genuine
        # corruption (the turn counter is monotonic) and must raise.
        s = init_state()
        s, _ = record_decision(s, turn=1, decision="DISCARD")  # now on turn 2
        self.assertEqual(s["turn"], 2)
        with self.assertRaises(ValueError):
            advance_phase(s, turn=1, phase="proposed")

    def test_invalid_phase_rejected(self):
        s = init_state()
        with self.assertRaises(ValueError):
            advance_phase(s, turn=1, phase="bogus")


class TestNoProgressCounter(unittest.TestCase):
    def test_merge_resets_counter(self):
        s = init_state()
        s["no_progress_count"] = 2
        s, changed = record_decision(s, turn=1, decision="MERGE")
        self.assertTrue(changed)
        self.assertEqual(s["no_progress_count"], 0)
        self.assertEqual(s["turn"], 2)  # advanced

    def test_discard_increments_counter(self):
        s = init_state()
        s, _ = record_decision(s, turn=1, decision="DISCARD")
        self.assertEqual(s["no_progress_count"], 1)
        self.assertEqual(s["turn"], 2)

    def test_sub_keep_resets_counter(self):
        s = init_state()
        s["no_progress_count"] = 2
        s, _ = record_decision(s, turn=1, decision="SUB_KEEP")
        self.assertEqual(s["no_progress_count"], 0)

    def test_sub_drop_increments_counter(self):
        s = init_state()
        s["no_progress_count"] = 1
        s, _ = record_decision(s, turn=1, decision="SUB_DROP")
        self.assertEqual(s["no_progress_count"], 2)

    def test_halt_is_terminal_no_counter_change(self):
        s = init_state()
        s["no_progress_count"] = 1
        s, _ = record_decision(s, turn=1, decision="HALT")
        # counter unchanged, turn NOT advanced (terminal), halted flagged
        self.assertEqual(s["no_progress_count"], 1)
        self.assertEqual(s["turn"], 1)
        self.assertTrue(s["halted"])

    def test_record_decision_idempotent_per_turn(self):
        # Recording the same turn's decision twice must not double-count.
        s = init_state()
        s, changed1 = record_decision(s, turn=1, decision="DISCARD")
        self.assertTrue(changed1)
        self.assertEqual(s["no_progress_count"], 1)
        self.assertEqual(s["turn"], 2)
        # Replay the turn-1 decision (e.g. crash before state flush) -> no-op.
        s, changed2 = record_decision(s, turn=1, decision="DISCARD")
        self.assertFalse(changed2)
        self.assertEqual(s["no_progress_count"], 1)
        self.assertEqual(s["turn"], 2)

    def test_halt_replay_idempotent(self):
        s = init_state()
        s, _ = record_decision(s, turn=1, decision="HALT")
        s, changed = record_decision(s, turn=1, decision="HALT")
        self.assertFalse(changed)
        self.assertTrue(s["halted"])


class TestPromoteMarker(unittest.TestCase):
    def test_promote_done_sets_hash(self):
        s = init_state(current_prompt_hash="sha256:old")
        s, changed = promote_done(s, "sha256:new")
        self.assertTrue(changed)
        self.assertEqual(s["current_prompt_hash"], "sha256:new")

    def test_promote_done_idempotent(self):
        s = init_state(current_prompt_hash="sha256:new")
        s, changed = promote_done(s, "sha256:new")
        self.assertFalse(changed)


class TestScoreCarryOver(unittest.TestCase):
    """F-06: record_scores caches the current prompt's scores for reuse next turn,
    without touching the turn counter, phase, or no-progress counter."""

    def test_record_scores_caches_fields(self):
        s = init_state()
        s, changed = record_scores(s, prompt_hash="sha256:abc", train=0.78, heldout=0.70)
        self.assertTrue(changed)
        self.assertEqual(s["last_scored_prompt_hash"], "sha256:abc")
        self.assertEqual(s["last_train"], 0.78)
        self.assertEqual(s["last_heldout"], 0.70)

    def test_record_scores_is_pure_cache(self):
        # Must not advance the turn or disturb the no-progress counter / phase.
        s = init_state()
        s["turn"] = 5
        s["no_progress_count"] = 2
        s["phase"] = "graded"
        s, _ = record_scores(s, "sha256:x", 0.5, 0.5)
        self.assertEqual(s["turn"], 5)
        self.assertEqual(s["no_progress_count"], 2)
        self.assertEqual(s["phase"], "graded")


class TestGraderProvenance(unittest.TestCase):
    """Additive grader-provenance field for the advisory cross-family drift WARN.

    A grader swap is invisible today (state carries golden_set_version + split_hash
    but no grader field; split_goldenset op=verify can't catch a swapped ruler).
    init_state now records grader_version_id alongside the other provenance so the
    non-blocking trust-time WARN can surface it. These tests pin that the field is
    present, defaults to None, is settable, and -- critically -- that adding it did
    NOT change any decision / transition / counter behaviour (the verified core).
    """

    def test_init_state_has_grader_field_default_none(self):
        s = init_state()
        self.assertIn("grader_version_id", s)
        self.assertIsNone(s["grader_version_id"])

    def test_init_state_records_grader_version_id(self):
        s = init_state(grader_version_id="claude-opus-4-8")
        self.assertEqual(s["grader_version_id"], "claude-opus-4-8")

    def test_init_state_records_alongside_other_provenance(self):
        # Sits next to the existing orchestrator-populated provenance, unchanged.
        s = init_state(
            golden_set_version="v2",
            split_hash="sha256:abc",
            grader_version_id="claude-opus-4-8",
        )
        self.assertEqual(s["golden_set_version"], "v2")
        self.assertEqual(s["split_hash"], "sha256:abc")
        self.assertEqual(s["grader_version_id"], "claude-opus-4-8")

    def test_grader_field_does_not_perturb_decisions(self):
        # The provenance field must be inert w.r.t. the state machine: a turn driven
        # to MERGE behaves identically whether or not grader_version_id is set.
        s_no = init_state()
        s_no, _ = record_decision(s_no, turn=1, decision="MERGE")
        s_yes = init_state(grader_version_id="claude-opus-4-8")
        s_yes, _ = record_decision(s_yes, turn=1, decision="MERGE")
        self.assertEqual(s_no["turn"], s_yes["turn"])
        self.assertEqual(s_no["no_progress_count"], s_yes["no_progress_count"])
        self.assertEqual(s_no["phase"], s_yes["phase"])
        # The field rides along untouched by the decision.
        self.assertEqual(s_yes["grader_version_id"], "claude-opus-4-8")

    def test_grader_field_does_not_perturb_stop(self):
        # should_stop must ignore the provenance field entirely.
        s = init_state(grader_version_id="claude-opus-4-8")
        s["turn"] = 3
        stop, reason = should_stop(s, n_turns=10, no_progress_k=3, max_usd_total=20.0)
        self.assertFalse(stop)
        self.assertIsNone(reason)


class TestStopConditions(unittest.TestCase):
    def test_max_turns(self):
        s = init_state()
        s["turn"] = 11
        stop, reason = should_stop(s, n_turns=10)
        self.assertTrue(stop)
        self.assertIn("max turns", reason)

    def test_no_progress_k(self):
        s = init_state()
        s["no_progress_count"] = 3
        stop, reason = should_stop(s, no_progress_k=3)
        self.assertTrue(stop)
        self.assertIn("no progress", reason)

    def test_budget(self):
        s = init_state()
        s["budget_spent_usd"] = 20.5
        stop, reason = should_stop(s, max_usd_total=20.0)
        self.assertTrue(stop)
        self.assertIn("budget", reason)

    def test_perfect(self):
        s = init_state()
        stop, reason = should_stop(s, perfect=True)
        self.assertTrue(stop)

    def test_halt_stops(self):
        s = init_state()
        s["halted"] = True
        stop, reason = should_stop(s)
        self.assertTrue(stop)

    def test_keep_going(self):
        s = init_state()
        s["turn"] = 3
        s["no_progress_count"] = 1
        s["budget_spent_usd"] = 5.0
        stop, reason = should_stop(s, n_turns=10, no_progress_k=3, max_usd_total=20.0)
        self.assertFalse(stop)
        self.assertIsNone(reason)


class TestInterruptedResumeNoDuplicatesOrGaps(unittest.TestCase):
    """Simulate a full run with a mid-turn crash and a resume; assert the turn
    sequence has no duplicate and no missing turns."""

    def _run_turn(self, s, turn, decision, crash_after_phase=None):
        """Drive one turn through its phases + decision. If ``crash_after_phase``
        is set, stop after that phase (simulating interruption) and return the
        partial state without recording the decision."""
        phases = ["proposed", "applied", "graded"]
        for ph in phases:
            s, _ = advance_phase(s, turn=turn, phase=ph)
            if ph == crash_after_phase:
                return s, False  # interrupted: decision NOT recorded
        s, _ = record_decision(s, turn=turn, decision=decision)
        return s, True

    def test_clean_run_turn_sequence(self):
        s = init_state()
        completed = []
        plan = [("DISCARD", None), ("MERGE", None), ("DISCARD", None)]
        for i, (decision, crash) in enumerate(plan, start=1):
            before_turn = s["turn"]
            s, done = self._run_turn(s, before_turn, decision, crash)
            self.assertTrue(done)
            completed.append(before_turn)
        # turns recorded strictly 1,2,3 -- no dup, no gap
        self.assertEqual(completed, [1, 2, 3])
        self.assertEqual(s["turn"], 4)
        self.assertEqual(s["no_progress_count"], 1)  # DISCARD, MERGE(reset), DISCARD

    def test_crash_mid_turn_then_resume_no_dup_no_gap(self):
        # Turn 1 completes (DISCARD). Turn 2 crashes after "applied" (decision not
        # recorded). On resume we re-drive turn 2 from scratch; the decision is
        # then recorded exactly once. Turn 3 completes. Final: turns 1,2,3 each
        # recorded once.
        s = init_state()

        # turn 1 clean
        s, done1 = self._run_turn(s, s["turn"], "DISCARD")
        self.assertTrue(done1)
        self.assertEqual(s["turn"], 2)
        np_after_t1 = s["no_progress_count"]
        self.assertEqual(np_after_t1, 1)

        # turn 2 crashes after "applied" -> still on turn 2, decision NOT recorded
        s, done2 = self._run_turn(s, s["turn"], "MERGE", crash_after_phase="applied")
        self.assertFalse(done2)
        self.assertEqual(s["turn"], 2)  # did NOT advance
        self.assertEqual(s["phase"], "applied")
        self.assertEqual(s["no_progress_count"], 1)  # MERGE not yet applied

        # ---- RESUME ---- re-drive turn 2 from its phases; advance_phase replays
        # the already-done "proposed"/"applied" as no-ops, then records MERGE once.
        s, done2b = self._run_turn(s, s["turn"], "MERGE")
        self.assertTrue(done2b)
        self.assertEqual(s["turn"], 3)  # advanced exactly once
        self.assertEqual(s["no_progress_count"], 0)  # MERGE reset, applied once

        # Replaying turn-2's MERGE again (double resume) is a no-op: no double reset/skip.
        s, changed = record_decision(s, turn=2, decision="MERGE")
        self.assertFalse(changed)
        self.assertEqual(s["turn"], 3)

        # turn 3 clean
        s, done3 = self._run_turn(s, s["turn"], "DISCARD")
        self.assertTrue(done3)
        self.assertEqual(s["turn"], 4)
        self.assertEqual(s["no_progress_count"], 1)

    def test_resume_after_decision_recorded_but_before_state_observed(self):
        # Decision recorded (turn advanced) but the orchestrator re-issues the
        # same record_decision after a crash. Must be a no-op (no skipped turn).
        s = init_state()
        s, _ = record_decision(s, turn=1, decision="MERGE")
        self.assertEqual(s["turn"], 2)
        # crash + replay
        s, changed = record_decision(s, turn=1, decision="MERGE")
        self.assertFalse(changed)
        self.assertEqual(s["turn"], 2)  # NOT advanced to 3


if __name__ == "__main__":
    unittest.main()
