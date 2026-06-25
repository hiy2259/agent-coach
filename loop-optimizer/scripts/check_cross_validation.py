#!/usr/bin/env python3
"""check_cross_validation.py -- ADVISORY (record-only) cross-family drift WARN.

This is a NON-BLOCKING surfacing aid, NOT a gate and NOT a safety net. It exists
for ONE consumer: the moment a human is about to **trust a dogfood verdict**. It
answers "has the decorrelated second-judge cross-family check ever run against
THIS ruler + THIS golden set + THIS split -- or have they drifted since?" by
comparing the current run's provenance to the LAST entry of the dual-judge ledger
(``references/baselines/dual-judge-ledger.jsonl``).

It MUST stay advisory:
  * It NEVER exits non-zero to block a run (run_cli always returns 0).
  * It NEVER feeds the merge gate / HALT / discard logic. Nothing consumes its
    output except a human reading the WARN.
  * It does NOT run the cross-family check, does NOT call a model, does NOT touch
    the network. It only reads a JSON-lines ledger and compares fields.

Why this and not a blocking gate: the dual-judge comparator body is intentionally
on HOLD (the diagnostic set is saturated; a detector built on it would be
premature). Until a drift detector is validated on a de-saturated set, the honest
posture is to SURFACE drift to the human at verdict-trust time and let them decide
to run the manual cross-family re-check -- not to pretend an automated safety net
exists. See SKILL.md (grader-drift canary paragraph) and references/baselines/.

Input JSON (stdin or a file-path arg, like the other scripts):
  {
    "grader_version_id": "claude-opus-4-8",   # current run's ruler id (may be null)
    "golden_set_version": "v2",               # current golden-set version (may be null)
    "split_hash": "sha256:...",               # current frozen split hash (may be null)
    "ledger_path": "<path>"                    # optional; default:
                                               #   references/baselines/dual-judge-ledger.jsonl
                                               #   resolved relative to this script
  }
  A current field that is absent/null is treated as "unknown" and, because it
  cannot be shown to match the ledger, contributes to a WARN (fail-loud-but-soft).

Output JSON:
  {
    "ok": true,                # ALWAYS true on a well-formed request (advisory)
    "warn": true|false,        # true => surface to the human before trusting
    "message": "<human-readable advisory>",
    "reason": "never_run" | "drift" | "match",
    "changed": ["grader_version_id", ...],   # which fields differ (drift only)
    "last_check": { ...last ledger entry... } | null,
    "current": { "grader_version_id":..., "golden_set_version":..., "split_hash":... }
  }
"""

import json
import os
import sys

try:
    from _common import load_payload, emit
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import load_payload, emit


# Provenance fields compared against the ledger, in report order.
PROVENANCE_FIELDS = ("grader_version_id", "golden_set_version", "split_hash")

# Default ledger location, resolved relative to THIS file so the helper works from
# any working directory (the scripts are invoked with varied cwd).
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LEDGER_PATH = os.path.normpath(
    os.path.join(_HERE, "..", "references", "baselines", "dual-judge-ledger.jsonl")
)


def read_last_ledger_entry(ledger_path):
    """Return the LAST JSON object in the JSON-lines ledger, or None if the file
    is missing or has no parseable entries.

    Blank lines are skipped. A malformed (non-JSON) last data line raises
    ValueError so the caller surfaces a structured error rather than silently
    treating a corrupt ledger as 'never run' -- a corrupt ledger is a real
    problem the human should see, not a soft pass.
    """
    if not ledger_path or not os.path.exists(ledger_path):
        return None
    last = None
    with open(ledger_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "malformed ledger line in {!r}: {}".format(ledger_path, exc)
                )
            last = obj
    return last


def check_cross_validation(current, last_entry):
    """Pure comparison. Returns the advisory result dict (always ok:true).

    ``current`` is the run's provenance ({grader_version_id, golden_set_version,
    split_hash}); ``last_entry`` is the last ledger object or None.

    - last_entry is None            -> warn, reason "never_run"
    - any provenance field differs  -> warn, reason "drift" (+ which fields)
    - all three match               -> no warn, reason "match"

    A current field that is None/absent counts as drift UNCONDITIONALLY -- even if
    the ledger's same field is also null -- because we cannot certify a cross-check
    covered a ruler/set/split we cannot even read (fail-safe: never a silent match).
    """
    current_view = {f: current.get(f) for f in PROVENANCE_FIELDS}

    if last_entry is None:
        return {
            "ok": True,
            "warn": True,
            "reason": "never_run",
            "changed": list(PROVENANCE_FIELDS),
            "message": (
                "Cross-family (dual-judge) check has NEVER been recorded for this "
                "target: the decorrelated second-judge sanity check has not been "
                "run against this ruler/golden-set/split. Cross-validation NOT done "
                "-- treat the verdict as single-judge. (Advisory only; run the "
                "manual cross-family re-check before trusting it.)"
            ),
            "last_check": None,
            "current": current_view,
        }

    # Fail-safe: a null/absent CURRENT provenance field ALWAYS counts as drift,
    # independent of the ledger. "I cannot see this field" must never resolve to a
    # silent match -- which it otherwise would when the ledger's same field is also
    # null (None == None). We cannot certify a cross-check covered a ruler/set/split
    # we can't even read, so the honest answer is always WARN.
    changed = [f for f in PROVENANCE_FIELDS
               if current.get(f) is None or current.get(f) != last_entry.get(f)]

    if not changed:
        return {
            "ok": True,
            "warn": False,
            "reason": "match",
            "changed": [],
            "message": (
                "Grader/golden-set/split are UNCHANGED since the last cross-family "
                "check ({} -> verdict {!r}). The decorrelated second-judge result "
                "still applies to this provenance. (Advisory only; not a guarantee "
                "of correctness.)".format(
                    last_entry.get("date", "?"), last_entry.get("verdict", "?")
                )
            ),
            "last_check": last_entry,
            "current": current_view,
        }

    return {
        "ok": True,
        "warn": True,
        "reason": "drift",
        "changed": changed,
        "message": (
            "Grader/golden-set/split CHANGED since the last cross-family check ({}): "
            "differs in {}. Cross-validation NOT done for the current provenance -- "
            "the prior decorrelated second-judge result may no longer apply. "
            "(Advisory only; run the manual cross-family re-check before trusting "
            "the verdict.)".format(last_entry.get("date", "?"), ", ".join(changed))
        ),
        "last_check": last_entry,
        "current": current_view,
    }


def run_cli(argv):
    """ADVISORY entrypoint. Always returns 0 -- this check NEVER blocks a run.

    The only non-zero path is a malformed REQUEST (bad JSON payload) or a corrupt
    ledger file, which are operator errors in invoking the tool, not a verdict
    about the run. Even those still print a structured ok:false so nothing parses
    a traceback.
    """
    try:
        payload = load_payload(argv)
        if not isinstance(payload, dict):
            emit({"ok": False, "warn": False,
                  "message": "input must be a JSON object"})
            return 1
        ledger_path = payload.get("ledger_path") or DEFAULT_LEDGER_PATH
        last_entry = read_last_ledger_entry(ledger_path)
        result = check_cross_validation(payload, last_entry)
    except (ValueError, OSError) as exc:
        emit({"ok": False, "warn": False, "message": "error: {}".format(exc)})
        return 1
    emit(result)
    # Advisory: success regardless of warn. A WARN is information for the human,
    # never a process failure.
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
