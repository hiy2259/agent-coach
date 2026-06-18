#!/usr/bin/env python3
"""score_compare.py -- S1/S2/S7: the merge gate. PURE ARITHMETIC.

The single most important code in the skill: it decides MERGE / DISCARD / HALT
(or SUB_KEEP / SUB_DROP for subtraction turns) from scores alone. NO model
judgment ever enters here -- a model must never decide "it looks better".

The margins ``eps_train`` / ``eps_heldout`` are measurement noise produced by
calibrate_noise.py (Runner-output variance). A change inside the noise band is
luck, not progress.

------------------------------------------------------------------- merge mode
  MERGE   iff  train_a >= train_b + eps_train          (real gain on train)
          AND  train_a >  train_b                        (strictly positive; a
                                                          +0.0 tie never merges,
                                                          even if eps_train == 0)
          AND  held_a  >= held_b  - eps_heldout         (no real held-out regress)
          AND  the gain survives the confirm re-run (S7; see below)
  HALT    iff  train_a >= train_b + eps_train            (a REAL train gain...)
          AND  held_a  <  held_b - eps_heldout           (...but held-out really fell)
                                                          => overfitting, terminal
  DISCARD otherwise

  Note the held-out margin is SYMMETRIC: -eps_heldout gates the merge AND the
  HALT, so ordinary held-out noise does not trigger a false HALT.

  HALT keys on the SAME `train_gain_ok` as MERGE -- a *real* gain beyond noise,
  not a sub-eps wiggle (F-08). An overfit that only nudges train within the noise
  band while cratering held-out is a DISCARD (blocked, but not terminal): there is
  no demonstrated generalization failure to justify killing the whole run, just a
  change that didn't earn a merge. Terminal HALT is reserved for the unambiguous
  overfit trajectory: train genuinely rose AND held-out genuinely fell.

  Precedence: MERGE is checked first. The MERGE and HALT regions are disjoint
  by construction (both require train_gain_ok; MERGE needs held_a >= held_b -
  eps_heldout, HALT needs held_a < held_b - eps_heldout -- exact complements), so
  order does not change the verdict; we evaluate MERGE, then HALT, then DISCARD.

------------------------------------------------------------- subtraction mode
  SUB_KEEP iff train_a >= train_b - eps_train            (no real train loss)
           AND held_a  >= held_b  - eps_heldout           (no real held-out loss)
           AND the parity survives the confirm re-run (S7)
  SUB_DROP otherwise  (restore the removed rule)

--------------------------------------------------------- floating-point safety
  All inequalities are evaluated with a tiny tolerance ``_TOL`` (1e-9) so a
  value sitting EXACTLY on a threshold resolves in the intended, inclusive
  direction. Without it, IEEE-754 dust (the classic ``0.1 + 0.2 ==
  0.30000000000000004``) silently flips boundary verdicts: a real gain landing
  on the merge line is DISCARDed, and -- far worse -- an ordinary held-out dip
  landing on the margin flips a safe run into a *terminal false HALT*. Scores
  are pass-fractions (Sigma pass / Sigma total); for any realistic golden set
  the smallest gap between two genuinely distinct score levels is orders of
  magnitude larger than 1e-9, so the tolerance only ever absorbs float dust, it
  never merges two truly different scores. calibrate_noise.py keeps the same
  discipline (it snaps sub-1e-12 variance to 0).

----------------------------------------------------------- confirm re-run (S7)
  The Grader runs at temperature 0, so re-grading the SAME text is a no-op
  (zero variance). Real noise comes from the RUNNER producing different outputs
  across runs. So a promote decision (MERGE / SUB_KEEP) is only FINAL after a
  fresh Runner re-run + re-grade reproduces it. This gate enforces that in CODE,
  not prose:

    * Call once with just (train_b, train_a, ...). If the provisional verdict is
      MERGE / SUB_KEEP it is returned with ``confirm_required: true`` and
      ``confirmed: false`` -- a *provisional* verdict the orchestrator must not
      promote yet.
    * Re-run BOTH the candidate AND the current (baseline) prompt, re-grade both,
      and call AGAIN passing the confirm after-scores ``train_a2`` / ``held_a2``
      AND the RE-MEASURED baseline ``train_b2`` / ``held_b2``. The same
      inequalities are re-checked against the fresh scores -- the candidate's new
      score against the baseline's NEW score. Only if they still hold is the
      verdict returned with ``confirmed: true``; otherwise it is downgraded to
      DISCARD / SUB_DROP (the gain was noise).

  WHY re-measure the baseline (H4). The point of confirm is a SECOND INDEPENDENT
  measurement of the same comparison. The first gate checks
  ``train_a1 >= train_b + eps``; if confirm reused that same ``train_b`` it would
  check ``train_a2 >= train_b + eps`` -- two checks sharing one term, so a
  baseline that happened to be drawn LOW slips BOTH past the gate at once. That
  positive correlation roughly halves confirm's power to reject noise (a ~2x
  higher false-MERGE rate, the held-out guard included, persisting at higher
  k_calib). Re-running the baseline makes the confirm check statistically
  independent of the first -- which is the whole reason confirm exists. So this
  code REQUIRES ``train_b2`` / ``held_b2`` whenever confirm after-scores are
  supplied: a confirm that re-ran the candidate must also have re-run the current
  prompt (S2/S7 -- enforced in code, not trusted to prose).

  apply_change.py op=promote refuses to promote without ``confirmed: true``, so
  a noise change can never be baked in by skipping confirm (S2/S7).

Input JSON:
  {
    "train_b": 0.70, "train_a": 0.78,
    "held_b":  0.65, "held_a":  0.70,
    "eps_train": 0.03, "eps_heldout": 0.04,
    "mode": "merge" | "subtraction",    # default "merge"
    "train_a2": 0.77, "held_a2": 0.69,  # confirm re-run AFTER-scores (candidate)
    "train_b2": 0.71, "held_b2": 0.65   # confirm re-run RE-MEASURED baseline (current);
                                        # REQUIRED once train_a2/held_a2 are given (H4)
  }

Output JSON:
  {
    "decision": "MERGE"|"DISCARD"|"HALT"|"SUB_KEEP"|"SUB_DROP",
    "mode": "...",
    "reason": "...",
    "deltas": { "train": <train_a-train_b>, "heldout": <held_a-held_b> },
    "thresholds": { ... },          # the exact inequalities evaluated
    "confirm_required": <bool>,     # true: provisional, run confirm + call again
    "confirmed": <bool>,            # true: confirm re-run reproduced the verdict
    "confirm": { ... }              # present once confirm scores were supplied
  }

The ``decision`` string matches the ``history.jsonl`` ``decision`` enum exactly.
"""

import sys

try:
    from _common import load_payload, emit
except ImportError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import load_payload, emit


# Floating-point tolerance for every gate inequality (see module docstring).
_TOL = 1e-9


def _ge(x, y):
    """x >= y, tolerant: x within _TOL below y still counts as >= (inclusive)."""
    return x >= y - _TOL


def _gt(x, y):
    """x > y, tolerant: x must clear y by more than float dust to count."""
    return x > y + _TOL


def _lt(x, y):
    """x < y, tolerant: the exact complement of _ge(x, y)."""
    return x < y - _TOL


def _num(payload, key):
    if key not in payload or payload[key] is None:
        raise ValueError("missing required numeric field '{}'".format(key))
    try:
        return float(payload[key])
    except (TypeError, ValueError):
        raise ValueError("field '{}' must be a number, got {!r}".format(key, payload[key]))


def _opt_num(payload, key):
    """Parse an OPTIONAL numeric field; return None when absent/null."""
    if payload.get(key) is None:
        return None
    try:
        return float(payload[key])
    except (TypeError, ValueError):
        raise ValueError("field '{}' must be a number if provided, got {!r}".format(key, payload[key]))


def compare_merge(train_b, train_a, held_b, held_a, eps_train, eps_heldout):
    """Merge-mode PROVISIONAL decision (pre-confirm). Returns a result dict."""
    train_delta = train_a - train_b
    held_delta = held_a - held_b

    # Beyond train noise AND a strictly positive gain. The strict `> train_b`
    # is belt-and-suspenders for the degenerate eps_train == 0 case: without it
    # a +0.0 tie would satisfy `>= train_b + 0` and merge a no-op as "progress"
    # (calibrate_noise floors eps at 0.02, but a hand-passed eps=0 must still be
    # safe here). Both comparisons are _TOL-tolerant so a value exactly on the
    # line resolves the intended way instead of on float dust.
    train_gain_ok = _ge(train_a, train_b + eps_train) and _gt(train_a, train_b)
    held_no_regress = _ge(held_a, held_b - eps_heldout)      # within held-out margin
    held_real_regress = _lt(held_a, held_b - eps_heldout)    # beyond held-out margin
    train_rose = _gt(train_a, train_b)

    thresholds = {
        "train_merge_threshold": train_b + eps_train,
        "heldout_floor": held_b - eps_heldout,
        "train_gain_ok": train_gain_ok,
        "held_no_regress": held_no_regress,
        "train_rose": train_rose,
        "held_real_regress": held_real_regress,
    }
    deltas = {"train": train_delta, "heldout": held_delta}

    if train_gain_ok and held_no_regress:
        return {
            "decision": "MERGE",
            "mode": "merge",
            "reason": "train gain {:+.4f} >= eps_train {} AND held-out {:+.4f} within -eps_heldout {}".format(
                train_delta, eps_train, held_delta, eps_heldout
            ),
            "deltas": deltas,
            "thresholds": thresholds,
        }
    if train_gain_ok and held_real_regress:
        return {
            "decision": "HALT",
            "mode": "merge",
            "reason": "overfitting: real train gain {:+.4f} (>= eps_train {}) but held-out fell {:+.4f} beyond -eps_heldout {}".format(
                train_delta, eps_train, held_delta, eps_heldout
            ),
            "deltas": deltas,
            "thresholds": thresholds,
        }
    return {
        "decision": "DISCARD",
        "mode": "merge",
        "reason": "no real gain: train {:+.4f} (need >= eps_train {}) / held-out {:+.4f}".format(
            train_delta, eps_train, held_delta
        ),
        "deltas": deltas,
        "thresholds": thresholds,
    }


def compare_subtraction(train_b, train_a, held_b, held_a, eps_train, eps_heldout):
    """Subtraction-mode PROVISIONAL decision (pre-confirm). Returns a result dict."""
    train_delta = train_a - train_b
    held_delta = held_a - held_b

    train_no_loss = _ge(train_a, train_b - eps_train)
    held_no_loss = _ge(held_a, held_b - eps_heldout)

    thresholds = {
        "train_floor": train_b - eps_train,
        "heldout_floor": held_b - eps_heldout,
        "train_no_loss": train_no_loss,
        "held_no_loss": held_no_loss,
    }
    deltas = {"train": train_delta, "heldout": held_delta}

    if train_no_loss and held_no_loss:
        return {
            "decision": "SUB_KEEP",
            "mode": "subtraction",
            "reason": "removal harmless: train {:+.4f} within -eps_train {} AND held-out {:+.4f} within -eps_heldout {}".format(
                train_delta, eps_train, held_delta, eps_heldout
            ),
            "deltas": deltas,
            "thresholds": thresholds,
        }
    return {
        "decision": "SUB_DROP",
        "mode": "subtraction",
        "reason": "removal hurt: train {:+.4f} or held-out {:+.4f} fell beyond margin; restore the rule".format(
            train_delta, held_delta
        ),
        "deltas": deltas,
        "thresholds": thresholds,
    }


def score_compare(train_b, train_a, held_b, held_a, eps_train, eps_heldout,
                  mode="merge", train_a2=None, held_a2=None,
                  train_b2=None, held_b2=None):
    """Dispatch to merge / subtraction comparison, then apply the confirm gate.

    No policy verdict ever raises. A promote decision (MERGE / SUB_KEEP) is only
    returned as FINAL (``confirmed: true``) when the confirm after-scores
    ``train_a2`` / ``held_a2`` AND the re-measured baseline ``train_b2`` /
    ``held_b2`` are supplied AND re-checking the same inequalities against them
    still yields the same verdict. Without confirm scores a promote decision is
    returned PROVISIONALLY (``confirm_required: true``); if the confirm scores
    contradict it, it is downgraded to DISCARD / SUB_DROP.

    The ONE input-contract violation that raises ValueError (caught by run_cli ->
    ``ok: false``): supplying confirm after-scores WITHOUT the re-measured baseline
    (train_b2/held_b2). Reusing the first-call baseline would correlate the two
    gate checks (H4); re-measuring it is mandatory, so its absence is an error,
    not a silent fallback.
    """
    # A negative margin is nonsensical input (calibrate never produces one) and
    # would make the gate too permissive; clamp to 0 defensively.
    eps_train = max(eps_train, 0.0)
    eps_heldout = max(eps_heldout, 0.0)

    cmp_fn = compare_subtraction if mode == "subtraction" else compare_merge
    promote_decision = "SUB_KEEP" if mode == "subtraction" else "MERGE"
    downgrade_decision = "SUB_DROP" if mode == "subtraction" else "DISCARD"

    result = cmp_fn(train_b, train_a, held_b, held_a, eps_train, eps_heldout)

    # Non-promote verdicts (DISCARD / HALT / SUB_DROP) need no confirm: HALT is
    # terminal and DISCARD/SUB_DROP do not promote anything.
    if result["decision"] != promote_decision:
        result["confirm_required"] = False
        result["confirmed"] = False
        return result

    # Provisional promote with no confirm scores yet: the orchestrator must run
    # the confirm re-run and call again. apply_change refuses promote until then.
    if train_a2 is None or held_a2 is None:
        result["confirm_required"] = True
        result["confirmed"] = False
        return result

    # Confirm after-scores were supplied -> the re-measured baseline must be too.
    # Reusing the first-call baseline (train_b/held_b) here would correlate the
    # two gate checks and roughly halve confirm's noise filtering (H4). We require
    # the re-measured baseline in code rather than trust prose to supply it.
    if train_b2 is None or held_b2 is None:
        raise ValueError(
            "confirm requires a RE-MEASURED baseline: pass train_b2 AND held_b2 "
            "(re-run + re-grade the CURRENT prompt at confirm time, not only the "
            "candidate). Omitting them and reusing the first-call baseline "
            "correlates the two gate checks and roughly halves confirm's noise "
            "filtering (H4)."
        )

    # Confirm: re-check the SAME inequalities against the fresh re-run scores --
    # the candidate's new score against the baseline's NEWLY re-measured score, so
    # the two gate checks are statistically independent (H4).
    confirm = cmp_fn(train_b2, train_a2, held_b2, held_a2, eps_train, eps_heldout)
    confirm_info = {
        "decision": confirm["decision"],
        "deltas": confirm["deltas"],
        "baseline_remeasured": True,
        "confirm_baseline": {"train_b2": train_b2, "held_b2": held_b2},
    }

    if confirm["decision"] == promote_decision:
        result["confirmed"] = True
        result["confirm_required"] = False
        result["confirm"] = confirm_info
        return result

    # The gain / parity evaporated on a fresh, independently-baselined run -> it
    # was noise. Downgrade.
    return {
        "decision": downgrade_decision,
        "mode": result["mode"],
        "reason": "provisional {} did not survive the confirm re-run ({}); treat as noise".format(
            promote_decision, confirm["reason"]
        ),
        "deltas": result["deltas"],
        "thresholds": result["thresholds"],
        "confirm_required": False,
        "confirmed": False,
        "confirm": confirm_info,
    }


def run_cli(argv):
    try:
        payload = load_payload(argv)
        mode = payload.get("mode", "merge")
        if mode not in ("merge", "subtraction"):
            raise ValueError("mode must be 'merge' or 'subtraction', got {!r}".format(mode))
        result = score_compare(
            train_b=_num(payload, "train_b"),
            train_a=_num(payload, "train_a"),
            held_b=_num(payload, "held_b"),
            held_a=_num(payload, "held_a"),
            eps_train=_num(payload, "eps_train"),
            eps_heldout=_num(payload, "eps_heldout"),
            mode=mode,
            train_a2=_opt_num(payload, "train_a2"),
            held_a2=_opt_num(payload, "held_a2"),
            train_b2=_opt_num(payload, "train_b2"),
            held_b2=_opt_num(payload, "held_b2"),
        )
    except (ValueError, OSError) as exc:
        emit({"decision": None, "ok": False, "reason": "input error: {}".format(exc)})
        return 1
    emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
