#!/usr/bin/env python3
"""validate_config.py -- G: check run-config.json invariants BEFORE a run.

The skill's safety story assumes actor separation (propose != grade != seed) and
a sane measurement setup (temp-0 grader, temp>0 runner so eps is real). Nothing
previously checked these, so a config could silently violate them -- e.g. the
Bootstrapper and Grader set to the same model (shared blind spots), or the
Runner at temperature 0 (no run-to-run variance -> eps collapses to the floor
and the merge gate degenerates). This script turns those into loud, structured
errors/warnings the orchestrator must act on at setup time.

ERRORS (must block the run):
  - missing runner / grader / proposer block, or a missing model in one
  - grader.temperature != 0          (score comparability depends on it -- S7)
  - proposer.model == grader.model   (propose != grade -- self-grading inflates)
  - bootstrapper.model == grader.model (cold-start cases share the grader's blind
                                        spots -> a self-consistent illusion)

WARNINGS (proceed with caution):
  - runner.temperature == 0   (no variance -> eps ~ floor, gate barely discriminates)
  - calibration.k_calib < 5   (eps estimate is noisy at small k)
  - grader.version_id missing (no drift audit trail)
  - budget block missing      (budget is a first-class constraint)

Input JSON:
  {"config_path": "./run-config.json"}   # OR  {"config": {<run-config inline>}}
  # if neither key is present, the payload itself is treated as the run-config.

Output JSON:
  {"ok": true/false, "errors": [...], "warnings": [...]}
"""

import json
import sys

try:
    from _common import load_payload, emit
except ImportError:
    import os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _common import load_payload, emit


def _load_config(payload):
    if isinstance(payload, dict) and payload.get("config") is not None:
        return payload["config"]
    if isinstance(payload, dict) and payload.get("config_path"):
        with open(payload["config_path"], "r", encoding="utf-8") as fh:
            return json.load(fh)
    return payload  # the payload itself is the run-config


def _norm_model(m):
    """Normalize a model id for identity comparison (case/whitespace-insensitive)
    so a one-character difference can't defeat the actor-separation check."""
    return str(m).strip().lower() if m else None


def _num(x):
    """Best-effort float; None if not numeric (so the pure function returns a
    structured error instead of raising on e.g. temperature: 'high')."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def validate_config(config):
    """Pure check. Returns {ok, errors, warnings}."""
    errors = []
    warnings = []

    if not isinstance(config, dict):
        return {"ok": False, "errors": ["run-config must be a JSON object"], "warnings": []}

    runner = config.get("runner")
    grader = config.get("grader")
    proposer = config.get("proposer")
    bootstrapper = config.get("bootstrapper")

    for name, block in (("runner", runner), ("grader", grader), ("proposer", proposer)):
        if not isinstance(block, dict):
            errors.append("missing or malformed '{}' block".format(name))
        elif not block.get("model"):
            errors.append("'{}.model' is required".format(name))

    # Grader must be deterministic, or before/after were measured by different rulers.
    if isinstance(grader, dict) and grader.get("model"):
        gtemp = grader.get("temperature")
        gt = _num(gtemp)
        if gt is None or gt != 0.0:
            errors.append(
                "grader.temperature must be 0 (numeric) for comparable scores, got {!r}".format(gtemp)
            )

    # Actor separation: propose != grade, seed != grade. Compare NORMALIZED ids
    # so "Sonnet" vs "sonnet" (or a stray space) can't sneak a self-grading run
    # past the check.
    gmodel = _norm_model(grader.get("model")) if isinstance(grader, dict) else None
    pmodel = _norm_model(proposer.get("model")) if isinstance(proposer, dict) else None
    bmodel = _norm_model(bootstrapper.get("model")) if isinstance(bootstrapper, dict) else None
    rmodel = _norm_model(runner.get("model")) if isinstance(runner, dict) else None
    if gmodel and pmodel and pmodel == gmodel:
        errors.append(
            "proposer.model == grader.model ({!r}): the proposer must differ from the grader "
            "(a player must not referee their own game).".format(grader.get("model"))
        )
    if gmodel and bmodel and bmodel == gmodel:
        errors.append(
            "bootstrapper.model == grader.model ({!r}): cold-start input drafting must differ "
            "from grading, or they share blind spots.".format(grader.get("model"))
        )

    # tools.mode (F-26): only "none" (text-in/text-out target) is implemented in
    # v1. "mocked"/tool-using targets have NO defined behavior, so a config that
    # sets one would run against an unspecified harness. Block it until the mock
    # contract exists, rather than silently proceeding as if it were supported.
    tools = config.get("tools")
    if isinstance(tools, dict):
        tmode = tools.get("mode")
        if tmode is not None and tmode != "none":
            errors.append(
                "tools.mode = {!r}: only 'none' (text-in/text-out target) is implemented in v1; "
                "'mocked'/tool-using targets have no defined behavior yet. Set tools.mode to 'none' "
                "or omit it.".format(tmode)
            )

    # Warnings: degenerate but not fatal.
    if isinstance(runner, dict):
        rt = _num(runner.get("temperature"))
        if rt is not None and rt == 0.0:
            warnings.append(
                "runner.temperature == 0: no run-to-run variance, so eps collapses to the floor "
                "and the merge gate barely discriminates. Use the real production temperature."
            )
    # Runner vs grader (GAP-2): the noise model treats the Runner as the variance
    # source (temp>0) and the Grader as a fixed temp-0 ruler. The SAME model in
    # both roles makes that separation nominal -- the grader can favour the
    # runner's own style (a subtler self-grading). WARN, not ERROR: the docs'
    # separation rules don't forbid it and a deliberate same-model setup is a
    # legitimate (if weaker) choice, so surface it rather than block.
    if gmodel and rmodel and rmodel == gmodel:
        warnings.append(
            "runner.model == grader.model ({!r}): the grader scores the runner's own output, "
            "so the player/referee separation is weaker. Prefer a distinct grader model.".format(
                grader.get("model"))
        )
    calib = config.get("calibration") or {}
    kc = _num(calib.get("k_calib"))
    if kc is not None and kc < 5:
        warnings.append(
            "calibration.k_calib = {}: eps is a noisy estimate at small k; consider >= 5.".format(calib.get("k_calib"))
        )
    if isinstance(grader, dict) and not grader.get("version_id"):
        warnings.append("grader.version_id missing: no drift-audit trail for the grader.")
    if not config.get("budget"):
        warnings.append("no 'budget' block: budget is a first-class constraint; set max_usd caps.")

    return {"ok": len(errors) == 0, "errors": errors, "warnings": warnings}


def run_cli(argv):
    try:
        payload = load_payload(argv)
        config = _load_config(payload)
        result = validate_config(config)
    except (ValueError, OSError) as exc:
        emit({"ok": False, "errors": ["input error: {}".format(exc)], "warnings": []})
        return 1
    emit(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(run_cli(sys.argv[1:]))
