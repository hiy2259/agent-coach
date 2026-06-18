#!/usr/bin/env python3
"""calibrate_noise.py -- S7: estimate eps_train / eps_heldout from score samples.

The merge gate (score_compare.py) compares an *after* score to a *before* score.
The question it must answer is: "is this difference real, or just measurement
noise?" Measurement noise comes from the **Runner** producing different outputs
across runs on FIXED inputs (the temp-0 Grader re-grading identical text has
zero variance, so it is not the noise source -- see S7).

This script does NOT call any model. The orchestration (SKILL.md) runs the
Runner ``k_calib`` times on fixed inputs, grades each run externally, and passes
the resulting per-split score SAMPLES in here. We turn those samples into a
robust spread => eps_train / eps_heldout, PER SPLIT.

ESTIMATORS (documented; default = "stddev2"):
  - "stddev2" (default): eps = 2 * (population) standard deviation of the split's
        score samples. Rationale: for an approximately normal score, ~95% of
        single-run scores fall within 2*sigma of the mean, so a before/after gap
        smaller than ~2*sigma is well within run-to-run noise and must not count
        as progress. This is the estimator named in the brief (std-dev x2).
        With a single sample, stddev is 0 -> eps falls back to ``min_eps``.

  - "pairwise_p95": eps = the ``percentile``-th percentile (default 95) of the
        absolute pairwise differences |s_i - s_j| among the split's samples.
        Rationale: this is the empirical null distribution of "how far apart do
        two independent runs land?" -- a direct, distribution-free model of the
        before/after gap under the null hypothesis of no change. The brief names
        this alternative ("high percentile of pairwise null differences").
        Needs >= 2 samples; with <2 it falls back to ``min_eps``.

A floor ``min_eps`` (default 0.02) keeps the margin STRICTLY POSITIVE even when
the samples are identical (stddev 0). A zero margin is dangerous: the gate would
merge a +0.0 tie (no real gain) as "progress". The floor makes any sub-floor
gain count as noise. Raise it for coarse / small golden sets where a single
rubric flip is itself within noise.

If a ``baseline`` (per-split baseline scores) is supplied, the result also
reports whether the merge gate is even SATISFIABLE: a change can only MERGE if
it gains >= eps_train on train, so when eps_train >= the achievable headroom
(1 - baseline_train), NO change can ever clear the gate -- the orchestrator must
stop and fix the measurement (enlarge train / raise k_calib) rather than burn N
turns. The saturated case (baseline already at the 1.0 ceiling) is the SAME
condition and surfaces the same way; this is the calibration-time
overfit/staleness signal, reusing one mechanism with no change to
score_compare's merge contract.

Input JSON:
  {
    "samples": { "train": [0.70, 0.72, 0.68, 0.71, 0.69],
                 "heldout": [0.65, 0.67, 0.64] },
    "estimator": "stddev2" | "pairwise_p95",   # default "stddev2"
    "percentile": 95,                            # for pairwise_p95
    "min_eps": 0.02,                             # floor (default 0.02, must be > 0)
    "baseline": { "train": 0.84, "heldout": 0.87 },  # OPTIONAL -> gate-satisfiability check
    "round_to": 4                                # decimal places (default 4)
  }

  (Splits other than train/heldout are tolerated and echoed back, but the loop
  only uses eps_train / eps_heldout.)

Output JSON:
  {
    "ok": true,
    "estimator": "stddev2",
    "eps_train": 0.0299, "eps_heldout": 0.0249,
    "gate_satisfiable": true,                    # present only when baseline given
    "warnings": [ "GATE UNSATISFIABLE: ..." ],   # present only when something is wrong
    "per_split": { "train": {"n":5,"mean":..,"stddev":..,"eps":..,
                             "baseline":..,"headroom":..,"gate_unsatisfiable":false}, ... }
  }

Reading per-split ``gate_unsatisfiable``: TRAIN is the merge DRIVER, so its flag
is authoritative -- it is what sets the top-level ``gate_satisfiable`` and the
loud ``warnings`` above. Every OTHER split (held-out, ...) is a GUARD, not a
driver: its per-split ``gate_unsatisfiable`` is ADVISORY only (a saturated
held-out baseline does not block a run -- it just means held-out has little room
left to regress). So the same flag means different things by split: under
``train`` it is the real blocker; under ``heldout`` it is informational. Do not
let the harmless held-out signal train you to ignore the dangerous train one.
"""

import math
import sys

try:
    from _common import load_payload, emit
except ImportError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import load_payload, emit


DEFAULT_ESTIMATOR = "stddev2"
DEFAULT_PERCENTILE = 95
# A strictly-positive floor. eps must never reach 0, or score_compare would
# merge a +0.0 tie as "progress" (see B / the merge-gate strict-gain guard).
DEFAULT_MIN_EPS = 0.02
DEFAULT_ROUND_TO = 4


def _mean(values):
    return sum(values) / len(values)


def _pop_stddev(values):
    """Population standard deviation (ddof=0). 0.0 for a single sample.

    Floating-point subtraction of identical samples can leave a tiny non-zero
    residue (e.g. 2.2e-16). We snap a negligible variance to exactly 0.0 so
    identical score samples produce a true zero spread (before any min_eps
    floor) instead of a spurious sub-epsilon margin.
    """
    n = len(values)
    if n < 2:
        return 0.0
    mu = _mean(values)
    var = sum((v - mu) ** 2 for v in values) / n
    if var <= 1e-15:
        return 0.0
    return math.sqrt(var)


def _percentile(sorted_values, pct):
    """Linear-interpolation percentile (same method as numpy's default).

    ``sorted_values`` must be non-empty and sorted ascending. ``pct`` in [0,100].
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return sorted_values[lo]
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


def _pairwise_abs_diffs(values):
    diffs = []
    n = len(values)
    for i in range(n):
        for j in range(i + 1, n):
            diffs.append(abs(values[i] - values[j]))
    return diffs


def eps_for_split(values, estimator=DEFAULT_ESTIMATOR, percentile=DEFAULT_PERCENTILE, min_eps=DEFAULT_MIN_EPS):
    """Compute (eps, detail_dict) for one split's score samples."""
    values = [float(v) for v in values]
    n = len(values)
    detail = {"n": n, "estimator": estimator}

    if n == 0:
        raise ValueError("empty sample list; need at least one score per split")

    mean = _mean(values)
    stddev = _pop_stddev(values)
    detail["mean"] = mean
    detail["stddev"] = stddev

    if estimator == "stddev2":
        eps = 2.0 * stddev
    elif estimator == "pairwise_p95":
        diffs = _pairwise_abs_diffs(values)
        if diffs:
            eps = _percentile(sorted(diffs), percentile)
        else:
            eps = 0.0  # single sample: no pairwise diff available
        detail["percentile"] = percentile
        detail["n_pairs"] = len(diffs)
    else:
        raise ValueError("unknown estimator {!r} (expected 'stddev2' or 'pairwise_p95')".format(estimator))

    eps = max(eps, min_eps)
    detail["eps_raw"] = eps
    return eps, detail


def calibrate(samples, estimator=DEFAULT_ESTIMATOR, percentile=DEFAULT_PERCENTILE,
              min_eps=DEFAULT_MIN_EPS, round_to=DEFAULT_ROUND_TO, baseline=None):
    """Compute per-split eps. Returns a result dict.

    ``samples`` is a mapping split-name -> list of scores. ``eps_train`` and
    ``eps_heldout`` are surfaced at the top level when those splits are present.

    When ``baseline`` (split -> baseline score) is given, also report gate
    satisfiability: if eps_train >= (1 - baseline_train) the merge gate can never
    be cleared (the saturated-baseline case is the same condition). This is the
    calibration-time stop/warn signal -- it does NOT alter score_compare.
    """
    if not isinstance(samples, dict) or not samples:
        raise ValueError("'samples' must be a non-empty object of split -> [scores]")

    # Validate the noise-margin knobs up front (F-09). A non-positive floor would
    # let a +0.0 tie merge as "progress"; an out-of-range percentile makes the
    # pairwise estimator index past the sample list (an uncaught IndexError).
    try:
        min_eps_f = float(min_eps)
    except (TypeError, ValueError):
        raise ValueError("min_eps must be a positive number, got {!r}".format(min_eps))
    if min_eps_f <= 0:
        raise ValueError(
            "min_eps must be > 0 (a zero/negative floor lets a +0.0 tie look like "
            "progress), got {!r}".format(min_eps)
        )
    if estimator == "pairwise_p95":
        try:
            pct_f = float(percentile)
        except (TypeError, ValueError):
            raise ValueError("percentile must be a number in [0, 100], got {!r}".format(percentile))
        if not (0.0 <= pct_f <= 100.0):
            raise ValueError("percentile must be in [0, 100], got {!r}".format(percentile))

    per_split = {}
    for split, values in samples.items():
        eps, detail = eps_for_split(values, estimator=estimator, percentile=percentile, min_eps=min_eps)
        if round_to is not None:
            eps = round(eps, round_to)
        detail["eps"] = eps
        if baseline and split in baseline and baseline[split] is not None:
            b = float(baseline[split])
            if not (0.0 <= b <= 1.0):
                raise ValueError(
                    "baseline[{!r}] must be a score in [0, 1], got {}".format(split, b)
                )
            headroom = 1.0 - b
            detail["baseline"] = b
            detail["headroom"] = round(headroom, round_to) if round_to is not None else headroom
            # Gate is unsatisfiable on this split when the noise margin meets or
            # exceeds the room left to improve (a sub-eps gain can't be certified).
            detail["gate_unsatisfiable"] = eps >= headroom - 1e-12
        per_split[split] = detail

    result = {
        "ok": True,
        "estimator": estimator,
        "per_split": per_split,
    }
    if "train" in per_split:
        result["eps_train"] = per_split["train"]["eps"]
    if "heldout" in per_split:
        result["eps_heldout"] = per_split["heldout"]["eps"]

    # Satisfiability is driven by TRAIN (the merge driver; held-out is a guard).
    # Computed only when a train baseline was supplied.
    warnings = []
    train = per_split.get("train")
    if train is not None and "gate_unsatisfiable" in train:
        satisfiable = not train["gate_unsatisfiable"]
        result["gate_satisfiable"] = satisfiable
        if not satisfiable:
            b = train["baseline"]
            if b >= 1.0 - 1e-12:
                warnings.append(
                    "SATURATED: train baseline is at the ceiling (1.0) -- no change can raise "
                    "train, so the merge gate cannot certify any progress. The golden set is too "
                    "easy; add harder / currently-failing cases before running (S6)."
                )
            else:
                warnings.append(
                    "GATE UNSATISFIABLE: eps_train ({}) >= achievable train headroom ({}). No "
                    "single change can clear the merge gate. Enlarge the train split and/or raise "
                    "k_calib so the noise margin shrinks below the achievable gain, then re-run."
                    .format(train["eps"], train["headroom"])
                )
    if warnings:
        result["warnings"] = warnings
    return result


def run_cli(argv):
    try:
        payload = load_payload(argv)
        result = calibrate(
            samples=payload.get("samples"),
            estimator=payload.get("estimator", DEFAULT_ESTIMATOR),
            percentile=payload.get("percentile", DEFAULT_PERCENTILE),
            min_eps=payload.get("min_eps", DEFAULT_MIN_EPS),
            round_to=payload.get("round_to", DEFAULT_ROUND_TO),
            baseline=payload.get("baseline"),
        )
    except (ValueError, OSError) as exc:
        emit({"ok": False, "reason": "input error: {}".format(exc)})
        return 1
    emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
