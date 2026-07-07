#!/usr/bin/env python3
"""aggregate_scores.py -- reduce per-case Grader Scores to the two per-split
numbers the merge gate compares. PURE ARITHMETIC, no model.

The Grader emits a per-case vector (passed/total per case); score_compare.py
needs two scalars (train_score, heldout_score). That reduction is the one step
the loop ALWAYS runs and, until now, the ONLY step with no script and no test --
the orchestrator did `Σpassed / Σtotal` by hand (F-24). Giving it a deterministic,
tested home does two things:

  1. Removes the last ad-hoc, unverified arithmetic from the measurement path.
  2. Is the seam every future upgrade hangs off -- a statistical (bootstrap) gate,
     per-case weighting, and per-case discrimination analysis all need the
     per-case vector in ONE deterministic place. This script computes the scalars
     AND echoes the per-case vector so the orchestrator can persist it for those.

Per-split score is `Σ passed / Σ total` over the split's cases -- NOT the mean of
per-case pass-rates. A case with more rubric criteria therefore carries
proportionally more weight, matching data-formats §4.7. (Mean-of-rates would let
a 1-criterion case swing the score as much as a 10-criterion one.)

Input JSON:
  {
    "scores": [
      {"case_id": "c1", "split": "train",   "passed": 4, "total": 5},
      {"case_id": "c2", "split": "heldout", "results": [{"criterion_index": 0, "passed": true},
                                                        {"criterion_index": 1, "passed": false}]},
      ...
    ]
  }
  Each Score gives `passed`/`total` directly OR a `results` array to derive them
  from (if both are present they must agree, else it is a structured error).

Output JSON:
  {
    "ok": true,
    "train_score": 0.80, "heldout_score": 0.67,    # present for each split seen
    "per_split": { "train":   {"n_cases": 5, "sum_passed": 20, "sum_total": 25, "score": 0.80},
                   "heldout": {"n_cases": 3, "sum_passed":  6, "sum_total":  9, "score": 0.666667} },
    "per_case": [ {"case_id": "c1", "split": "train", "passed": 4, "total": 5, "score": 0.8}, ... ]
  }
"""

import sys

try:
    from _common import load_payload, emit
except ImportError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import load_payload, emit


def _passed_total(score):
    """Resolve (passed, total) for one Score.

    If a ``results`` array is present it is authoritative (passed = count of true,
    total = len). Any explicitly-given passed/total must AGREE with it (a mismatch
    is a Grader bug we must not silently average over). Without ``results``, both
    ``passed`` and ``total`` must be given explicitly.
    """
    cid = score.get("case_id")
    results = score.get("results")
    if results is not None:
        if not isinstance(results, list):
            raise ValueError("case {!r}: 'results' must be a list".format(cid))
        derived_total = len(results)
        derived_passed = sum(1 for r in results if isinstance(r, dict) and r.get("passed") is True)
        if score.get("passed") is not None and int(score["passed"]) != derived_passed:
            raise ValueError(
                "case {!r}: passed {} disagrees with {} true results".format(
                    cid, score["passed"], derived_passed)
            )
        if score.get("total") is not None and int(score["total"]) != derived_total:
            raise ValueError(
                "case {!r}: total {} disagrees with len(results) {}".format(
                    cid, score["total"], derived_total)
            )
        return derived_passed, derived_total
    if score.get("passed") is None or score.get("total") is None:
        raise ValueError(
            "case {!r}: provide a 'results' array or both 'passed' and 'total'".format(cid)
        )
    try:
        return int(score["passed"]), int(score["total"])
    except (TypeError, ValueError):
        raise ValueError("case {!r}: passed/total must be integers".format(cid))


def aggregate_scores(scores):
    """Reduce a list of per-case Scores to per-split Σpassed/Σtotal. Pure."""
    if not isinstance(scores, list) or not scores:
        raise ValueError("'scores' must be a non-empty list of per-case Score objects")

    per_split = {}
    per_case = []
    seen = set()  # (split, case_id) -- a duplicate would double-count silently
    for s in scores:
        if not isinstance(s, dict):
            raise ValueError("each score must be an object, got {}".format(type(s).__name__))
        cid = s.get("case_id")
        split = s.get("split")
        if not split or not isinstance(split, str):
            raise ValueError("case {!r}: missing string 'split'".format(cid))
        passed, total = _passed_total(s)
        if total <= 0:
            raise ValueError(
                "case {!r}: total must be > 0 (a case with zero criteria cannot be scored)".format(cid)
            )
        if passed < 0 or passed > total:
            raise ValueError("case {!r}: passed {} out of range [0, {}]".format(cid, passed, total))
        key = (split, cid)
        if cid is not None and key in seen:
            raise ValueError("duplicate case_id {!r} within split {!r} (would double-count)".format(cid, split))
        seen.add(key)

        bucket = per_split.setdefault(split, {"n_cases": 0, "sum_passed": 0, "sum_total": 0})
        bucket["n_cases"] += 1
        bucket["sum_passed"] += passed
        bucket["sum_total"] += total
        per_case.append({
            "case_id": cid, "split": split, "passed": passed, "total": total,
            "score": round(passed / total, 6),
        })

    result = {"ok": True, "per_split": {}, "per_case": per_case}
    for split, bucket in per_split.items():
        bucket["score"] = round(bucket["sum_passed"] / bucket["sum_total"], 6)  # sum_total > 0 guaranteed
        result["per_split"][split] = bucket
    if "train" in result["per_split"]:
        result["train_score"] = result["per_split"]["train"]["score"]
    if "heldout" in result["per_split"]:
        result["heldout_score"] = result["per_split"]["heldout"]["score"]
    return result


def run_cli(argv):
    try:
        payload = load_payload(argv)
        result = aggregate_scores(payload.get("scores"))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        emit({"ok": False, "reason": "input error: {}".format(exc)})
        return 1
    emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
