#!/usr/bin/env python3
"""apply_change.py -- S4: staging-only application + idempotent promote.

This script is the ONLY thing allowed to mutate the staging files, and it is
forbidden from ever touching the live target. Two operations:

  op="apply"   : take the current text + a Change {before, after}, produce the
                 candidate text, and write it to STAGING (prompt.candidate.md).
                 The live target is NEVER written. apply RE-RUNS the full
                 verify_change gate (uniqueness AND locality) and REFUSES on
                 ok:false -- so a change the gate rejects can never be staged,
                 even if a caller forgot to run verify first (S3 unbypassable).

  op="promote" : the merge gate passed AND the confirm re-run held. Promote
                 candidate -> current by copying prompt.candidate.md over
                 prompt.current.md. REQUIRES ``confirmed: true`` (S7): promote
                 refuses without it, so a noise change can never be baked in by
                 skipping the confirm re-run. The orchestrator sets confirmed:true
                 ONLY after score_compare.py returned a confirmed promote decision
                 (confirm after-scores + re-measured baseline train_b2/held_b2
                 supplied, and the gain/parity held). This is the
                 single irreversible step, so the confirm wall lives here in code.
                 IDEMPOTENT: if current already byte-equals candidate, the
                 promote is already done and this is a no-op. This ordering --
                 *promote first, then the caller records phase:merged* -- is what
                 makes resume safe: a crash between promote and the state write
                 just re-runs an idempotent promote (M1, S4).
                 Used for BOTH a MERGE and a SUB_KEEP (a kept removal is a live
                 change too and must be promoted the same way -- they are
                 symmetric; only the confirm mode differs).

Neither op writes the live target file. Staging lives under loop/<target>/.

Input JSON (op="apply"):
  {
    "op": "apply",
    "current_text": "<...>"  | "current_file": "<path to prompt.current.md>",
    "before": "<...>", "after": "<...>",
    "candidate_file": "<path to prompt.candidate.md>",  # required: where to stage
    "kind": "edit" | "subtraction",   # pass it: subtraction removals would else
                                       # be rejected by the default ratio cap at
                                       # the re-run verify gate below.
    # optional cap overrides -- kept in sync with the verify step automatically
    # (defaults mirror verify_change.py: see DEFAULT_MAX_* there):
    "max_before_tokens": 200, "max_after_delta_ratio": 0.5,
    "max_after_abs_delta": 60, "max_after_abs_tokens": 10
  }

Input JSON (op="promote"):
  {
    "op": "promote",
    "current_file":   "<path to prompt.current.md>",   # required
    "candidate_file": "<path to prompt.candidate.md>", # required
    "confirmed": true                                  # required: the confirm
                                                       # re-run held (S7). Set it
                                                       # ONLY from a score_compare
                                                       # result with confirmed:true.
  }

Output JSON:
  apply   -> { "ok": true, "op": "apply",   "candidate_file": "...",
               "wrote_candidate": true, "occurrences": 1 }
  promote -> { "ok": true, "op": "promote", "current_file": "...",
               "promoted": true|false, "already_promoted": true|false }

Exit code mirrors ``ok``.
"""

import os
import sys

try:
    from _common import count_occurrences, load_payload, emit
    from verify_change import (
        verify_change as _verify,
        DEFAULT_MAX_BEFORE_TOKENS,
        DEFAULT_MAX_AFTER_DELTA_RATIO,
        DEFAULT_MAX_AFTER_ABS_DELTA,
        DEFAULT_MAX_AFTER_ABS_TOKENS,
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import count_occurrences, load_payload, emit
    from verify_change import (
        verify_change as _verify,
        DEFAULT_MAX_BEFORE_TOKENS,
        DEFAULT_MAX_AFTER_DELTA_RATIO,
        DEFAULT_MAX_AFTER_ABS_DELTA,
        DEFAULT_MAX_AFTER_ABS_TOKENS,
    )


def apply_change_text(current_text, before, after):
    """Pure transform: replace the unique ``before`` with ``after``.

    Returns the candidate text. Raises ValueError if ``before`` does not match
    exactly once (defensive: verify_change.py is the primary gate, but apply
    must never silently corrupt staging by replacing the wrong / no span).
    """
    if before is None:
        before = ""
    if after is None:
        after = ""
    occ = count_occurrences(current_text, before)
    if occ != 1:
        raise ValueError(
            "refusing to apply: before matches {} times, expected exactly 1".format(occ)
        )
    # Single, non-overlapping replacement of the unique anchor.
    return current_text.replace(before, after, 1)


def _read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _write_text(path, text):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def op_apply(payload):
    if "current_text" in payload and payload["current_text"] is not None:
        current_text = payload["current_text"]
    elif "current_file" in payload and payload["current_file"] is not None:
        current_text = _read_text(payload["current_file"])
    else:
        raise ValueError("op=apply requires 'current_text' or 'current_file'")

    candidate_file = payload.get("candidate_file")
    if not candidate_file:
        raise ValueError("op=apply requires 'candidate_file' (the staging path)")

    # D: apply is GATED on the FULL verify_change (uniqueness AND locality).
    # Previously apply only re-checked uniqueness, so a change verify_change
    # rejected for locality could still be staged. Re-running the whole gate
    # here makes S3 structurally impossible to bypass from the apply step. The
    # same caps the orchestrator passes to the verify step flow through here so
    # the two never disagree.
    v = _verify(
        current_text,
        payload.get("before"),
        payload.get("after"),
        max_before_tokens=payload.get("max_before_tokens", DEFAULT_MAX_BEFORE_TOKENS),
        max_after_delta_ratio=payload.get("max_after_delta_ratio", DEFAULT_MAX_AFTER_DELTA_RATIO),
        max_after_abs_delta=payload.get("max_after_abs_delta", DEFAULT_MAX_AFTER_ABS_DELTA),
        max_after_abs_tokens=payload.get("max_after_abs_tokens", DEFAULT_MAX_AFTER_ABS_TOKENS),
        kind=payload.get("kind"),
    )
    if not v["ok"]:
        return {
            "ok": False,
            "op": "apply",
            "candidate_file": candidate_file,
            "wrote_candidate": False,
            "reason": "refusing to apply: verify_change rejected this change ({})".format(v["reason"]),
            "verify": v,
        }

    occ = v["occurrences"]
    candidate_text = apply_change_text(
        current_text, payload.get("before"), payload.get("after")
    )
    _write_text(candidate_file, candidate_text)
    return {
        "ok": True,
        "op": "apply",
        "candidate_file": candidate_file,
        "wrote_candidate": True,
        "occurrences": occ,
    }


def op_promote(payload):
    # S7 confirm wall: promotion is the ONE irreversible step, so it refuses
    # unless the caller asserts the confirm re-run held. ``confirmed`` is set
    # only from a score_compare result with confirmed:true (confirm after-scores
    # + re-measured baseline train_b2/held_b2 supplied, gain/parity reproduced).
    # Without this gate the entire
    # confirm safeguard would be advisory prose the orchestrator could skip.
    if payload.get("confirmed") is not True:
        return {
            "ok": False,
            "op": "promote",
            "promoted": False,
            "already_promoted": False,
            "reason": "refusing to promote: confirm re-run not recorded (S7). Pass "
                      "confirmed:true ONLY after score_compare returned a confirmed "
                      "promote decision (confirm after-scores + re-measured baseline "
                      "train_b2/held_b2 supplied, gain held). "
                      "Promoting without a confirm re-run can bake in measurement noise.",
        }

    current_file = payload.get("current_file")
    candidate_file = payload.get("candidate_file")
    if not current_file or not candidate_file:
        raise ValueError("op=promote requires 'current_file' and 'candidate_file'")
    if not os.path.exists(candidate_file):
        raise ValueError("candidate_file does not exist: {}".format(candidate_file))

    candidate_text = _read_text(candidate_file)

    # Idempotency: if current already equals candidate, promote was already done.
    if os.path.exists(current_file) and _read_text(current_file) == candidate_text:
        return {
            "ok": True,
            "op": "promote",
            "current_file": current_file,
            "promoted": False,
            "already_promoted": True,
        }

    _write_text(current_file, candidate_text)
    return {
        "ok": True,
        "op": "promote",
        "current_file": current_file,
        "promoted": True,
        "already_promoted": False,
    }


def run_cli(argv):
    try:
        payload = load_payload(argv)
        op = payload.get("op")
        if op == "apply":
            result = op_apply(payload)
        elif op == "promote":
            result = op_promote(payload)
        else:
            raise ValueError("unknown or missing 'op' (expected 'apply' or 'promote')")
    except (ValueError, OSError) as exc:
        emit({"ok": False, "reason": "error: {}".format(exc)})
        return 1
    emit(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
