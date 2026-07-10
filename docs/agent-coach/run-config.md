# Configuring the run

> The run config (`run-config.json`) tells the loop **how to run your target the
> way it runs in real use**, and which model plays each role. Two settings here
> carry the whole measurement. First, the **Runner must use your production model
> and temperature** — otherwise the noise the loop calibrates is not your real
> noise. Second, the **roles must stay separated** — otherwise grading quietly
> becomes a self-graded exam. Get either one wrong and every score downstream
> measures the wrong thing, no matter how good your golden set is.

This page is the field-by-field reference for `run-config.json`, plus the
pre-flight check that enforces its rules. For the *exam* this config runs
against, see [`golden-set.md`](./golden-set.md); for the end-to-end run, see
[`running.md`](./running.md); for the authoritative JSON schema, see
[`../../skills/agent-coach/references/data-formats.md`](../../skills/agent-coach/references/data-formats.md).

---

## A minimal config

If you already have a golden set, this warm-start config is all you need. (The
same file ships at
[`../../examples/agent-coach/en/run-config.example.json`](../../examples/agent-coach/en/run-config.example.json),
ready to copy.)

```json
{
  "_note": "Runtime/loop config example. Replace the model IDs with your real values. Key rules: grader != proposer (propose != grade), and runner must match your real-use model/temperature. Fields prefixed with '_' are ignored.",
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

Reading it block by block:

- **`_note`** is a comment for humans. The parser ignores any field whose name
  starts with `_`, so you can annotate the file freely.
- **Top level.** `target` and `golden_set` point at the live target file and its
  exam. Both are relative paths.
- **`runner`** uses `claude-opus-4-8` at **temperature 0.7** — the *same model and
  temperature you run in production*. That way the noise the loop calibrates is
  your real noise, not the artificially quiet noise of `temperature: 0`.
- **`grader`** uses a *different* model (`claude-sonnet-4-6`) at **temperature 0**,
  with a pinned `version_id` — a stable measuring stick that adds no randomness of
  its own. Keeping it a different model from the proposer is what keeps grading
  honest (propose ≠ grade).
- **`proposer`** uses `claude-opus-4-8` at a low temperature (**0.3**) for focused,
  single edits. Here it happens to share the runner's model, and that is fine —
  the only hard separation rules are proposer ≠ grader and bootstrapper ≠ grader.
- **`calibration.k_calib: 5`** re-runs the Runner 5 times to measure the noise
  margin `eps`; 5 is the recommended minimum.
- **`loop`** caps the run at 10 turns, stops after 3 turns without progress, and
  tries a subtraction (removing a rule) every 3rd turn.
- **`budget`** caps total spend at `$20` and per-turn spend at `$3`; the run stops
  when either cap is hit.
- **`tools.mode: "none"`** means the target is plain text-in / text-out (the v1
  default).

There is no `bootstrapper` block here because this is a warm start. Add one — with
a model different from the grader — only for a
[cold start](./running.md#cold-start-no-golden-set-yet).

---

## The three rules that keep measurement honest

Most of `run-config.json` is ordinary knobs: turn counts, budget caps. But three
settings are not matters of preference — they decide whether the loop measures
real quality or fools itself. The pre-flight check below **blocks the run** when
the hard rules are violated.

**1. The Runner is your production runtime.** `runner.model` and
`runner.temperature` must be the model and temperature you actually ship with. The
loop derives its noise margins (`eps_train` / `eps_heldout`) from how much the
Runner's output varies between identical runs. If you set `temperature: 0` to get
a "cleaner" number, you calibrate a noise band you will never see in production —
and the gate will happily merge changes that don't survive real use. Use your real
value (for example `0.7`), **not** `0`.

**2. The Grader is a fixed, zero-variance ruler.** `grader.temperature` must be
`0`, and `grader.version_id` records *which* ruler you used. At temperature 0,
grading the same text twice returns the identical score — the Grader contributes
**zero** randomness, so every bit of measured noise comes from the Runner, where
it belongs (S7). The pinned version lets you audit later that a cross-run trend
reflects the *target* improving, not the *ruler* drifting.

**3. The one who proposes never grades.** `proposer.model` must differ from
`grader.model` (and at cold start, `bootstrapper.model` must also differ from
`grader.model`). A model asked "did your *own* change help?" is primed to say
yes — the self-graded exam (S5). Putting propose and grade on different models is
what makes the separation real rather than nominal. The proposer *may* share the
runner's model; the only hard wall is against the grader.

---

## Field reference (every block)

| Block | Property | Type | What it means | How to set it |
|---|---|---|---|---|
| (top) | `target` | string | Relative path to the live target file | The same file the golden set's `target` names |
| (top) | `golden_set` | string | Relative path to `golden-set.json` | e.g. `./golden-set.json` |
| `runner` | `model` | string | The model that runs the target | **Must match your real production runtime**, so measured noise is real |
| `runner` | `temperature` | number | Real-use temperature — the source of the variance behind `eps` | Your actual production temperature, e.g. `0.7` (not `0`) |
| `runner` | `max_output_tokens` | number | Output cap for each target run | Enough for a full answer, e.g. `4096` |
| `grader` | `model` | string | The grading model (kept the same across the run) | A capable model that is **different from the proposer** |
| `grader` | `temperature` | number | **Must be `0`** — grading adds zero variance (S7) | Always `0` (the pre-flight errors otherwise) |
| `grader` | `version_id` | string | A pin recorded so grader drift can be audited later | A date or tag, e.g. `"2026-06-16"` |
| `proposer` | `model` | string | The model that proposes one change per turn | **Must differ from `grader.model`** (propose ≠ grade) |
| `proposer` | `temperature` | number | Low temperature for focused proposals | e.g. `0.3` |
| `bootstrapper` | `model` | string (optional) | Drafts candidate inputs during cold start | Only needed at cold start; if present, **must differ from `grader.model`** |
| `calibration` | `k_calib` | number | How many times the Runner is re-run to measure noise | **≥ 5** (a small k makes `eps` a shaky estimate → warning) |
| `loop` | `n_turns` | number | Maximum number of turns | Default `10`; raise it for a longer search (cost rises with it) |
| `loop` | `no_progress_k` | number | Stop after K consecutive turns with no `MERGE`/`SUB_KEEP` | Default `3` |
| `loop` | `subtraction_every` | number | Try a subtraction every Nth turn | Default `3` |
| `budget` | `max_usd_total` | number | Cap on total spend (a hard constraint, not a suggestion) | Size it from `n_turns` × set size; the run stops when hit |
| `budget` | `max_usd_per_turn` | number | Cap on per-turn spend | A guardrail against a single runaway turn |
| `tools` | `mode` | `"none"` \| `"mocked"` | `none` = plain text-in/text-out target (the v1 default) | Keep `"none"`; `"mocked"` is under-specified and a v2 concern |

---

## Pre-flight validation

Always run `validate_config.py` **before** turn 1. It stops the run on any error,
so a misconfigured role can never quietly invalidate a whole run:

- **Errors (block the run):** a missing `runner`/`grader`/`proposer` block or
  `model` field · `grader.temperature ≠ 0` · `proposer.model == grader.model` ·
  `bootstrapper.model == grader.model` (when a bootstrapper is present). Model ids
  are compared ignoring case and whitespace, so `"Sonnet"` vs `"sonnet"` cannot
  sneak a self-grading run past the check.
- **Warnings (proceed with caution):** `runner.temperature == 0` (no variance, so
  `eps` collapses to its floor) · `k_calib < 5` · missing `grader.version_id` ·
  missing `budget` block.

```bash
printf '%s' '{"config_path":"./run-config.json"}' | python3 skills/agent-coach/scripts/validate_config.py
```

(Run scripts from the repository root, as shown — the path is relative to the
project root, not to this `docs/` page.)

---

## See also

- [`golden-set.md`](./golden-set.md) — the exam this config runs against; where
  most of the leverage lives.
- [`running.md`](./running.md) — the run end to end: validate → baseline → loop →
  commit or revert as a batch, plus cold start and resuming.
- [`../../skills/agent-coach/references/data-formats.md`](../../skills/agent-coach/references/data-formats.md)
  — the authoritative `run-config.json` schema, field by field.
- [`../../skills/agent-coach/references/safety-invariants.md`](../../skills/agent-coach/references/safety-invariants.md)
  — S1–S7, including S5 (role separation) and S7 (noise measured from Runner
  variance, grader at temperature 0).
