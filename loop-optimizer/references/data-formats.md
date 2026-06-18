# Data formats — complete schemas

This is the authoritative, self-contained reference for every file and contract
the loop reads or writes. SKILL.md and the `scripts/` calls depend on these
shapes exactly; read this before writing any script invocation or hand-editing a
file.

> **Format SSOT note.** The data formats here are the single source of truth.
> They **supersede** any older notation in the design spec/plan (e.g. Markdown
> state files, or a single `margin` field). The current reality is: state and
> logs are **JSON / JSONL**, and the merge margin is split into **`eps_train`**
> and **`eps_heldout`**. Where an older document disagrees on *format*, this file
> wins; consult the spec/plan only for design rationale, not field shapes.

Conventions used below:
- **JSONL** files are append-only audit logs: **one JSON object per line**, no
  enclosing array, no commas between lines.
- A field prefixed with `_` (e.g. `_note`) is a comment the parser **ignores** —
  useful for inline documentation inside JSON.
- All `*_file` paths are **relative to the directory of the file that contains
  them** (see the `cases/` path rule under `golden-set.json`).

Files at a glance:

| File | Who writes it | Shape | Section |
|---|---|---|---|
| `golden-set.json` | **user-provided** | JSON object | [§4.4](#golden-setjson-44) |
| `run-config.json` | **user-provided** | JSON object | [§4.5](#run-configjson-45) |
| `history.jsonl` | the skill | JSONL (1 line/turn) | [§4.6](#historyjsonl-46) |
| `failure-log.jsonl` | the skill | JSONL (1 line/discard or halt) | [§4.6](#failure-logjsonl-46) |
| `state.json` | the skill | JSON object (single, updated) | [§4.6](#statejson-46) |
| **Change** contract | Proposer → code | JSON object (in-memory) | [§4.7](#change-proposer--code-47) |
| **Score** contract | Grader → code | JSON object (in-memory) | [§4.7](#score-grader--code-47) |

---

## `golden-set.json` (§4.4)

**User-provided.** The fixed exam: curated inputs + a yes/no rubric per input + a
frozen `train`/`heldout` split + evolution metadata. This is *not* a bundled
template — the user owns it (S5). Full worked example:
`examples/en/golden-set/golden-set.example.json`.

### Header (dataset-level) fields

| Field | Type | Meaning | Required |
|---|---|---|---|
| `target` | string | Relative path to the live target prompt/skill file | ✔ |
| `version` | string | Golden-set version id (e.g. `"v2"`); scores compare only *within* one version | ✔ |
| `parent_version` | string \| null | Version this evolved from (lineage) | ✔ |
| `created` | string (date) | When the set was first created | recommended |
| `updated` | string (date) | When it was last edited | recommended |
| `changelog` | string | What changed vs the parent version (e.g. which failure-derived case was added, what was retired) | recommended |
| `min_size` | object `{train, heldout}` | Minimum active cases per split; the size gate (S5) | ✔ |

### Case fields (`cases[]`)

| Field | Type | Meaning | Required |
|---|---|---|---|
| `id` | string | Stable identifier, tracked across versions | ✔ |
| `split` | `"train"` \| `"heldout"` | Which split; **frozen during a run** | ✔ |
| `input` **or** `input_file` | string | Inline text (short inputs) **or** a relative path to a file (code / large inputs). Provide **exactly one** | ✔ (one) |
| `rubric` | string[] | Array of yes/no criterion strings, **5–7 per input** | ✔ |
| `provenance` | `"seed"` \| `"bootstrap"` \| `"failure-log"` \| `"human"` | Where the case came from (evolution tracking) | ✔ |
| `added_in_version` | string | Version in which the case entered | ✔ |
| `realistic` | boolean | Is this a real production-like case? Realistic items are placed in held-out first | ✔ |
| `status` | `"active"` \| `"retired"` | Retired = excluded from scoring, kept for the record | ✔ |
| `notes` | string | What capability/failure this case targets | recommended |
| `tags` | string[] | Classification labels | optional |

### Semantics you must respect

- **Scoring.** Per case, score = `(rubric criteria passed) / (criteria total)`.
  Aggregate **per split** over **active** cases only (`status: "active"`).
  Retired cases are excluded from scoring but preserved for history. The rubric
  is not "the answer" — it is the *criteria* for a good answer.
- **`input` vs `input_file`.** Short inputs go inline in `input`. Code or large
  inputs go in a file referenced by `input_file`. Exactly one of the two per
  case.
- **`cases/` path rule.** `input_file` is a path **relative to the directory
  containing `golden-set.json`**. The convention is to keep these under a
  `cases/` subfolder, e.g. `"./cases/<id>.input.txt"`. (In the example,
  `golden-set.json` and `cases/` live side by side, so `./cases/debug-race-
  condition.input.txt` resolves next to the JSON.)
- **Evolution spine.** `version` / `parent_version` / `changelog` plus per-case
  `provenance` / `added_in_version` / `status` record how the set grows between
  runs. A `candidate_input` from `failure-log.jsonl` becomes a next-version case
  candidate (S6). Always record `golden_set_version` on each `history.jsonl` row;
  **never compare scores across versions directly.**
- **Frozen within a run.** The set and split are frozen while the loop runs:
  `split_goldenset.py` computes a `split_hash` over the active cases + split, and
  it is re-checked every turn. Any mid-run change is an error.
- **Advanced (deferred, v2).** `discrimination`, `failure_ref`, and per-criterion
  `id` / `weight` are not part of v1.

### Short example

```json
{
  "target": "./agents/dev-agent.md",
  "version": "v2",
  "parent_version": "v1",
  "created": "2026-06-10",
  "updated": "2026-06-16",
  "changelog": "Added a real concurrency-bug case from the failure log; retired the non-discriminating 'print-hello'.",
  "min_size": { "train": 5, "heldout": 3 },
  "cases": [
    {
      "id": "debug-race-condition",
      "split": "train",
      "provenance": "failure-log",
      "added_in_version": "v2",
      "realistic": true,
      "status": "active",
      "tags": ["debugging", "concurrency"],
      "notes": "From a real miss where the v1 agent overlooked a check-then-act race.",
      "input_file": "./cases/debug-race-condition.input.txt",
      "rubric": [
        "Did it name the race condition (check-then-act) as the real cause?",
        "Did it fix it correctly with a lock or atomic operation?",
        "Did it avoid inventing a cause not present in the code?",
        "Did it keep the existing withdraw signature intact?",
        "Did it explain in a line or two why that is the cause?"
      ]
    }
  ]
}
```

---

## `run-config.json` (§4.5)

**User-provided.** Configures how the Runner executes the target "like real use"
and controls the loop. Full example: `examples/en/run-config.example.json`.

| Block | Field | Type | Meaning |
|---|---|---|---|
| (top) | `target` | string | Relative path to the live target file |
| (top) | `golden_set` | string | Relative path to `golden-set.json` |
| `runner` | `model` | string | Model id — **must match the user's real production runtime** so `eps` reflects real noise |
| `runner` | `temperature` | number | Real-use temperature (the variance source for `eps`) |
| `runner` | `max_output_tokens` | number | Output cap for target runs |
| `grader` | `model` | string | Grader model (kept stable) |
| `grader` | `temperature` | number | **Must be `0`** (zero grading variance) |
| `grader` | `version_id` | string | Pin id recorded for drift audit (e.g. a date) |
| `proposer` | `model` | string | Proposer model — **must differ from `grader.model`** (propose ≠ grade) |
| `proposer` | `temperature` | number | Low temperature for focused proposals |
| `calibration` | `k_calib` | number | Runner re-runs for noise calibration (default 5) |
| `loop` | `n_turns` | number | Max turns (default 10) |
| `loop` | `no_progress_k` | number | Stop after K turns with no MERGE/SUB_KEEP (default 3) |
| `loop` | `subtraction_every` | number | Try a subtraction every Nth turn (default 3) |
| `budget` | `max_usd_total` | number | Total spend cap — the **code-enforced** stop (`resume.py op=should_stop`) |
| `budget` | `max_usd_per_turn` | number | **Advisory** pre-turn cost estimate (size-of-set × calls); NOT a hard mid-turn stop — only `max_usd_total` is enforced |
| `tools` | `mode` | `"none"` \| `"mocked"` | `none` = text-in/text-out target (v1 default). `mocked` = tool-using target |

> **`tools.mode: "mocked"` is under-specified in v1** — the mock definition format
> is not yet specified. The v1 default is `none` (text-only targets). Do **not**
> invent a mock schema; tool-using targets are a v2 concern. `live-sandboxed` is
> also v2.

### Short example

```json
{
  "target": "./agents/dev-agent.md",
  "golden_set": "./golden-set.json",
  "runner":   { "model": "claude-opus-4-8", "temperature": 0.7, "max_output_tokens": 4096 },
  "grader":   { "model": "claude-sonnet-4-6", "temperature": 0, "version_id": "2026-06-16" },
  "proposer": { "model": "claude-opus-4-8", "temperature": 0.3 },
  "calibration": { "k_calib": 5 },
  "loop":     { "n_turns": 10, "no_progress_k": 3, "subtraction_every": 3 },
  "budget":   { "max_usd_total": 20.0, "max_usd_per_turn": 3.0 },
  "tools":    { "mode": "none" }
}
```

---

## `history.jsonl` (§4.6)

Written by the skill — **one line per turn**, append-only. The per-turn score
trail the human reviews at the end.

| Field | Type | Meaning |
|---|---|---|
| `turn` | number | Turn index (1-based) |
| `golden_set_version` | string | Version scored against (**required**; blocks cross-version comparison) |
| `grader_version_id` | string | The grader's pinned `version_id` this turn (F-25; lets cross-run trends flag grader drift vs target change) |
| `decision` | `"MERGE"` \| `"DISCARD"` \| `"HALT"` \| `"SUB_KEEP"` \| `"SUB_DROP"` | What code decided this turn |
| `train_before` | number | Train score before the change (0–1) |
| `train_after` | number | Train score after the change |
| `heldout_before` | number | Held-out score before |
| `heldout_after` | number | Held-out score after |
| `eps_train` | number | Calibrated train noise margin used this turn |
| `eps_heldout` | number | Calibrated held-out noise margin used this turn |
| `change` | object `{target_id, rationale}` | **Summary** of the change: which target + the one-line rationale (the full before/after lives in `failure-log.jsonl` for discards) |
| `ts` | string (ISO 8601) | Timestamp |

> **Decision vocabulary.** `MERGE` (real gain, kept) · `DISCARD` (an *addition*
> reverted: no real gain) · `HALT` (overfit: train↑ but held-out↓ past
> `eps_heldout`; terminal) · `SUB_KEEP` (a subtraction kept) · `SUB_DROP` (a
> subtraction reverted — the removed rule restored). `SUB_DROP` undoes a
> *removal*; `DISCARD` undoes an *addition* — they are distinct.

### Short example (one line per turn)

```jsonl
{"turn": 1, "golden_set_version": "v2", "decision": "MERGE", "train_before": 0.70, "train_after": 0.78, "heldout_before": 0.65, "heldout_after": 0.70, "eps_train": 0.03, "eps_heldout": 0.04, "change": {"target_id": "dev-agent.md", "rationale": "Add guidance to separate decisions from action items"}, "ts": "2026-06-16T10:00:00Z"}
{"turn": 4, "golden_set_version": "v2", "decision": "HALT", "train_before": 0.78, "train_after": 0.85, "heldout_before": 0.70, "heldout_after": 0.58, "eps_train": 0.03, "eps_heldout": 0.04, "change": {"target_id": "dev-agent.md", "rationale": "Fill gaps by inferring from context"}, "ts": "2026-06-16T10:09:00Z"}
```

---

## `failure-log.jsonl` (§4.6)

Written by the skill — **one line per DISCARD or HALT**, append-only. The
"wrong-answer notebook" and the **evolution bridge**: the Proposer reads it to
avoid repeats (S6), and `candidate_input` seeds the next golden-set version.

| Field | Type | Meaning |
|---|---|---|
| `turn` | number | Turn the attempt was made |
| `result` | `"discarded"` \| `"halted"` | Why it landed here |
| `change` | object `{before, after, rationale}` | The **full** attempted edit (note: includes `before`/`after`, unlike `history.jsonl`) |
| `reason` | string | Human-readable explanation (e.g. "train +1pp within eps_train — noise", "held-out −12pp > eps_heldout — overfit") |
| `candidate_input` | string \| null | **Evolution bridge:** a candidate input for the *next* golden-set version (e.g. an input that exposes the hallucination this overfit revealed). `null` if none |
| `ts` | string (ISO 8601) | Timestamp |

> **Why `candidate_input` matters (S6).** A halted overfit usually means the
> change exploited a gap the golden set doesn't yet cover. Recording an input
> that *would* catch that gap turns each failure into a curation lead for the
> human's between-runs growth of the set. It is the literal bridge from
> `failure-log.jsonl` to the next `golden-set.json` `version`.

### Short example (one line per failure)

```jsonl
{"turn": 2, "result": "discarded", "change": {"before": "Summarize the minutes in five sentences or fewer.", "after": "Summarize the minutes in five sentences or fewer, in a formal register.", "rationale": "Force a formal tone"}, "reason": "train +1pp (within eps_train=0.03 — noise level)", "candidate_input": null, "ts": "2026-06-16T10:03:00Z"}
{"turn": 4, "result": "halted", "change": {"before": "Summarize the minutes in five sentences or fewer.", "after": "Infer and fill in content not present in the minutes when summarizing.", "rationale": "Fill gaps by inferring from context"}, "reason": "held-out −12pp > eps_heldout=0.04 (overfit — train rose only by hallucinating)", "candidate_input": "An input asking for a decision not stated in the minutes — to test hallucination resistance; candidate for golden set v3", "ts": "2026-06-16T10:09:00Z"}
```

---

## `state.json` (§4.6)

Written by the skill — a **single object, updated in place** (not append-only).
Drives idempotent resume (`scripts/resume.py`).

| Field | Type | Meaning |
|---|---|---|
| `turn` | number | Current turn |
| `phase` | `"proposed"` \| `"applied"` \| `"graded"` \| `"merged"` \| `"discarded"` | Last completed phase in the turn state machine (resume re-enters from here) |
| `golden_set_version` | string | Version in effect (**orchestrator-populated**, informational — `resume.py` does not write this; F-14) |
| `split_hash` | string | Hash of active cases + split (**orchestrator-populated**; the authoritative within-run freeze check is `split_goldenset.py op=verify`, re-run every turn — `resume.py` does not write this; F-14) |
| `current_prompt_hash` | string | Hash of `prompt.current.md`; used to tell whether a promote already happened (idempotent resume). Written by `resume.py op=promote_done`. |
| `no_progress_count` | number | Consecutive turns without MERGE/SUB_KEEP (stop at `no_progress_k`) |
| `candidate_pending` | boolean | Is a candidate staged but not yet resolved? |
| `budget_spent_usd` | number | Cumulative spend (checked against `budget` caps) |
| `last_scored_prompt_hash` | string \| null | F-06 carry-over: hash of the prompt the cached scores below belong to |
| `last_train` | number \| null | F-06 carry-over: last measured train score of `last_scored_prompt_hash` (reused as next turn's before-score when the prompt is unchanged) |
| `last_heldout` | number \| null | F-06 carry-over: last measured held-out score of `last_scored_prompt_hash` |
| `ts` | string (ISO 8601) | Last update |

> **Resume idempotency (M1).** On re-entry, `resume.py` reads `phase` and resumes
> from the last completed step. Promotion (`candidate → current`) happens
> **before** recording `phase: "merged"`, and `current_prompt_hash` reveals
> whether it already occurred — so an interrupted-then-resumed run never
> double-applies a merge.

### Short example

```json
{
  "turn": 4,
  "phase": "graded",
  "golden_set_version": "v2",
  "split_hash": "sha256:3f2a9c0b...c91",
  "current_prompt_hash": "sha256:8b1d77e2...4e7",
  "no_progress_count": 0,
  "candidate_pending": true,
  "budget_spent_usd": 7.40,
  "last_scored_prompt_hash": "sha256:8b1d77e2...4e7",
  "last_train": 0.78,
  "last_heldout": 0.70,
  "ts": "2026-06-16T10:09:30Z"
}
```

---

## Internal model↔code contracts (§4.7)

These are **in-memory JSON objects** passed between an actor and a script during a
turn. They are not persisted as files, but their shape is exact — the scripts
parse them directly.

### Change (Proposer → code) (§4.7)

Emitted by the Proposer, consumed by `verify_change.py`.

| Field | Type | Meaning |
|---|---|---|
| `target_id` | string | The target file id being edited (e.g. `dev-agent.md`) |
| `before` | string | A **unique** substring of the current target (verbatim) — the edit site |
| `after` | string | Replacement text; for `subtraction`, `before` with the chosen rule removed |
| `rationale` | string | One or two sentences: the rubric weakness targeted and why it should generalize |
| `kind` | `"edit"` \| `"subtraction"` | Addition/edit, or a deliberate rule removal |

Mechanically checked (S3): `before` must occur **exactly once** and the edit must
be **local** (bounded span/delta), else `verify_change.py` rejects it unmeasured.

```json
{
  "target_id": "dev-agent.md",
  "before": "Summarize the minutes in five sentences or fewer.",
  "after": "Summarize the minutes in five sentences or fewer; if a decision is not stated, mark it unspecified rather than inferring one.",
  "rationale": "Targets held-out hallucination cases by forbidding invented decisions; should generalize beyond train.",
  "kind": "edit"
}
```

### Score (Grader → code) (§4.7)

Emitted by the Grader (per case), consumed by the scoring aggregation that feeds
`score_compare.py`.

| Field | Type | Meaning |
|---|---|---|
| `case_id` | string | The case scored |
| `results` | array of `{criterion_index, passed}` | One entry **per rubric criterion**, `criterion_index` zero-based, in rubric order |
| `passed` | number | Count of `passed: true` results |
| `total` | number | Number of criteria |
| `split` | `"train"` \| `"heldout"` | Which split this case belongs to. **Attached by the orchestrator, NOT emitted by the Grader** — see the note below. |

> **Who attaches `split` (H3).** The Grader emits a Score **without** `split`: it
> must stay blind to whether an output is a train or held-out case, or it could
> grade toward a wanted result (see the Grader contract — blindness is
> intentional). But `aggregate_scores.py` **requires** `split` on every Score to
> bucket it per split. So the orchestrator is the one that joins it on: just
> before aggregating, it looks each `case_id` up in the frozen `golden-set.json`
> (`id → split`) and stamps `split` onto the Score. A missing `split` is a hard
> error at aggregation, not a silent mis-bucket. The example below is the Grader's
> raw emission (no `split`); the orchestrator augments it before the aggregator
> sees it.

Per-split aggregate (active cases only): `Σ passed / Σ total`, computed by
`scripts/aggregate_scores.py` (F-24) — the one deterministic home for this
reduction. It also echoes the per-case vector (`per_case`), which the
orchestrator MAY persist (e.g. a `scores.jsonl`) to unlock later statistical
gates, per-case weighting, or discrimination analysis. A case with more criteria
weighs proportionally more (sum-of-counts, not mean-of-rates).

```json
{
  "case_id": "debug-race-condition",
  "results": [
    { "criterion_index": 0, "passed": true },
    { "criterion_index": 1, "passed": true },
    { "criterion_index": 2, "passed": true },
    { "criterion_index": 3, "passed": false },
    { "criterion_index": 4, "passed": true }
  ],
  "passed": 4,
  "total": 5
}
```
