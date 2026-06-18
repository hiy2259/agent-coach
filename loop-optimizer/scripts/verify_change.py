#!/usr/bin/env python3
"""verify_change.py -- S3: mechanical single-change verification.

Given a proposed Change against a target text, verify two things deterministically
(NO model judgment):

  1. UNIQUENESS: ``before`` matches the target text EXACTLY ONCE. A zero-match
     anchor is stale; a multi-match anchor is ambiguous (the edit could land in
     the wrong place). Both are rejected.
  2. LOCALITY: the change is small and local. The ``before`` span must be
     <= 200 tokens, AND the size delta must pass EITHER:
       - ratio path: |len(after)-len(before)| / len(before) <= 0.5.
         For a genuine kind="subtraction" removal (after is a PURE DELETION of
         before -- it introduces no new token -- and is not longer), the ratio
         cap is relaxed to 1.0, since deleting a rule that is most of its span is
         the removal's natural size. The "pure deletion" guard stops a turn
         labelled "subtraction" from SWAPPING a rule for several new shorter ones
         to dodge the 0.5 edit cap.
       OR
       - absolute path: a small ADDITION on a short target. It must GROW
         (after >= before) by <= 60 chars AND <= 10 tokens.
         This rescues "one short scoped instruction on a tiny target" (where a
         single clause blows past 50% of a tiny anchor) without admitting a
         shrink-rewrite (growth-only) or a multi-rule pile. A *token* cap is used
         (not a punctuation heuristic) so a lowercase / comma-separated pile
         cannot dodge it. For anything longer than one short clause, anchor on a
         wider unique ``before`` and use the ratio path -- "anchor wide, add
         little".
     A whole-file rewrite is still not a "single localized change".

This enforces invariant S3 ("one turn = one localized change") at the code
level, before anything is ever applied to staging.

Input JSON object:
  {
    "target_text": "<full current target text>",      # OR
    "target_file": "<path to read the target text>",   # exactly one of these
    "before": "<exact substring to be replaced>",
    "after":  "<replacement text>",
    # optional overrides:
    "max_before_tokens": 200,
    "max_after_delta_ratio": 0.5,
    "max_after_abs_delta": 60,       # absolute char floor for the add path
    "max_after_abs_tokens": 10,      # absolute token floor for the add path
    "kind": "edit" | "subtraction"   # subtraction removals get the relaxed ratio
  }

Output JSON object:
  { "ok": true,  "reason": "...", "checks": {...}, "occurrences": 1 }
  { "ok": false, "reason": "...", "checks": {...}, "occurrences": N }

Exit code: 0 if ok, 1 if rejected (or input error). The JSON ``ok`` field is the
authoritative signal; the exit code mirrors it for shell convenience.

CLI:
  python3 verify_change.py payload.json
  cat payload.json | python3 verify_change.py
"""

import sys

try:
    from _common import count_occurrences, count_tokens, tokenize, load_payload, emit
except ImportError:  # allow `python3 scripts/verify_change.py` from repo root
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import count_occurrences, count_tokens, tokenize, load_payload, emit


DEFAULT_MAX_BEFORE_TOKENS = 200
DEFAULT_MAX_AFTER_DELTA_RATIO = 0.5
# The absolute-floor path rescues ONE short instruction on a tiny target. Kept
# small in BOTH chars and tokens so it can't hold a multi-rule pile, and the
# token cap is style-independent (commas/lowercase can't dodge it). This is the
# guard-relaxation point -- review changes here against S3.
DEFAULT_MAX_AFTER_ABS_DELTA = 60      # chars
DEFAULT_MAX_AFTER_ABS_TOKENS = 10     # tokens


def _is_subsequence(sub, seq):
    """True iff list ``sub`` appears in ``seq`` in order (not necessarily
    contiguously). The classic iterator-advance check; empty ``sub`` matches any
    ``seq``."""
    it = iter(seq)
    return all(token in it for token in sub)


def _is_pure_deletion(before, after):
    """True iff ``after`` is a genuine in-order EXCISION of ``before`` -- its token
    list is a SUBSEQUENCE of before's, so it only drops tokens, never reorders,
    negates, or duplicates them.

    The old check was a set-subset, which ignored order AND count (F-10): it
    accepted a net-shrink that DUPLICATED a surviving token (e.g. "a b c d e f" ->
    "a a", set-subset true but not a real removal) and a same-token reorder as a
    "deletion". Subsequence is the honest test -- a true removal keeps the
    surviving tokens in their original order and multiplicity -- and it subsumes
    both the order and the count check the audit asked for."""
    return _is_subsequence(tokenize(after), tokenize(before))


def _resolve_target_text(payload):
    """Return the target text from either ``target_text`` or ``target_file``."""
    has_text = "target_text" in payload and payload["target_text"] is not None
    has_file = "target_file" in payload and payload["target_file"] is not None
    if has_text and has_file:
        raise ValueError("provide exactly one of 'target_text' or 'target_file', not both")
    if has_text:
        return payload["target_text"]
    if has_file:
        with open(payload["target_file"], "r", encoding="utf-8") as fh:
            return fh.read()
    raise ValueError("missing target: provide 'target_text' or 'target_file'")


def verify_change(
    target_text,
    before,
    after,
    max_before_tokens=DEFAULT_MAX_BEFORE_TOKENS,
    max_after_delta_ratio=DEFAULT_MAX_AFTER_DELTA_RATIO,
    max_after_abs_delta=DEFAULT_MAX_AFTER_ABS_DELTA,
    max_after_abs_tokens=DEFAULT_MAX_AFTER_ABS_TOKENS,
    kind=None,
):
    """Pure verification. Returns a result dict; never raises on policy failure.

    ``ok`` is True only when uniqueness AND locality both pass.
    """
    if before is None:
        before = ""
    if after is None:
        after = ""

    occurrences = count_occurrences(target_text, before)
    before_tokens = count_tokens(before)

    # after-size delta as a fraction of the before length (in characters).
    # If before is empty we cannot define a ratio; uniqueness already fails in
    # that case, so we report ratio as None and let uniqueness drive the reject.
    before_len = len(before)
    after_len = len(after)
    abs_delta = abs(after_len - before_len)
    if before_len > 0:
        delta_ratio = abs_delta / before_len
    else:
        delta_ratio = None

    # Locality holds if the size delta is small RELATIVELY (ratio path) OR is a
    # valid small ADDITION (absolute path). Both paths are tightened so the
    # relaxation can never become a back-door for bundling / rewriting (S3):
    #   - A genuine subtraction REMOVAL (kind=subtraction, not longer, and a pure
    #     deletion adding no new token) gets the ratio cap relaxed to 1.0 -- the
    #     removal's natural locality. The pure-deletion guard blocks a "swap"
    #     mislabelled as subtraction. apply re-runs verify with the same kind, so
    #     verify and apply agree without the caller threading a cap.
    #   - The absolute path applies ONLY to GROWTH and caps BOTH chars and tokens,
    #     so it admits one short clause but not a multi-rule pile (token cap is
    #     punctuation-independent).
    is_removal = (kind == "subtraction") and (after_len <= before_len) and _is_pure_deletion(before, after)
    effective_ratio_cap = max(max_after_delta_ratio, 1.0) if is_removal else max_after_delta_ratio
    ratio_ok = (delta_ratio is None) or (delta_ratio <= effective_ratio_cap)

    grew = after_len >= before_len
    added_tokens = count_tokens(after) - count_tokens(before)
    abs_ok = grew and (abs_delta <= max_after_abs_delta) and (added_tokens <= max_after_abs_tokens)

    checks = {
        "unique": occurrences == 1,
        "before_tokens": before_tokens,
        "max_before_tokens": max_before_tokens,
        "before_span_ok": before_tokens <= max_before_tokens,
        "after_delta_ratio": delta_ratio,
        "effective_ratio_cap": effective_ratio_cap,
        "max_after_delta_ratio": max_after_delta_ratio,
        "after_abs_delta": abs_delta,
        "max_after_abs_delta": max_after_abs_delta,
        "after_added_tokens": added_tokens,
        "max_after_abs_tokens": max_after_abs_tokens,
        "is_removal": is_removal,
        "after_delta_ok": ratio_ok or abs_ok,
        "kind": kind,
    }

    # Reject precedence: report the most actionable single reason.
    if occurrences == 0:
        return {
            "ok": False,
            "reason": "before not found in target (stale anchor; 0 matches). Copy `before` "
                      "verbatim from the current target — a 0-match is often CRLF vs LF line "
                      "endings or a Unicode look-alike (smart vs straight quotes, NBSP vs "
                      "space) that doesn't match byte-for-byte",
            "occurrences": occurrences,
            "checks": checks,
        }
    if occurrences > 1:
        return {
            "ok": False,
            "reason": "before is ambiguous: {} matches, expected exactly 1".format(occurrences),
            "occurrences": occurrences,
            "checks": checks,
        }
    if not checks["before_span_ok"]:
        return {
            "ok": False,
            "reason": "before span {} tokens exceeds locality cap {} (change not local)".format(
                before_tokens, max_before_tokens
            ),
            "occurrences": occurrences,
            "checks": checks,
        }
    if not checks["after_delta_ok"]:
        return {
            "ok": False,
            "reason": (
                "change not local: delta ratio {:.3f} > cap {} and not a single small addition "
                "(grew={}, abs_delta={}/{} chars, added_tokens={}/{}) -- anchor wider and add less"
                .format(delta_ratio, effective_ratio_cap, grew, abs_delta,
                        max_after_abs_delta, added_tokens, max_after_abs_tokens)
            ),
            "occurrences": occurrences,
            "checks": checks,
        }

    return {
        "ok": True,
        "reason": "unique match and change is local",
        "occurrences": occurrences,
        "checks": checks,
    }


def run_cli(argv):
    try:
        payload = load_payload(argv)
        target_text = _resolve_target_text(payload)
    except (ValueError, OSError) as exc:
        emit({"ok": False, "reason": "input error: {}".format(exc), "occurrences": None, "checks": {}})
        return 1

    result = verify_change(
        target_text=target_text,
        before=payload.get("before"),
        after=payload.get("after"),
        max_before_tokens=payload.get("max_before_tokens", DEFAULT_MAX_BEFORE_TOKENS),
        max_after_delta_ratio=payload.get("max_after_delta_ratio", DEFAULT_MAX_AFTER_DELTA_RATIO),
        max_after_abs_delta=payload.get("max_after_abs_delta", DEFAULT_MAX_AFTER_ABS_DELTA),
        max_after_abs_tokens=payload.get("max_after_abs_tokens", DEFAULT_MAX_AFTER_ABS_TOKENS),
        kind=payload.get("kind"),
    )
    emit(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
