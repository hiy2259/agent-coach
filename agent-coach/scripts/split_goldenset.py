#!/usr/bin/env python3
"""split_goldenset.py -- S5: assign train/held-out, enforce sizes, freeze split.

Operates on a POST-CURATION golden-set.json (the human has already curated
inputs and written rubrics; see SKILL.md "Cold start"). Two responsibilities:

  1. SPLIT (op="split"): assign each active case to train or held-out and freeze
     the assignment.
       - "reality-first": the MOST REALISTIC items go to held-out, so the
         held-out set is not a blind-spot twin of train (S5). Cases already
         carrying an explicit "split" are respected unless ``reassign`` is true.
       - Size gate: active train >= 5 AND active held-out >= 3, else ERROR.
         (Retired cases are excluded from scoring and from the counts.)
       - Freeze: compute ``split_hash`` over the active cases + their splits and
         store it on the golden set. This is the value re-checked every turn.

  2. VERIFY (op="verify"): recompute the split_hash of a golden set and compare
     to its stored ``split_hash`` to detect mid-run mutation (S5 freeze). Any
     change to an active case's input, rubric, id, status, or split flips the
     hash and is reported as a mutation.

split_hash design: a sha256 over canonical JSON of, for every ACTIVE case
(sorted by id): {id, split, input_content, rubric, status}. ``input_content`` is
the resolved input text (inline ``input`` or the contents of ``input_file``), so
editing a case file -- not just the json -- is detected. Retired cases are
intentionally excluded (retiring a dead case must not invalidate a run).

Input JSON (op="split"):
  {
    "op": "split",
    "golden_set": { ... full golden-set.json object ... },
    "golden_set_path": "<path>",         # OR provide the object inline
    "base_dir": "<dir for resolving input_file>",  # default: dirname(path) or "."
    "reassign": false,                    # if true, ignore existing splits and re-derive
    "min_train": 5, "min_heldout": 3,     # optional overrides (else from min_size)
    "write": false                        # if true and golden_set_path given, write back
  }

Input JSON (op="verify"):
  {
    "op": "verify",
    "golden_set": { ... } | "golden_set_path": "<path>",
    "base_dir": "<dir>"
  }

Output (split):  { "ok": true, "split_hash": "sha256:...",
                   "counts": {"train":5,"heldout":3,"retired":1},
                   "assignments": {"id": "train", ...}, "golden_set": {...} }
Output (verify): { "ok": true, "valid": true,  "expected": "...", "actual": "..." }
                 { "ok": true, "valid": false, "expected": "...", "actual": "...",
                   "reason": "split_hash mismatch: golden set mutated mid-run" }

Input JSON (op="state"):  pure-read SIGNPOST for deterministic cold-start entry.
  { "op": "state", "golden_set_path": "<path>" }   # OR inline "golden_set"
Output (state):  { "ok": true,
                   "state": "missing"|"malformed"|"empty"|"unfrozen"|"mutated"|"ready",
                   "ready_to_run": bool, "next": "<one-line instruction>",
                   "counts": {"active":N,"train":N,"heldout":N,"retired":N} }
  ``state`` is a SIGNPOST, not a guard -- it never blocks and never mutates. The
  authoritative walls stay op=split (freeze + require_rubric + size gate) and
  op=verify (per-turn hash check); "ready" means freeze-consistent, not fully
  validated.
"""

import os
import sys

try:
    from _common import sha256_hex, canonical_json, load_payload, emit
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import sha256_hex, canonical_json, load_payload, emit


DEFAULT_MIN_TRAIN = 5
DEFAULT_MIN_HELDOUT = 3


def _resolve_input_content(case, base_dir):
    """Return the resolved input text for a case (inline or from input_file)."""
    if case.get("input") is not None:
        return case["input"]
    if case.get("input_file") is not None:
        path = case["input_file"]
        if not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    raise ValueError("case {!r} has neither 'input' nor 'input_file'".format(case.get("id")))


KNOWN_STATUSES = ("active", "retired")


def _status(case):
    """Normalized status: stripped + lower-cased; default 'active' (GAP-5).

    Status is compared case-insensitively so a typo like 'Retired' / 'RETIRED'
    actually retires the case instead of silently leaving it active (and frozen +
    scored). A non-string status is returned as-is so the unknown-status check
    flags it rather than crashing here."""
    raw = case.get("status", "active")
    return raw.strip().lower() if isinstance(raw, str) else raw


def active_cases(golden_set):
    """Active cases only (normalized status != 'retired'). Default 'active'."""
    return [c for c in golden_set.get("cases", []) if _status(c) != "retired"]


def unknown_status_positions(cases):
    """Indices of cases whose normalized status is neither 'active' nor 'retired'
    (GAP-5). A value like 'inactive' / 'archived' would otherwise fall through as
    active and be frozen + scored. Surface it instead of guessing intent."""
    bad = []
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            continue
        if _status(c) not in KNOWN_STATUSES:
            bad.append(i)
    return bad


def missing_id_positions(cases):
    """Indices of ACTIVE cases lacking a non-empty string ``id``.

    ``id`` is the key the split assignment map and the freeze hash are organized
    by. The assignment loop indexes ``case["id"]`` directly, so a missing id
    raises KeyError (an ugly traceback instead of a structured error), and a
    blank/duplicate id silently collapses entries in the assignment dict. We
    therefore validate ids up front and turn any violation into a clean
    ValueError / "malformed" state -- preserving the totality contract ("never
    crash; always return a structured result"). Retired cases are exempt: they
    are never assigned or hashed. Non-dict entries are skipped (a separate check
    flags those).
    """
    bad = []
    for i, c in enumerate(cases):
        if not isinstance(c, dict):
            continue
        if _status(c) == "retired":
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid.strip():
            bad.append(i)
    return bad


def duplicate_active_ids(cases):
    """ids appearing on more than one ACTIVE case (F-05).

    The split assignment dict and the size gate are keyed by id, so two active
    cases sharing an id silently collapse: the size gate counts the deduped total
    (and can pass) while MORE physical cases are actually frozen and scored, quietly
    polluting the measurement. Detect duplicates up front. Retired cases are exempt;
    call after ids are known present (non-string ids are skipped here).
    """
    seen = {}
    for c in cases:
        if not isinstance(c, dict) or _status(c) == "retired":
            continue
        cid = c.get("id")
        if isinstance(cid, str):
            seen[cid] = seen.get(cid, 0) + 1
    return sorted([cid for cid, n in seen.items() if n > 1])


def compute_split_hash(golden_set, base_dir="."):
    """Deterministic hash over active cases + their splits + content.

    Sorted by case id so insertion order never affects the hash.
    """
    entries = []
    for case in sorted(active_cases(golden_set), key=lambda c: c.get("id", "")):
        entries.append({
            "id": case.get("id"),
            "split": case.get("split"),
            "status": case.get("status", "active"),
            "rubric": case.get("rubric"),
            "input_content": _resolve_input_content(case, base_dir),
        })
    return sha256_hex(canonical_json(entries))


def verify_split_hash(golden_set, base_dir="."):
    """Detect mid-run mutation. Returns a result dict.

    Compares the golden set's stored ``split_hash`` to a freshly computed one.
    ``valid`` is True iff they match. If the golden set carries no stored hash,
    ``valid`` is False with an explanatory reason (an unfrozen set must not run).
    """
    expected = golden_set.get("split_hash")
    actual = compute_split_hash(golden_set, base_dir=base_dir)
    if expected is None:
        return {
            "ok": True,
            "valid": False,
            "expected": None,
            "actual": actual,
            "reason": "no stored split_hash; run op=split to freeze before looping",
        }
    valid = expected == actual
    result = {"ok": True, "valid": valid, "expected": expected, "actual": actual}
    if not valid:
        result["reason"] = "split_hash mismatch: golden set mutated mid-run"
    return result


def goldenset_state(payload):
    """PURE-READ signpost: classify the golden set's state so cold-start ENTRY is
    deterministic (S2) instead of inferred from the path by eye. This is NOT a
    guard -- it never blocks and never mutates; the authoritative walls remain
    op=split (freeze + require_rubric + size gate) and op=verify (per-turn hash).
    It only composes existing read-only primitives.

    States: "missing" (no file -> cold start), "malformed" (bad JSON / no 'cases'
    list / non-object case / unresolvable input on a frozen set), "empty" (0 active
    cases -> cold start), "unfrozen"
    (actives but no stored split_hash -> run op=split), "mutated" (stored hash
    mismatches -> restore or re-split), "ready" (frozen + consistent -> loop).
    """
    path = payload.get("golden_set_path")
    inline = payload.get("golden_set")
    base_dir = payload.get("base_dir")
    # Stay TOTAL over arbitrary JSON: a malformed REQUEST (bad payload types) is a
    # structured ok:False "unknown", never a raised TypeError. (A malformed golden
    # SET is a different thing -> ok:True state "malformed", handled below.)
    if path is not None and not isinstance(path, str):
        return {"ok": False, "state": "unknown", "ready_to_run": False,
                "next": "'golden_set_path' must be a string path"}
    if base_dir is not None and not isinstance(base_dir, str):
        return {"ok": False, "state": "unknown", "ready_to_run": False,
                "next": "'base_dir' must be a string path"}
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(path)) if path else "."

    # Load read-only; absence / parse failure become STATES, never exceptions.
    if inline is not None:
        golden_set = inline
    elif path:
        if not os.path.exists(path):
            return {"ok": True, "state": "missing", "ready_to_run": False,
                    "next": "no golden set at {!r}: cold start -- build it first "
                            "(SKILL.md 'Cold start')".format(path)}
        try:
            import json
            with open(path, "r", encoding="utf-8") as fh:
                golden_set = json.load(fh)
        except (ValueError, OSError) as exc:
            return {"ok": True, "state": "malformed", "ready_to_run": False,
                    "next": "golden set at {!r} is unreadable / not JSON: {}".format(path, exc)}
    else:
        return {"ok": False, "state": "unknown", "ready_to_run": False,
                "next": "provide 'golden_set_path' (or inline 'golden_set') to classify"}

    cases = golden_set.get("cases") if isinstance(golden_set, dict) else None
    if not isinstance(cases, list) or not all(isinstance(c, dict) for c in cases):
        return {"ok": True, "state": "malformed", "ready_to_run": False,
                "next": "golden set 'cases' must be a list of case objects; fix the "
                        "schema (references/data-formats.md)"}

    # Unrecognized status first (GAP-5): it decides activeness, so flag it before
    # id/freeze logic rather than letting a typo'd case slip in as active.
    unknown_status = unknown_status_positions(cases)
    if unknown_status:
        return {"ok": True, "state": "malformed", "ready_to_run": False,
                "next": "case(s) at index {} have an unrecognized 'status' (use 'active' or "
                        "'retired'); a typo is otherwise treated as active "
                        "(references/data-formats.md)".format(unknown_status)}

    # A missing/blank id is "malformed", not "unfrozen": otherwise the signpost
    # would route the orchestrator to op=split, which needs the id to assign --
    # turning a fixable schema slip into a crash at the next step (the totality
    # contract says: surface it as a structured state here).
    bad_ids = missing_id_positions(cases)
    if bad_ids:
        return {"ok": True, "state": "malformed", "ready_to_run": False,
                "next": "active case(s) at index {} have a missing/blank/non-string "
                        "'id'; every active case needs a non-empty string id "
                        "(references/data-formats.md)".format(bad_ids)}

    dup_ids = duplicate_active_ids(cases)
    if dup_ids:
        return {"ok": True, "state": "malformed", "ready_to_run": False,
                "next": "duplicate active case id(s) {}; ids must be unique or the split "
                        "silently undercounts (references/data-formats.md)".format(dup_ids)}

    actives = active_cases(golden_set)
    all_cases = golden_set.get("cases", [])
    n_train = sum(1 for c in actives if c.get("split") == "train")
    n_heldout = sum(1 for c in actives if c.get("split") == "heldout")
    counts = {
        "active": len(actives),
        "train": n_train,
        "heldout": n_heldout,
        # Active cases that are neither train nor heldout (unassigned or a bogus
        # split label). 0 for a clean frozen set; a non-zero value lets a consumer
        # spot a degenerate set even when the freeze hash is self-consistent.
        "unassigned": len(actives) - n_train - n_heldout,
        "retired": len(all_cases) - len(actives),
    }

    if not actives:
        return {"ok": True, "state": "empty", "ready_to_run": False, "counts": counts,
                "next": "golden set has 0 active cases: cold start -- seed + curate inputs"}

    stored = golden_set.get("split_hash")
    if not stored:
        return {"ok": True, "state": "unfrozen", "ready_to_run": False, "counts": counts,
                "next": "active cases present but not frozen: run op=split to assign + freeze"}

    # compute_split_hash resolves input_file contents; a broken / ill-typed
    # reference is malformed (TypeError covers a non-string input_file path).
    try:
        actual = compute_split_hash(golden_set, base_dir=base_dir)
    except (ValueError, OSError, TypeError) as exc:
        return {"ok": True, "state": "malformed", "ready_to_run": False, "counts": counts,
                "next": "cannot resolve a case input ({}); fix the golden set".format(exc)}

    if stored != actual:
        return {"ok": True, "state": "mutated", "ready_to_run": False, "counts": counts,
                "expected": stored, "actual": actual,
                "next": "split_hash mismatch: golden set changed since freeze -- "
                        "restore the frozen set or re-run op=split"}

    return {"ok": True, "state": "ready", "ready_to_run": True, "counts": counts,
            "next": "frozen + consistent: ready to loop"}


def split_goldenset(golden_set, base_dir=".", reassign=False,
                    min_train=None, min_heldout=None, require_rubric=True):
    """Assign splits (reality-first), enforce min sizes, freeze split_hash.

    Returns a result dict containing the (possibly updated) golden_set with a
    fresh ``split_hash``. Raises ValueError when a size gate fails, or (when
    ``require_rubric`` is true -- the default) when any ACTIVE case has an empty
    rubric. A frozen rubric-less case has zero criteria, so the merge gate has
    nothing to measure and passes VACUOUSLY -- the loop could then merge freely
    against a null eval and the moat collapses (the most blatant Goodhart hole).
    The 5-7-criteria guidance is the human's; this only blocks the degenerate
    empty case. Retired cases are exempt (excluded from scoring).
    """
    if min_train is None:
        min_train = golden_set.get("min_size", {}).get("train", DEFAULT_MIN_TRAIN)
    if min_heldout is None:
        min_heldout = golden_set.get("min_size", {}).get("heldout", DEFAULT_MIN_HELDOUT)

    all_cases_list = golden_set.get("cases", [])

    # Validate statuses first (GAP-5): a typo'd status decides whether a case is
    # even active, so an unrecognized value must be caught before id/size logic.
    unknown_status = unknown_status_positions(all_cases_list)
    if unknown_status:
        raise ValueError(
            "case(s) at index {} have an unrecognized 'status' (use 'active' or 'retired', "
            "case-insensitive); a typo is otherwise silently treated as active and "
            "frozen/scored.".format(unknown_status)
        )

    actives = active_cases(golden_set)

    # Validate ids BEFORE the assignment loop indexes case["id"] directly: a
    # missing/blank/non-string id would otherwise raise a bare KeyError (ugly
    # traceback, and op=state happily routes here as "unfrozen -> go split").
    bad_ids = missing_id_positions(all_cases_list)
    if bad_ids:
        raise ValueError(
            "active case(s) at index {} have a missing/blank/non-string 'id'. Every "
            "active case needs a non-empty string id (it keys the split assignment "
            "and the freeze hash). Fix the golden set (references/data-formats.md).".format(bad_ids)
        )

    dup_ids = duplicate_active_ids(golden_set.get("cases", []))
    if dup_ids:
        raise ValueError(
            "duplicate active case id(s) {}: ids must be unique — duplicates collapse in "
            "the split assignment so the size gate undercounts what is actually frozen and "
            "scored. Rename or retire the duplicates.".format(dup_ids)
        )

    if require_rubric:
        no_rubric = [c.get("id") for c in actives
                     if not (isinstance(c.get("rubric"), list) and len(c.get("rubric")) > 0)]
        if no_rubric:
            raise ValueError(
                "empty rubric on active case(s) {}: a frozen rubric-less case has zero "
                "criteria, so the gate passes vacuously and the loop merges against a null "
                "eval. Add yes/no criteria (5-7 per case) or retire the case.".format(no_rubric)
            )

    # Decide assignments. If a case already has an explicit split and we are not
    # reassigning, keep it (the human/prior run froze it). Otherwise derive:
    # realistic items -> held-out first, the rest -> train.
    assignments = {}
    need_derive = []
    for case in actives:
        existing = case.get("split")
        if existing in ("train", "heldout") and not reassign:
            assignments[case["id"]] = existing
        else:
            need_derive.append(case)

    # Reality-first derivation: realistic cases prefer held-out. Stable order by
    # id so the result is deterministic.
    realistic = sorted([c for c in need_derive if c.get("realistic")], key=lambda c: c.get("id", ""))
    non_realistic = sorted([c for c in need_derive if not c.get("realistic")], key=lambda c: c.get("id", ""))

    # Count existing held-out so we only top up toward the minimum from realistic
    # items, then send remaining realistic items + all non-realistic to train.
    held_existing = sum(1 for v in assignments.values() if v == "heldout")
    for case in realistic:
        if held_existing < min_heldout:
            assignments[case["id"]] = "heldout"
            held_existing += 1
        else:
            assignments[case["id"]] = "train"
    for case in non_realistic:
        assignments[case["id"]] = "train"

    train_count = sum(1 for v in assignments.values() if v == "train")
    held_count = sum(1 for v in assignments.values() if v == "heldout")
    retired_count = len(golden_set.get("cases", [])) - len(actives)

    if train_count < min_train or held_count < min_heldout:
        raise ValueError(
            "size gate failed: active train={} (min {}), held-out={} (min {}). "
            "Curate more cases before running.".format(
                train_count, min_train, held_count, min_heldout
            )
        )

    # Write assignments back onto a shallow copy of the golden set so we can
    # hash and return the frozen version without mutating the caller's object.
    updated = dict(golden_set)
    new_cases = []
    for case in golden_set.get("cases", []):
        cid = case.get("id")
        if cid in assignments:
            case = dict(case)
            case["split"] = assignments[cid]
        new_cases.append(case)
    updated["cases"] = new_cases

    split_hash = compute_split_hash(updated, base_dir=base_dir)
    updated["split_hash"] = split_hash

    return {
        "ok": True,
        "split_hash": split_hash,
        "counts": {"train": train_count, "heldout": held_count, "retired": retired_count},
        "assignments": assignments,
        "golden_set": updated,
    }


def _load_golden_set(payload):
    """Return (golden_set, base_dir, golden_set_path)."""
    path = payload.get("golden_set_path")
    if "golden_set" in payload and payload["golden_set"] is not None:
        golden_set = payload["golden_set"]
    elif path:
        import json
        with open(path, "r", encoding="utf-8") as fh:
            golden_set = json.load(fh)
    else:
        raise ValueError("provide 'golden_set' (inline) or 'golden_set_path'")

    base_dir = payload.get("base_dir")
    if not base_dir:
        base_dir = os.path.dirname(os.path.abspath(path)) if path else "."
    return golden_set, base_dir, path


def run_cli(argv):
    try:
        payload = load_payload(argv)
        op = payload.get("op", "split")

        # op=state is a pure-read signpost: "missing"/"malformed" are RETURNED
        # states, so it must run before _load_golden_set (which raises on those).
        if op == "state":
            result = goldenset_state(payload)
            emit(result)
            return 0 if result.get("ok") else 1

        golden_set, base_dir, path = _load_golden_set(payload)

        if op == "verify":
            result = verify_split_hash(golden_set, base_dir=base_dir)
        elif op == "split":
            result = split_goldenset(
                golden_set,
                base_dir=base_dir,
                reassign=bool(payload.get("reassign", False)),
                min_train=payload.get("min_train"),
                min_heldout=payload.get("min_heldout"),
                require_rubric=bool(payload.get("require_rubric", True)),
            )
            if payload.get("write") and path:
                import json
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(result["golden_set"], fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
                result["written_to"] = path
        else:
            raise ValueError("unknown 'op' {!r} (expected 'split', 'verify', or 'state')".format(op))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        # Totality: any structural defect (incl. a stray KeyError/TypeError from a
        # malformed case) becomes a structured {ok:false}, never a raw traceback.
        emit({"ok": False, "reason": "error: {}".format(exc)})
        return 1
    emit(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
