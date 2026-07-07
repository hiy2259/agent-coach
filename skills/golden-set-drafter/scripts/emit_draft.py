#!/usr/bin/env python3
"""Emit an UNFROZEN golden-set draft whose held-out rubrics are empty by design.

This is the deterministic end of the golden-set-drafter skill: the council and
the expose pass are model work, but the invariants that keep agent-coach's
delegated gate armed must hold *every* time, so they are enforced here in code,
not in prose. The emitted set deliberately has NO ``split_hash`` and every
held-out case ships ``rubric: []`` with ``split:"heldout"`` pinned — so
agent-coach's own ``op=state`` routes to ``op=split`` and ``op=split`` raises
until a human authors those rubrics (see agent-coach
``scripts/split_goldenset.py``: unfrozen at :307-310, require_rubric raise at
:381-389). We never weaken that: an AI-drafted held-out rubric would turn the
exam into a self-graded one (anti-pattern #1, S5).

Usage (mirrors agent-coach's script convention)::

    printf '%s' '<payload JSON>' | python3 scripts/emit_draft.py
    python3 scripts/emit_draft.py payload.json          # argv alternative

Payload::

    {
      "output_dir": "loop/my-target/golden-set",   // artifacts land here
      "target": "./agents/my-target.md",           // recorded in the set
      "case_language": "ko",
      "created": "2026-07-02",                     // optional, default today
      "changelog": "...",                          // optional
      "train_cases": [                              // >= 5
        {"id": "...", "input": "..." | "input_file_content": "...",
         "rubric": ["yes/no criterion", ...],       // >= 1; 5-7 is guidance
         "realistic": false, "notes": "...",
         "verified_failing": true, "top_up": false}
      ],
      "heldout_cases": [                            // >= 3, INPUTS ONLY
        {"id": "...", "input": "..." | "input_file_content": "...",
         "probe_dimension": "...", "notes": "..."}  // NO rubric key allowed
      ],
      "ruler": {"model": "claude-...",              // required: same-ruler disclosure
                 "temperature_configured": 0.7},    // optional number|null
      "council": {"rounds": 2, "objections_total": 5,
                   "unresolved": [...], "accepted_risks": [...]},   // optional
      "excluded_case_ids": {"<id>": "<reason>"},   // tool/network-dependent
      "runbook": {                                  // case-language markdown blocks
        "title": "...", "intro": "...", "next_steps": "...",
        "limitations": "1. ... \n ... 10. ...",     // >= 10 numbered items
        "notes": "..."                              // optional
      }
    }

Design notes (why some rules are warnings, not errors):

* Train rubric size 5-7 is *guidance for intentional criteria*. Hard-forcing it
  would invite padding — a filler criterion injects grading noise and dulls the
  merge gate — so outside 5-7 we WARN and record it, never block. Empty train
  rubric IS an error: it would trip agent-coach's require_rubric raise with a
  runbook that told the human only held-out needs filling (wrong guidance).
* ``provenance`` is hardcoded to ``"bootstrap"`` (the only schema-legal value
  for AI-drafted cases; ``"ai-draft"`` does not exist in the enum). Because
  "bootstrap" alone would read as the Bootstrapper's meaning (AI input + HUMAN
  rubric), the true origin is stamped per case in ``tags``:
  train ``["ai-input","ai-rubric"]`` / held-out ``["ai-input","human-rubric"]``.
* Timestamps come from the payload when given so tests are deterministic.
"""

import json
import os
import re
import sys
from datetime import date

SKILL_NAME = "golden-set-drafter"
SET_VERSION = "v1"
MIN_TRAIN = 5
MIN_HELDOUT = 3
RUBRIC_GUIDE_LO, RUBRIC_GUIDE_HI = 5, 7
MIN_LIMITATION_ITEMS = 10

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_NUMBERED_ITEM_RE = re.compile(r"(?m)^\s{0,3}\d{1,2}[.)]\s")


def _req_str(obj, key, where):
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ValueError("{}: '{}' must be a non-empty string".format(where, key))
    return val


def _case_id(case, idx, kind):
    cid = case.get("id")
    if not isinstance(cid, str) or not cid.strip():
        raise ValueError("{} case at index {} has a missing/blank 'id'".format(kind, idx))
    if not _ID_RE.match(cid):
        raise ValueError(
            "{} case id {!r} is not filename-safe (use letters/digits/._- , "
            "starting alphanumeric) — ids key ./cases/<id>.input.txt and the "
            "freeze hash".format(kind, cid))
    return cid


def _one_input(case, cid):
    """Enforce exactly one of input / input_file_content (agent-coach: exactly
    one of input / input_file per case)."""
    inline = case.get("input")
    filec = case.get("input_file_content")
    has_inline = isinstance(inline, str) and inline.strip() != ""
    has_file = isinstance(filec, str) and filec.strip() != ""
    if has_inline == has_file:  # both or neither
        raise ValueError(
            "case {!r}: provide exactly one of 'input' (inline) or "
            "'input_file_content' (written to ./cases/<id>.input.txt)".format(cid))
    return ("inline", inline) if has_inline else ("file", filec)


def _validate_rubric(case, cid, warnings):
    rubric = case.get("rubric")
    if not isinstance(rubric, list) or not rubric:
        raise ValueError(
            "train case {!r}: 'rubric' must be a non-empty list of yes/no "
            "criterion strings. An empty train rubric would trip agent-coach's "
            "require_rubric raise while the runbook tells the human only "
            "held-out needs authoring — wrong guidance at the gate.".format(cid))
    for i, crit in enumerate(rubric):
        if not isinstance(crit, str) or not crit.strip():
            raise ValueError("train case {!r}: rubric[{}] is not a non-empty string".format(cid, i))
    n = len(rubric)
    if n < RUBRIC_GUIDE_LO or n > RUBRIC_GUIDE_HI:
        warnings.append(
            "train case {!r} has {} criteria (guidance is {}-{}); kept as-is — "
            "do not pad with filler criteria".format(cid, n, RUBRIC_GUIDE_LO, RUBRIC_GUIDE_HI))
    return [c.strip() for c in rubric]


def _validate_runbook(runbook):
    if not isinstance(runbook, dict):
        raise ValueError("'runbook' must be an object with title/intro/next_steps/limitations")
    for key in ("title", "intro", "next_steps", "limitations"):
        _req_str(runbook, key, "runbook")
    n_items = len(_NUMBERED_ITEM_RE.findall(runbook["limitations"]))
    if n_items < MIN_LIMITATION_ITEMS:
        raise ValueError(
            "runbook.limitations contains {} numbered items; all {} honest "
            "limitations must be rendered faithfully and completely (number "
            "them 1-{}) — hiding limitations was the original design's "
            "failure mode".format(n_items, MIN_LIMITATION_ITEMS, MIN_LIMITATION_ITEMS))


def _agent_coach_split_cmd(output_dir):
    """Best-effort display path for the op=split command in the runbook."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.abspath(os.path.join(here, "..", "..", "agent-coach", "scripts", "split_goldenset.py"))
    if os.path.isfile(candidate):
        try:
            shown = os.path.relpath(candidate, os.path.abspath(output_dir))
        except ValueError:  # different drive (windows) — fall back to abs
            shown = candidate
    else:
        shown = "<agent-coach>/scripts/split_goldenset.py"
    return ("printf '%s' '{\"op\":\"split\",\"golden_set_path\":\"golden-set.json\",\"write\":true}' "
            "| python3 " + shown)


def build_draft(payload):
    """Validate the payload and build (golden_set, case_files, runlog, runbook_md, warnings).

    Raises ValueError on any invariant violation. Writes nothing — emit_draft()
    does the IO, so tests can exercise every invariant without touching disk.
    """
    warnings = []

    output_dir = _req_str(payload, "output_dir", "payload")
    target = _req_str(payload, "target", "payload")
    case_language = _req_str(payload, "case_language", "payload")

    ruler_in = payload.get("ruler")
    if not isinstance(ruler_in, dict):
        raise ValueError("'ruler' object with 'model' is required — the same-ruler "
                         "disclosure is not optional (it is what makes the expose "
                         "pass auditable)")
    ruler_model = _req_str(ruler_in, "model", "ruler")
    ruler = {
        "model": ruler_model,
        "temperature_configured": ruler_in.get("temperature_configured"),
        "temperature_pinning": "prose-only (harness limitation, both sides)",
    }

    train_in = payload.get("train_cases")
    heldout_in = payload.get("heldout_cases")
    if not isinstance(train_in, list) or len(train_in) < MIN_TRAIN:
        raise ValueError("need >= {} train_cases (got {}) — never emit below the "
                         "size gate; top up with the highest-probe non-failing "
                         "candidates instead of shrinking".format(
                             MIN_TRAIN, len(train_in) if isinstance(train_in, list) else "none"))
    if not isinstance(heldout_in, list) or len(heldout_in) < MIN_HELDOUT:
        raise ValueError("need >= {} heldout_cases (got {}) — below agent-coach's "
                         "held-out floor the retirement dodge reopens".format(
                             MIN_HELDOUT, len(heldout_in) if isinstance(heldout_in, list) else "none"))

    excluded = payload.get("excluded_case_ids") or {}
    if not isinstance(excluded, dict):
        raise ValueError("'excluded_case_ids' must be an object of id -> reason")

    created = payload.get("created") or date.today().isoformat()

    seen_ids = set()
    cases = []
    case_files = {}  # relative path -> content
    verified_failing = []
    top_up = []

    for idx, case in enumerate(train_in):
        cid = _case_id(case, idx, "train")
        if cid in seen_ids:
            raise ValueError("duplicate case id {!r} — ids key the split assignment "
                             "and the freeze hash; duplicates undercount the size gate".format(cid))
        seen_ids.add(cid)

        if case.get("top_up") and case.get("verified_failing"):
            raise ValueError("train case {!r} is flagged both top_up and "
                             "verified_failing — a top-up is by definition a "
                             "non-failing filler; fix the flags".format(cid))

        kind, text = _one_input(case, cid)
        rubric = _validate_rubric(case, cid, warnings)

        tags = ["ai-input", "ai-rubric"]
        if case.get("top_up"):
            tags.append("top-up")
            top_up.append(cid)
        if cid in excluded:
            tags.append("baseline-excluded")
        if case.get("verified_failing"):
            verified_failing.append(cid)

        out = {
            "id": cid,
            "split": "train",
            "provenance": "bootstrap",
            "added_in_version": SET_VERSION,
            "realistic": bool(case.get("realistic", False)),
            "status": "active",
            "tags": tags,
            "notes": (case.get("notes") or "").strip(),
            "rubric": rubric,
        }
        if kind == "inline":
            out["input"] = text
        else:
            rel = "./cases/{}.input.txt".format(cid)
            out["input_file"] = rel
            case_files[rel] = text
        cases.append(out)

    for idx, case in enumerate(heldout_in):
        cid = _case_id(case, idx, "heldout")
        if cid in seen_ids:
            raise ValueError("duplicate case id {!r} across splits".format(cid))
        seen_ids.add(cid)

        rubric_key = case.get("rubric")
        if isinstance(rubric_key, list) and len(rubric_key) > 0:
            raise ValueError(
                "S5-2 violation: held-out case {!r} arrived WITH a rubric. The "
                "council/skill must never draft held-out rubrics — the human "
                "owns the definition of 'good' on the generalization guard. "
                "Refusing to emit.".format(cid))

        kind, text = _one_input(case, cid)

        tags = ["ai-input", "human-rubric"]
        if cid in excluded:
            tags.append("baseline-excluded")

        notes = (case.get("notes") or "").strip()
        probe = (case.get("probe_dimension") or "").strip()
        if probe:
            notes = "probe: {}{}".format(probe, (" — " + notes) if notes else "")

        out = {
            "id": cid,
            "split": "heldout",          # pinned — split_goldenset respects existing splits
            "provenance": "bootstrap",
            "added_in_version": SET_VERSION,
            "realistic": True,            # held-out is selected realism-first by design
            "status": "active",
            "tags": tags,
            "notes": notes,
            "rubric": [],                 # EMPTY BY DESIGN — the delegated gate
        }
        if kind == "inline":
            out["input"] = text
        else:
            rel = "./cases/{}.input.txt".format(cid)
            out["input_file"] = rel
            case_files[rel] = text
        cases.append(out)

    if not verified_failing and not excluded:
        warnings.append(
            "no train case is marked verified_failing and none is excluded — "
            "either the expose pass was skipped or the target passed everything; "
            "the train baseline may sit at ceiling (calibrate_noise will judge)")
    if top_up:
        warnings.append(
            "top-up fillers present ({}): train baseline may sit near ceiling — "
            "agent-coach's calibration is the authority that accepts or loudly "
            "rejects this set".format(", ".join(top_up)))

    golden_set = {
        "target": target,
        "version": SET_VERSION,
        "parent_version": None,
        "created": created,
        "updated": created,
        "changelog": (payload.get("changelog") or
                      "Initial AI-drafted set (golden-set-drafter): train input+rubric and "
                      "held-out inputs drafted by the council; ALL held-out rubrics "
                      "intentionally left empty for human authorship."),
        "min_size": {"train": MIN_TRAIN, "heldout": MIN_HELDOUT},
        "cases": cases,
        # NOTE: deliberately NO "split_hash" — the set must arrive unfrozen so
        # agent-coach's op=state routes the human to op=split and the
        # require_rubric raise (the delegated gate).
    }

    council_in = payload.get("council") or {}
    council = {
        "rounds": council_in.get("rounds", 0),
        "objections_total": council_in.get("objections_total", 0),
        "unresolved": council_in.get("unresolved", []),
        "accepted_risks": council_in.get("accepted_risks", []),
    }

    runlog = {
        "skill": SKILL_NAME,
        "skill_version": SET_VERSION,
        "generated": created,
        "target": target,
        "case_language": case_language,
        "ruler": ruler,
        "council": council,
        "expose": {
            "train_total": len(train_in),
            "verified_failing": verified_failing,
            "top_up": top_up,
            "baseline_excluded": excluded,
            "heldout_runs": 0,   # held-out is never executed at draft time (by design)
        },
        "counts": {"train": len(train_in), "heldout": len(heldout_in)},
        "warnings": warnings,
        "next_step": ("human authors ALL held-out rubrics (see "
                      "GOLDEN-SET-DRAFT-README.md), then runs agent-coach op=split; "
                      "first run is expected to error on the empty-rubric held-out "
                      "ids — that error is the gate working"),
    }

    runbook_in = payload.get("runbook")
    _validate_runbook(runbook_in)
    heldout_ids = [c["id"] for c in cases if c["split"] == "heldout"]
    appendix = [
        "---",
        "",
        "## Gate data (machine-generated)",
        "",
        "- Draft state: **UNFROZEN** (`split_hash` absent) — agent-coach `op=state` answers `\"unfrozen\"`.",
        "- Held-out cases awaiting YOUR rubric (empty by design):",
    ]
    appendix += ["  - `{}`".format(cid) for cid in heldout_ids]
    appendix += [
        "- First command (run from the directory containing `golden-set.json`):",
        "",
        "      " + _agent_coach_split_cmd(output_dir),
        "",
        "  The FIRST run is expected to FAIL with an error naming exactly the ids above —",
        "  that error is the gate working, not a bug. Author those rubrics, re-run, and the set freezes.",
        "- Ordering note: the empty-rubric check fires BEFORE the size gate — do not delete",
        "  held-out cases mid-fill (held-out must stay >= {}).".format(MIN_HELDOUT),
        "- Ruler disclosure: model=`{}`, temperature_configured=`{}`, temperature_pinning=prose-only (both sides).".format(
            ruler["model"], ruler["temperature_configured"]),
        "- Train top-ups (non-failing fillers; near-ceiling risk): {}".format(", ".join(top_up) if top_up else "none"),
        "- Baseline-excluded cases (tool/network-dependent; no discrimination claim): {}".format(
            ", ".join(sorted(excluded)) if excluded else "none"),
        "- Council: rounds={}, unresolved={}, accepted_risks={}".format(
            council["rounds"],
            "; ".join(str(u) for u in council["unresolved"]) if council["unresolved"] else "none",
            "; ".join(str(a) for a in council["accepted_risks"]) if council["accepted_risks"] else "none"),
        "- Counts: train={} heldout={}".format(len(train_in), len(heldout_in)),
    ]
    runbook_md = "\n\n".join(
        block for block in (
            "# " + runbook_in["title"].strip(),
            runbook_in["intro"].strip(),
            runbook_in["next_steps"].strip(),
            runbook_in["limitations"].strip(),
            (runbook_in.get("notes") or "").strip() or None,
            "\n".join(appendix),
        ) if block
    ) + "\n"

    # Belt-and-suspenders on the two non-negotiables (constructed above, but a
    # future edit must not be able to break them silently):
    gs_text = json.dumps(golden_set, ensure_ascii=False)
    rl_text = json.dumps(runlog, ensure_ascii=False)
    if "split_hash" in golden_set:
        raise ValueError("internal: draft must not carry split_hash (must emit unfrozen)")
    for text, name in ((gs_text, "golden-set.json"), (rl_text, "RUNLOG")):
        if '"require_rubric"' in text:
            raise ValueError("internal: emitted {} must not contain a require_rubric key — "
                             "that key exists only to DISABLE the gate".format(name))
    for c in golden_set["cases"]:
        if c["split"] == "heldout" and c["rubric"] != []:
            raise ValueError("internal: held-out case {!r} rubric not empty".format(c["id"]))

    return golden_set, case_files, runlog, runbook_md, warnings


def emit_draft(payload):
    """build_draft + IO. Returns the CLI result object."""
    golden_set, case_files, runlog, runbook_md, warnings = build_draft(payload)
    output_dir = payload["output_dir"]
    os.makedirs(output_dir, exist_ok=True)

    written_cases = []
    for rel, content in sorted(case_files.items()):
        path = os.path.join(output_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content if content.endswith("\n") else content + "\n")
        written_cases.append(path)

    gs_path = os.path.join(output_dir, "golden-set.json")
    with open(gs_path, "w", encoding="utf-8") as fh:
        json.dump(golden_set, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    # Emitted input_file paths must resolve BEFORE the human invests rubric work
    # (agent-coach resolves them only at freeze time, inside compute_split_hash).
    for case in golden_set["cases"]:
        rel = case.get("input_file")
        if rel and not os.path.isfile(os.path.join(output_dir, rel)):
            raise ValueError("internal: emitted input_file {!r} does not resolve "
                             "next to golden-set.json".format(rel))

    rb_path = os.path.join(output_dir, "GOLDEN-SET-DRAFT-README.md")
    with open(rb_path, "w", encoding="utf-8") as fh:
        fh.write(runbook_md)

    rl_path = os.path.join(output_dir, "GOLDEN-SET-DRAFT-RUNLOG.json")
    with open(rl_path, "w", encoding="utf-8") as fh:
        json.dump(runlog, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    return {
        "ok": True,
        "written": {
            "golden_set": gs_path,
            "runbook": rb_path,
            "runlog": rl_path,
            "case_files": written_cases,
        },
        "counts": runlog["counts"],
        "warnings": warnings,
        "next": runlog["next_step"],
    }


def _load_payload(argv):
    if len(argv) > 1:
        with open(argv[1], "r", encoding="utf-8") as fh:
            return json.load(fh)
    data = sys.stdin.read()
    if not data.strip():
        raise ValueError("empty payload: pipe the JSON payload on stdin or pass a file path")
    return json.loads(data)


def run_cli(argv):
    try:
        payload = _load_payload(argv)
        result = emit_draft(payload)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        # Totality (agent-coach convention): structural defects become a
        # structured {ok:false}, never a raw traceback.
        print(json.dumps({"ok": False, "reason": "error: {}".format(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv))
