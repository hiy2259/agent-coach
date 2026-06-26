# `loop/<target>/` — state scaffold

These are the **empty init templates** copied into `loop/<target>/` when a run is
set up. They establish the staging area and the append-only logs. Full field
schemas: `references/data-formats.md`. The guarantees behind them:
`references/safety-invariants.md`.

## What ships here (and what does NOT)

| File | Role at init | Note |
|---|---|---|
| `prompt.current.md` | Staging copy of the target | Replace with the live target's contents at setup. The loop reads/promotes here and **never writes the live file** (S4). |
| `prompt.candidate.md` | Staging copy under test | `apply_change.py` writes the candidate change here; on MERGE it is promoted to `prompt.current.md`. |
| `history.jsonl` | Per-turn score trail | **Starts empty.** Append one JSON object per turn (`{turn, golden_set_version, decision, train/heldout before/after, eps_train, eps_heldout, change{target_id, rationale}, ts}`). |
| `failure-log.jsonl` | Wrong-answer notebook | **Starts empty.** Append one line per DISCARD/HALT (`{turn, result, change{before, after, rationale}, reason, candidate_input, ts}`). The Proposer reads this before proposing (S6); `candidate_input` seeds the next golden-set version. |
| `state.json` | Resume state machine | Not pre-seeded here — created/updated by the loop (`scripts/resume.py`) on the first turn. Single object, updated in place. |

> **`golden-set.json` is USER-PROVIDED — it is *not* a bundled template.** The
> human owns the inputs and the rubric (S5); the skill must not generate it. A
> worked reference lives at `examples/en/golden-set/golden-set.example.json`, and the
> full schema is in `references/data-formats.md`. Place the user's
> `golden-set.json` (and any `cases/*.input.txt`) into `loop/<target>/` at setup.

## JSONL files start empty — append, never rewrite

`history.jsonl` and `failure-log.jsonl` are **append-only audit logs**: one JSON
object per line, no enclosing array, no commas between lines. They are intentionally
empty at init. Never rewrite or reorder existing lines — only append. (This is
what makes the run auditable and `resume.py` safe.)

## Staging only — the live target is sacred until commit

Nothing here is the user's live file. The loop operates entirely on these staging
copies; the live target's bytes stay unchanged throughout the run and after any
abort. The human's end-of-run **`commit`** is the first and only write to the live
file (S4). The header comment in each `prompt.*.md` placeholder should be replaced
by the target's real contents at setup.
