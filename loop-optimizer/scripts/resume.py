#!/usr/bin/env python3
"""resume.py -- M1: state.json read/write, idempotent resume + no-progress rule.

``state.json`` is the single mutable resume record (schema, brief §4.6):
  {
    turn, phase, golden_set_version, split_hash, current_prompt_hash,
    no_progress_count, candidate_pending, budget_spent_usd, ts
  }
  phase in {proposed, applied, graded, merged, discarded}

This script makes the turn loop crash-safe and idempotent:

  * op="read"           : load state.json (or a fresh turn-0 init if absent).

  * op="advance"        : record that a phase completed. Writing the SAME phase
                          twice is a no-op (idempotent resume): if the stored
                          phase already equals the requested one for the same
                          turn, nothing changes. Phases must not move backward
                          within a turn.

  * op="record_decision": apply a turn's terminal decision to the no-progress
                          counter and phase, then advance the turn:
                            MERGE / SUB_KEEP  -> reset counter to 0
                            DISCARD / SUB_DROP-> counter += 1
                            HALT              -> terminal; counter UNCHANGED
                          MERGE and SUB_KEEP are BOTH promote decisions: a live
                          staging write (apply_change op=promote + promote_done)
                          happens for each, driven separately by the orchestrator.
                          DISCARD/SUB_DROP/HALT promote nothing. (The per-turn
                          phase set here is moot for the non-HALT cases -- the turn
                          advance immediately resets phase to None; only HALT, which
                          does not advance, keeps its "discarded" phase.)
                          Idempotent: re-recording the same decision for the same
                          turn does not double-count (keyed on ``turn``).

  * op="promote_done"   : mark a promote complete by stamping
                          current_prompt_hash := candidate_prompt_hash. Combined
                          with apply_change.py's "promote first, record after"
                          ordering this gives idempotent merge: if
                          current_prompt_hash already equals the candidate hash,
                          the promote is known-done (M1, S4).

  * op="record_scores" : cache the current prompt's freshly measured scores
                          (last_scored_prompt_hash/last_train/last_heldout) so the
                          next turn can reuse them as before-scores when the prompt
                          is unchanged, skipping a redundant re-run (F-06). Pure
                          cache: never touches turn/phase/counter/decision.

  * op="should_stop"    : evaluate stop conditions against the loop config.

All writes are full-object rewrites of state.json (single record, append-only
logs live elsewhere). ``ts`` is stamped with stdlib datetime (UTC) -- ordinary
runtime, not a workflow decision.
"""

import json
import os
import sys
from datetime import datetime, timezone

try:
    from _common import load_payload, emit
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import load_payload, emit


PHASES = ("proposed", "applied", "graded", "merged", "discarded")
# Ordering used to forbid backward moves WITHIN a turn. "merged" and "discarded"
# are both terminal phases of a turn at the same rank (a turn ends as one or the
# other), so they share rank 3.
PHASE_RANK = {"proposed": 0, "applied": 1, "graded": 2, "merged": 3, "discarded": 3}

RESET_DECISIONS = ("MERGE", "SUB_KEEP")
INCREMENT_DECISIONS = ("DISCARD", "SUB_DROP")
TERMINAL_DECISIONS = ("HALT",)
ALL_DECISIONS = RESET_DECISIONS + INCREMENT_DECISIONS + TERMINAL_DECISIONS


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_state(golden_set_version=None, split_hash=None, current_prompt_hash=None):
    """A fresh turn-1, nothing-done-yet state."""
    return {
        "turn": 1,
        "phase": None,
        "golden_set_version": golden_set_version,
        "split_hash": split_hash,
        "current_prompt_hash": current_prompt_hash,
        "no_progress_count": 0,
        "candidate_pending": False,
        "budget_spent_usd": 0.0,
        # F-06 carry-over cache: the most recent measured scores of the CURRENT
        # prompt and the hash they belong to. Lets the next turn reuse them as its
        # before-scores instead of re-running the Runner on an unchanged prompt.
        "last_scored_prompt_hash": None,
        "last_train": None,
        "last_heldout": None,
        "ts": _now_iso(),
    }


def read_state(path):
    """Load state.json, or return an init state if the file does not exist."""
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return init_state()


def write_state(path, state):
    state = dict(state)
    state["ts"] = _now_iso()
    if path:
        parent = os.path.dirname(os.path.abspath(path))
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    return state


def advance_phase(state, turn, phase, candidate_pending=None, budget_spent_usd=None):
    """Idempotently record that ``phase`` of ``turn`` completed.

    Returns (new_state, changed: bool).

    M1 resume semantics: re-running a phase is a no-op. When an interrupted turn
    is resumed, the orchestrator re-drives that turn from its FIRST phase; the
    already-completed earlier phases must replay silently. So within the current
    in-progress turn, re-issuing an earlier-or-equal-ranked phase is an
    idempotent no-op (state already reflects at least that much progress) rather
    than an error. Only the *new high-water mark* advances the phase.

    The genuine corruption we still reject is a TURN regression: recording a
    phase for a turn older than the current turn (the turn counter only moves
    forward, via record_decision).

    Raises ValueError on an invalid phase or a turn regression.
    """
    if phase not in PHASES:
        raise ValueError("invalid phase {!r}; expected one of {}".format(phase, PHASES))

    new_state = dict(state)
    cur_turn = state.get("turn")
    cur_phase = state.get("phase")

    # Turn regression = corruption (the turn counter is monotonic).
    if cur_turn is not None and turn < cur_turn:
        raise ValueError(
            "cannot record phase for turn {} < current turn {} (turn regression)".format(turn, cur_turn)
        )

    # Replaying an earlier-or-equal phase of the CURRENT turn: idempotent no-op
    # (interrupted-turn resume re-walks completed phases). Side fields may still
    # be refreshed, but the phase high-water mark does not move and changed=False.
    if turn == cur_turn and cur_phase is not None and PHASE_RANK[phase] <= PHASE_RANK[cur_phase]:
        if candidate_pending is not None:
            new_state["candidate_pending"] = candidate_pending
        if budget_spent_usd is not None:
            new_state["budget_spent_usd"] = budget_spent_usd
        return new_state, False

    new_state["turn"] = turn
    new_state["phase"] = phase
    if candidate_pending is not None:
        new_state["candidate_pending"] = candidate_pending
    if budget_spent_usd is not None:
        new_state["budget_spent_usd"] = budget_spent_usd
    return new_state, True


def record_decision(state, turn, decision, budget_spent_usd=None):
    """Apply a turn's terminal decision: update counter + phase + advance turn.

    Returns (new_state, changed: bool). Idempotent per-turn: if this turn's
    decision was already recorded (the state has already advanced past ``turn``),
    it is a no-op so an interrupted->resumed run never double-counts or skips.
    """
    if decision not in ALL_DECISIONS:
        raise ValueError("unknown decision {!r}; expected one of {}".format(decision, ALL_DECISIONS))

    new_state = dict(state)

    # Idempotency: a decision is "recorded" once the turn counter has moved past
    # the turn it applies to. If we've already advanced beyond ``turn``, replay
    # is a no-op. (HALT is terminal and does not advance the turn, so re-recording
    # HALT on the same turn is also a no-op via the phase check below.)
    if state.get("turn", 1) > turn:
        return new_state, False

    if decision in TERMINAL_DECISIONS:
        # HALT: terminal. Stamp phase, leave the counter untouched, do NOT advance
        # the turn (the loop ends here). Re-recording is idempotent.
        if state.get("turn") == turn and state.get("phase") == "discarded" \
                and state.get("halted") is True:
            return new_state, False
        new_state["phase"] = "discarded"
        new_state["halted"] = True
        new_state["candidate_pending"] = False
        if budget_spent_usd is not None:
            new_state["budget_spent_usd"] = budget_spent_usd
        return new_state, True

    if decision in RESET_DECISIONS:
        new_state["no_progress_count"] = 0
        new_state["phase"] = "merged" if decision == "MERGE" else "discarded"
    else:  # INCREMENT_DECISIONS: DISCARD, SUB_DROP
        new_state["no_progress_count"] = state.get("no_progress_count", 0) + 1
        new_state["phase"] = "discarded"

    new_state["candidate_pending"] = False
    if budget_spent_usd is not None:
        new_state["budget_spent_usd"] = budget_spent_usd
    # Advance to the next turn; reset phase for the new turn.
    new_state["turn"] = turn + 1
    new_state["phase"] = None
    # carry the last decision's effects already applied above; the per-turn phase
    # for the *completed* turn is implied by history.jsonl, not state.json.
    return new_state, True


def promote_done(state, candidate_prompt_hash):
    """Stamp current_prompt_hash := candidate hash (idempotent merge marker).

    Returns (new_state, changed). If already equal, no-op (promote known-done).
    """
    new_state = dict(state)
    if state.get("current_prompt_hash") == candidate_prompt_hash:
        return new_state, False
    new_state["current_prompt_hash"] = candidate_prompt_hash
    new_state["candidate_pending"] = False
    return new_state, True


def record_scores(state, prompt_hash, train, heldout):
    """Cache the freshly measured scores of the CURRENT prompt (F-06).

    Returns (new_state, changed). The orchestrator calls this after grading the
    current prompt (turn 1) and after a confirmed promote (the confirm re-run's
    scores). On the next turn, if ``last_scored_prompt_hash`` still equals the
    current prompt hash, those scores are reused as the before-scores and steps
    ①② (re-run + re-grade of the unchanged prompt) are skipped. This NEVER feeds
    the gate a stale score: the hash guard guarantees the prompt is byte-identical
    to what was measured, and the eps margin already covers run-to-run noise. It
    is a pure cache; it does not touch the turn counter, phase, or any decision.
    """
    new_state = dict(state)
    new_state["last_scored_prompt_hash"] = prompt_hash
    new_state["last_train"] = train
    new_state["last_heldout"] = heldout
    return new_state, True


def should_stop(state, n_turns=None, no_progress_k=None,
                max_usd_total=None, perfect=False):
    """Evaluate stop conditions. Returns (stop: bool, reason or None)."""
    if state.get("halted"):
        return True, "HALT (overfitting): terminal"
    if perfect:
        return True, "perfect score: all golden cases pass"
    if n_turns is not None and state.get("turn", 1) > n_turns:
        return True, "max turns reached ({})".format(n_turns)
    if no_progress_k is not None and state.get("no_progress_count", 0) >= no_progress_k:
        return True, "no progress for {} turns".format(no_progress_k)
    if max_usd_total is not None and state.get("budget_spent_usd", 0.0) >= max_usd_total:
        return True, "budget exceeded ({} >= {})".format(state.get("budget_spent_usd"), max_usd_total)
    return False, None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_cli(argv):
    try:
        payload = load_payload(argv)
        op = payload.get("op", "read")
        path = payload.get("state_path")
        state = read_state(path)

        if op == "read":
            emit({"ok": True, "state": state})
            return 0

        if op == "advance":
            new_state, changed = advance_phase(
                state,
                turn=payload["turn"],
                phase=payload["phase"],
                candidate_pending=payload.get("candidate_pending"),
                budget_spent_usd=payload.get("budget_spent_usd"),
            )
            new_state = write_state(path, new_state)
            emit({"ok": True, "changed": changed, "state": new_state})
            return 0

        if op == "record_decision":
            new_state, changed = record_decision(
                state,
                turn=payload["turn"],
                decision=payload["decision"],
                budget_spent_usd=payload.get("budget_spent_usd"),
            )
            new_state = write_state(path, new_state)
            emit({"ok": True, "changed": changed, "state": new_state})
            return 0

        if op == "promote_done":
            new_state, changed = promote_done(state, payload["candidate_prompt_hash"])
            new_state = write_state(path, new_state)
            emit({"ok": True, "changed": changed, "state": new_state})
            return 0

        if op == "record_scores":
            new_state, changed = record_scores(
                state,
                prompt_hash=payload["prompt_hash"],
                train=payload["train"],
                heldout=payload["heldout"],
            )
            new_state = write_state(path, new_state)
            emit({"ok": True, "changed": changed, "state": new_state})
            return 0

        if op == "should_stop":
            stop, reason = should_stop(
                state,
                n_turns=payload.get("n_turns"),
                no_progress_k=payload.get("no_progress_k"),
                max_usd_total=payload.get("max_usd_total"),
                perfect=bool(payload.get("perfect", False)),
            )
            emit({"ok": True, "stop": stop, "reason": reason, "state": state})
            return 0

        raise ValueError("unknown 'op' {!r}".format(op))
    except (ValueError, KeyError, OSError) as exc:
        emit({"ok": False, "reason": "error: {}".format(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
