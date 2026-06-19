# Configuring the run

> The run config (`run-config.json`) tells the loop **how to run your target "like
> real use"** and who plays each role. Two things here are load-bearing: the
> **Runner must match your production model and temperature** — or the noise the loop
> calibrates is not your real noise — and the **actors must stay separated** — or
> grading quietly becomes a self-graded exam. Get these wrong and every score
> downstream measures the wrong thing, no matter how good your golden set is.

This page is the field-by-field reference for `run-config.json` and the pre-flight
check that enforces it. For the *exam* this config runs against, see
[`golden-set.md`](./golden-set.md); for the end-to-end run, see
[`running.md`](./running.md); for the authoritative JSON schema see
[`../loop-optimizer/references/data-formats.md`](../loop-optimizer/references/data-formats.md).

---

## A minimal config

This warm-start config (the same one ships at
[`../examples/en/run-config.example.json`](../examples/en/run-config.example.json)
for copy-paste) is all you need when you already have a golden set:

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

- **`_note`** is a human comment the parser ignores (any field whose name starts
  with `_`) — use it to annotate the file.
- **Top level.** `target` and `golden_set` point at the live file and its exam —
  both relative paths.
- **`runner`** uses `claude-opus-4-8` at **temperature 0.7** — the *same model and
  temperature you run in production*, so the noise the loop calibrates is your real
  noise (not an artificially quiet `temperature: 0`).
- **`grader`** uses a *different* model (`claude-sonnet-4-6`) at **temperature 0**
  with a pinned `version_id` — a stable, zero-variance ruler. Using a different model
  is what keeps grading honest (propose ≠ grade).
- **`proposer`** uses `claude-opus-4-8` at a low **0.3** for focused, single edits.
  It happens to share the runner's model, which is fine — the only hard separation
  rule is proposer ≠ grader (and bootstrapper ≠ grader).
- **`calibration.k_calib: 5`** re-runs the Runner 5× to measure `eps`; 5 is the
  recommended floor.
- **`loop`** caps the run at 10 turns, stops after 3 no-progress turns, and tries a
  subtraction every 3rd turn.
- **`budget`** caps total spend at `$20` and per-turn spend at `$3` — the run halts
  when either is hit.
- **`tools.mode: "none"`** = a plain text-in/text-out target (the v1 default).

There is no `bootstrapper` block here because this is a warm start; add one — with a
model different from the grader — only for
[cold start](./running.md#cold-start-no-golden-set-yet).

---

## The three rules that keep measurement honest

Most of `run-config.json` is ordinary knobs (turn count, budget caps). But three
settings are not preferences — they are the difference between a loop that measures
real quality and one that fools itself. The pre-flight check below **blocks the run**
on the hard ones.

**1. The Runner is your production runtime.** `runner.model` and
`runner.temperature` must be the model and temperature you actually ship. The loop
derives its noise margins (`eps_train` / `eps_heldout`) from how much the Runner's
output wobbles between identical runs — so if you quiet it to `temperature: 0` for a
"cleaner" number, you calibrate a noise band you will never see in production, and
the gate will happily merge changes that don't survive real use. Set it to your real
`0.7` (or whatever you run), **not** `0`.

**2. The Grader is a fixed, zero-variance ruler.** `grader.temperature` must be `0`,
and `grader.version_id` pins *which* ruler you used. Temperature 0 means re-grading
the same text returns the identical score — the Grader contributes **zero** variance,
so every bit of measured noise comes from the Runner, where it belongs (S7). The pin
lets you later audit that a cross-run trend reflects the *target* improving, not the
*ruler* drifting.

**3. The one who proposes never grades.** `proposer.model` must differ from
`grader.model` (and, at cold start, `bootstrapper.model` must differ from
`grader.model`). A model asked "did your *own* change help?" is primed to say yes —
the self-graded exam (S5). Keeping propose and grade on different models is what
makes the separation real rather than nominal. The proposer *may* share the runner's
model; the only hard wall is against the grader.

---

## Field reference (every block)

| Block | Property | Type | What it means | How to set it |
|---|---|---|---|---|
| (top) | `target` | string | Relative path to the live target file | The same file as the golden set's `target` |
| (top) | `golden_set` | string | Relative path to `golden-set.json` | e.g. `./golden-set.json` |
| `runner` | `model` | string | The model that runs the target | **Must match your real production runtime** so measured noise is real |
| `runner` | `temperature` | number | Real-use temperature — the variance source for `eps` | Your actual production temperature, e.g. `0.7` (not `0`) |
| `runner` | `max_output_tokens` | number | Output cap for each target run | Enough for a full answer, e.g. `4096` |
| `grader` | `model` | string | The grader model (kept stable across the run) | A capable model that is **different from the proposer** |
| `grader` | `temperature` | number | **Must be `0`** — zero grading variance (S7) | Always `0` (the pre-flight errors otherwise) |
| `grader` | `version_id` | string | A pin id recorded for drift audit | A date or tag, e.g. `"2026-06-16"` |
| `proposer` | `model` | string | The model that proposes one change per turn | **Must differ from `grader.model`** (propose ≠ grade) |
| `proposer` | `temperature` | number | Low temperature for focused proposals | e.g. `0.3` |
| `bootstrapper` | `model` | string (optional) | Drafts candidate inputs during cold start | Only needed for cold start; if present, **must differ from `grader.model`** |
| `calibration` | `k_calib` | number | How many times the Runner is re-run to calibrate noise | **≥ 5** (a small k makes `eps` a noisy estimate → warning) |
| `loop` | `n_turns` | number | Maximum turns | Default `10`; raise for a bigger search (cost scales with it) |
| `loop` | `no_progress_k` | number | Stop after K turns with no `MERGE`/`SUB_KEEP` | Default `3` |
| `loop` | `subtraction_every` | number | Try a subtraction every Nth turn | Default `3` |
| `budget` | `max_usd_total` | number | Total spend cap (a first-class constraint) | Size it from `n_turns` × set size; the run stops when hit |
| `budget` | `max_usd_per_turn` | number | Per-turn spend cap | A guardrail against a single runaway turn |
| `tools` | `mode` | `"none"` \| `"mocked"` | `none` = text-in/text-out target (the v1 default) | Keep `"none"`; `"mocked"` is under-specified and a v2 concern |

---

## Pre-flight validation

Always run `validate_config.py` **before** turn 1; it STOPS the run on any error, so
a misconfigured actor can never quietly invalidate a whole run:

- **Errors (block the run):** a missing `runner`/`grader`/`proposer` block or
  `model` · `grader.temperature ≠ 0` · `proposer.model == grader.model` ·
  `bootstrapper.model == grader.model` (when a bootstrapper is present). Model ids
  are compared case- and whitespace-insensitively, so `"Sonnet"` vs `"sonnet"` can't
  sneak a self-grading run past the check.
- **Warnings (proceed with caution):** `runner.temperature == 0` (no variance →
  `eps` collapses to the floor) · `k_calib < 5` · missing `grader.version_id` ·
  missing `budget` block.

```bash
printf '%s' '{"config_path":"./run-config.json"}' | python3 loop-optimizer/scripts/validate_config.py
```

(Run scripts from the repository root, as shown — the path is relative to the project
root, not to this `docs/` page.)

---

## See also

- [`golden-set.md`](./golden-set.md) — the exam this config runs against; where most
  of the leverage lives.
- [`running.md`](./running.md) — the end-to-end run: validate → baseline → loop →
  batch commit/revert, plus cold start and resuming.
- [`../loop-optimizer/references/data-formats.md`](../loop-optimizer/references/data-formats.md)
  — the authoritative `run-config.json` schema, field by field.
- [`../loop-optimizer/references/safety-invariants.md`](../loop-optimizer/references/safety-invariants.md)
  — S1–S7, including S5 (actor separation) and S7 (noise from Runner variance, grader at temperature 0).
