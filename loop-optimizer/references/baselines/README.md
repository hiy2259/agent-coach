# Baselines — cross-family check ledger

## `dual-judge-ledger.jsonl`

An **append-only, record-only** ledger of when the **dual-judge cross-family
check** (the manual tripwire described in SKILL.md "Golden set is frozen…" and
`.omc/specs/loop-optimizer-dualjudge-diagnostic.md`) last ran, and under what
provenance. It exists so that, at the moment a human is about to **trust a
dogfood verdict**, a small advisory helper can answer: *"has the decorrelated
second-judge sanity check ever run against THIS ruler + THIS golden set + THIS
split — or has the ruler/set/split drifted since?"*

**This ledger is not a gate and not a safety net.** Nothing blocks on it. It is
a surfacing aid. The cross-family re-check itself is a deliberate **manual**
action the human runs (the dual-judge comparator body is intentionally on HOLD —
see the honest-gap note in SKILL.md). See `check_cross_validation.py` for the
advisory WARN that consumes this file.

### Schema (one JSON object per line)

| Field | Type | Meaning |
|---|---|---|
| `date` | string (`YYYY-MM-DD`) | When the cross-family check ran |
| `grader_version_id` | string | The grader (ruler) `version_id` it ran under |
| `golden_set_version` | string | Golden-set version it ran against |
| `split_hash` | string | Frozen `split_hash` of the active cases + split |
| `verdict` | string | Outcome — e.g. `"hold"` (no judge blind spot found) or `"trigger"` |

### How to append a new entry

After running a cross-family check, append exactly one line capturing the
provenance it ran under. Do **not** rewrite or reorder existing lines (append-only
history). The advisory WARN compares the current run's provenance against the
**last** line of this file.

### Current entries

- `2026-06-23` — grader `claude-opus-4-8`, goldenset `v2`, verdict `hold`.
  47/48 (97.9%) Claude-vs-GPT agreement; the single disagreement adjudicated as
  an ambiguous rubric, not a judge blind spot. Full write-up:
  `.omc/specs/loop-optimizer-dualjudge-diagnostic.md`.
