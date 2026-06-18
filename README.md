# Loop Optimizer

> **Iteratively improve a prompt, skill, or instruction file with a *measured* self-improvement loop — never on vibes.**

*Read this in another language: [한국어](./README.ko.md)*

`loop-optimizer` is a [Claude Code](https://docs.claude.com/en/docs/claude-code) skill (it lives in [`loop-optimizer/`](./loop-optimizer)) that tunes a target prompt/skill/instruction file the way a good coach trains an athlete:

> **measure → change ONE thing → measure again → keep it only if the score really went up.**

Its governing rule is **"no evolution without measurement."** You never change the target on a hunch — you change it on a score, and you let *deterministic code* (not a model's opinion) decide whether the change survives. A `MERGE` here is not "the model thought it looked better." It is a single, isolated, code-verified change that **beat measured noise on training cases, held generalization on held-out cases, survived a confirming re-run, and never touched your live file until you said so.**

---

## Table of contents

- [Why this exists](#why-this-exists)
- [What makes it different](#what-makes-it-different)
- [How it works](#how-it-works)
  - [The four actors](#the-four-actors)
  - [One turn of the loop](#one-turn-of-the-loop)
  - [The merge gate (the heart)](#the-merge-gate-the-heart)
  - [Subtraction turns](#subtraction-turns)
  - [Stop conditions](#stop-conditions)
- [The seven safety invariants (S1–S7)](#the-seven-safety-invariants-s1s7)
- [Inputs you provide](#inputs-you-provide)
  - [Golden set fields](#golden-set-fields)
  - [Run config fields](#run-config-fields)
- [Cold start: no golden set yet](#cold-start-no-golden-set-yet)
- [Quick start](#quick-start)
- [Usage examples by scenario](#usage-examples-by-scenario)
- [Repository layout](#repository-layout)
- [Bundled scripts](#bundled-scripts)
- [Cost](#cost)
- [Requirements](#requirements)
- [Further reading](#further-reading)

---

## Why this exists

"Self-improvement" sounds great, but it is a trap the moment it goes unmeasured. A model edits a prompt, declares it better, and the prompt slowly drifts on vibes — sometimes worse, with nobody able to tell. Three specific ways that drift hides real failure:

1. **Noise mistaken for progress.** At a realistic temperature, the target's output wobbles between runs. A "+1 on training" can be pure luck. Merge inside that noise band and you ratchet randomness into the prompt — the score creeps up while the prompt gets *worse*.
2. **Overfitting.** A change can memorize the quirks of the cases you optimized against and quietly destroy generalization — the classic "98% on train, broken in production" trap.
3. **The self-graded exam.** Ask a model "did your change help?" and, having just produced it, it is primed to say yes. A player must not referee their own game.

`loop-optimizer` is built to remove each of these failure modes mechanically, so that "better" is an **observed quantity** rather than an opinion.

---

## What makes it different

| Most "AI improves a prompt" tools | `loop-optimizer` |
|---|---|
| The model decides if a change helped | **Deterministic code** decides every merge — a fixed inequality, not a judgment |
| One score, optimize against it | **Train + held-out split**; held-out is the generalization guard, and overfitting triggers a **HALT** |
| A "+1" is accepted | A gain must **beat calibrated measurement noise** *and* survive a confirming re-run |
| The same model proposes and grades | **Four isolated actors** — proposer ≠ grader ≠ runner ≠ bootstrapper |
| Edits the live file directly | **Staging only**; your live file is byte-for-byte untouched until *you* commit |
| Rules only ever accrete | **Subtraction turns** prune dead rules every 3rd turn |
| Repeats the same losing ideas | A **failure log** is read back by the proposer to avoid known dead ends |

---

## How it works

### The four actors

The single most important structural rule: **the model that proposes a change is not the model that grades it, and neither is the model that runs the target.** Each actor is a separate Claude Code subagent with its own prompt under [`loop-optimizer/agents/`](./loop-optimizer/agents), so each starts from a clean context and the separation is *real*, not nominal.

| Actor | Job | Notes |
|---|---|---|
| **Runner** | Execute the target on a golden input → produce an output | Isolated: no write / network / shell. Reads the golden input only. This isolation is also a **security boundary** — an arbitrary target prompt must not hijack the host. Runs at your real production model + temperature so measured noise is real. |
| **Grader** | Score an output against the rubric → per-item yes/no | **Temperature 0**, version-pinned → contributes zero variance. |
| **Proposer** | Propose exactly **one** change | Reads `failure-log.jsonl` first to avoid repeating dead ends. |
| **Bootstrapper** | Draft cold-start input *candidates* | Must be a different model from the Grader. |

### One turn of the loop

The loop runs up to **N** turns (default 10). Each turn changes **at most one thing** and is gated by code:

```
① Run      Runner(current target, ALL train+heldout inputs) → outputs
② Grade    Grader(outputs, rubric) → train_before, heldout_before
③ Propose  Proposer → one change {target_id, before, after, rationale, kind}
④ Verify   verify_change.py: `before` matches UNIQUELY + change is local
           → reject the turn if not  (enforces "exactly one localized change")
⑤ Apply    apply_change.py: write to STAGING (prompt.candidate.md) only —
           the live target is untouched
⑥ Re-run   Runner(candidate, ALL inputs) → outputs
⑦ Re-grade Grader → train_after, heldout_after
⑧ Compare  score_compare.py (CODE decides): MERGE / DISCARD / HALT
⑨ Confirm  if MERGE: re-run + re-grade the full set ONCE more; the gain must hold
⑩ Record   MERGE  → promote candidate to current + append history.jsonl
           DISCARD→ failure-log.jsonl (+ candidate_input); keep the live file
           HALT   → stop + warn + failure-log.jsonl (result: halted)
```

**Why confirm by re-running, not just re-grading (⑨)?** The Grader runs at temperature 0, so re-grading the *same text* returns the identical score — a no-op. Real noise comes from the **Runner** producing different outputs across runs. So a merge is confirmed by *running the target again* and re-grading the fresh output. If the gain evaporates, it was noise.

### The merge gate (the heart)

[`score_compare.py`](./loop-optimizer/scripts/score_compare.py) — not a model — makes the decision. A change **MERGES only when all of these hold:**

```
train_after   >  train_before                      (a strictly positive gain — a +0.0 tie never merges)
train_after   ≥  train_before   + eps_train        (the gain beats measurement noise on train)
heldout_after ≥  heldout_before − eps_heldout       (no real regression on held-out)
AND the gain still holds after the confirm re-run (⑨)
```

Otherwise:

- If `train` rises but `heldout` falls by **more than** `eps_heldout` → **HALT** (overfitting: the change memorized train and broke generalization). HALT is terminal.
- Otherwise → **DISCARD** (no real gain; the addition is reverted).

The margins `eps_train` / `eps_heldout` are **measurement noise**, calibrated by [`calibrate_noise.py`](./loop-optimizer/scripts/calibrate_noise.py): it re-runs the Runner on fixed inputs `k_calib` times (≥5 recommended), grades each, and derives the score spread per split — floored at a small positive `min_eps` so a `+0.0` tie can never look like progress. The held-out margin is **symmetric** (`eps_heldout` on both the merge and HALT side), so ordinary held-out noise does not trigger false HALTs.

**Check the gate is satisfiable first.** Pass the baseline scores to `calibrate_noise.py`. If it returns `gate_satisfiable: false` — i.e. `eps_train ≥ 1 − baseline_train`, so *no* change could ever clear the gate (this also covers the saturated case where the baseline is already ≈1.0) — the loop **STOPS and surfaces the warning** instead of burning N turns. The fix is a bigger / harder golden set or a higher `k_calib`, not more proposing.

### Subtraction turns

Left to instinct, anyone improving a prompt only ever **adds** rules — the text accretes caveats until it is bloated and self-contradictory. So **every 3rd turn**, the loop inverts the question from "what to add?" to **"what to remove?"**: it drops one suspected-dead rule and re-measures.

- Keep the removal iff `train_after ≥ train_before − eps_train` **AND** `heldout_after ≥ heldout_before − eps_heldout` → record `SUB_KEEP` (the prompt got simpler at no cost) and reset the no-progress counter.
- Otherwise restore the rule, record `SUB_DROP`, and increment the counter.

(`SUB_DROP` undoes a *removal*; `DISCARD` undoes an *addition* — they are distinct.)

### Stop conditions

The loop stops at the first of: **N turns reached** · **no progress for K turns** (default 3; reset on `MERGE`/`SUB_KEEP`) · **budget exceeded** (per-turn or total) · **perfect score** · **HALT**.

A plateau below your hoped-for score is **information, not failure**: it means the instruction text has reached the ceiling of what the fixed model and tools allow. To go further, change the model or add a tool — not the words. The loop reports the plateau honestly rather than thrashing.

---

## The seven safety invariants (S1–S7)

These are the reason the skill exists. Each removes one specific way "self-improvement" silently degrades into evolution-without-measurement. Full statements: [`references/safety-invariants.md`](./loop-optimizer/references/safety-invariants.md).

| # | Invariant | Prevents | Enforced by |
|---|---|---|---|
| **S1** | Held-out split + **HALT** on overfitting (symmetric `eps_heldout` margin) | Overfit changes merging | `split_goldenset.py`, `score_compare.py` |
| **S2** | **Code-enforced merge** — never a model's "it's better" (plus a strict `>` gain) | Wishful self-assessment | `score_compare.py` |
| **S3** | **Mechanical single change** — unique `before` + locality caps | Ambiguous / confounded edits | `verify_change.py` (re-checked by `apply_change.py`) |
| **S4** | **Staging** — the live file is untouched until the human commits | Silent corruption of your real prompt | `apply_change.py` |
| **S5** | **Human-owned sourcing** + minimum-size gate (`train ≥ 5`, `heldout ≥ 3`) | A self-graded / too-small exam | Bootstrapper ≠ Grader, human curation, `split_goldenset.py` |
| **S6** | **Failure-log feedback** + proposer read-back | Repeated dead ends; a stale golden set | `failure-log.jsonl`, `agents/proposer.md` |
| **S7** | **Noise margin from Runner variance** + confirm re-run/re-grade | Noise mistaken for progress | `calibrate_noise.py`, the confirm step |

Remove any one and the loop can climb a meaningless score. Keep all seven and a `MERGE` *means* something.

---

## Inputs you provide

All work happens inside a `loop/<target>/` working directory, and you provide three things. Each is documented property-by-property below; the authoritative schemas live in [`references/data-formats.md`](./loop-optimizer/references/data-formats.md).

1. **Target** — the live prompt/skill/instruction file to improve, e.g. `./agents/dev-agent.md`. **Never written until you commit at the end.**
2. **Golden set** (`golden-set.json`) — **you own this.** The fixed exam the loop grades against; most of the leverage lives here. If you don't have one, the loop builds it *with* you (see [Cold start](#cold-start-no-golden-set-yet)) — it never invents one and grades against it.
3. **Run config** (`run-config.json`) — how the target is run "like real use," plus the loop and budget controls.

> **Golden set: frozen *within* a run, versioned *between* runs.** While the loop runs, the set and split are frozen (a `split_hash` is re-checked every turn; any mid-run change is an error) — this is what makes before/after scores comparable. Between runs, *you* grow the set, folding in failure-derived cases (via `candidate_input` from the failure log) as a new `version`. Scores are comparable **only within a version**, so every `history.jsonl` row records its `golden_set_version`.

### Golden set fields

The golden set (`golden-set.json`) is the fixed exam — **you curate the inputs and author the rubric** (S5). It has dataset-level **header fields** plus a list of **`cases[]`**. Here is a complete sample (the same one ships at `examples/en/golden-set/golden-set.example.json` for copy-paste):

```json
{
  "_note": "Abbreviated example for illustrating the format. A real golden set must satisfy min_size (active train >= 5 * heldout >= 3). Fields prefixed with '_' are ignored by the parser.",
  "target": "./agents/dev-agent.md",
  "version": "v2",
  "parent_version": "v1",
  "created": "2026-06-10",
  "updated": "2026-06-16",
  "changelog": "After v1 saturated, added a real-world 'missed concurrency bug' failure to train (from the failure log). Retired the non-discriminating 'print-hello'.",
  "min_size": { "train": 5, "heldout": 3 },
  "cases": [
    {
      "id": "regex-email-fix",
      "split": "train",
      "provenance": "seed",
      "added_in_version": "v1",
      "realistic": true,
      "status": "active",
      "tags": ["regex", "debugging"],
      "notes": "A regex-debugging request that came up often in real logs. Short input, so used inline.",
      "input": "This regex doesn't match emails correctly: ^\\w+@\\w+$ - what's wrong and how do I fix it?",
      "rubric": [
        "Did it point out that it fails to handle the TLD (e.g. .com) and the dot (.)?",
        "Did it provide a working improved regex?",
        "Did it avoid inventing a fake problem not present in the input?"
      ]
    },
    {
      "id": "debug-race-condition",
      "split": "train",
      "provenance": "failure-log",
      "added_in_version": "v2",
      "realistic": true,
      "status": "active",
      "tags": ["debugging", "concurrency"],
      "notes": "Derived from a real failure where the v1 agent missed a negative-balance bug. A representative case of evolution (S6 feedback). Code input, so uses input_file.",
      "input_file": "./cases/debug-race-condition.input.txt",
      "rubric": [
        "Did it name the race condition (check-then-act) as the real cause?",
        "Did it fix it correctly with a lock or an atomic operation?",
        "Did it avoid inventing a cause not present in the code?",
        "Did it keep the existing withdraw signature intact?",
        "Did it explain in a line or two why that is the cause?"
      ]
    },
    {
      "id": "review-sql-injection",
      "split": "heldout",
      "provenance": "human",
      "added_in_version": "v1",
      "realistic": true,
      "status": "active",
      "tags": ["code-review", "security"],
      "notes": "A real-world case taken from an actual PR -> placed in held-out first per the reality-first rule.",
      "input_file": "./cases/review-sql-injection.input.txt",
      "rubric": [
        "Did it point out the SQL injection vulnerability?",
        "Did it propose a parameter-binding (prepared statement) fix?",
        "Did it rate the severity appropriately (high)?",
        "Did it avoid fabricating a non-existent problem?",
        "Did it show a fix example that actually works?"
      ]
    },
    {
      "id": "print-hello",
      "split": "train",
      "provenance": "bootstrap",
      "added_in_version": "v1",
      "realistic": false,
      "status": "retired",
      "tags": ["trivial"],
      "notes": "Every version passes -> zero discrimination. Retired in v2 (excluded from scoring, kept for the record). A golden-set-level 'subtraction' example.",
      "input": "Print 'hello' in Python.",
      "rubric": ["Did it provide code that prints hello?"]
    }
  ]
}
```

**What the sample shows.** It is deliberately *abbreviated* — the `_note` flags that a real set must meet `min_size`, whereas this one has only 2 active `train` + 1 `heldout` cases (below the `train ≥ 5` / `heldout ≥ 3` gate, so a real run would warn). Reading it top to bottom:

- **Header block.** `version: "v2"` evolved from `parent_version: "v1"`, and `changelog` records *why* v2 exists: a real concurrency-bug miss was folded in from the failure log and a non-discriminating case was retired. `min_size` is the size gate (S5).
- **`regex-email-fix`** — a `train` case with a short **inline `input`** and `provenance: "seed"` (it came from real logs). Three yes/no rubric criteria define a good answer.
- **`debug-race-condition`** — a `train` case whose code lives in a file via **`input_file`**, with `provenance: "failure-log"`: it was *derived from a real miss* (the evolution bridge, S6). Notice the rubric also checks that the model does **not** invent a cause — a hallucination guard.
- **`review-sql-injection`** — the **held-out** case. `realistic: true` is exactly why it sits in held-out (reality-first): it is the generalization guard the loop never optimizes against.
- **`print-hello`** — `status: "retired"`: every version passed it, so it lost discriminative power; it is excluded from scoring but kept for the record (a golden-set-level "subtraction").

Every `rubric` is 5–7 plain yes/no criteria — the *criteria* for a good answer, not the answer itself — and scores aggregate per split over **active** cases only. The full field-by-field reference follows.

**Header (dataset-level) fields:**

| Property | Type | Required | What it means | How to set it |
|---|---|---|---|---|
| `target` | string | ✔ | Relative path to the live target file being improved | Point it at your real prompt/skill file, e.g. `./agents/dev-agent.md` |
| `version` | string | ✔ | Golden-set version id; scores compare **only within** one version | Start at `"v1"`; bump (`"v2"`, …) each time you grow the set between runs |
| `parent_version` | string \| null | ✔ | The version this evolved from (lineage) | `null` for the first version; otherwise the previous id |
| `created` | date | recommended | When the set was first created | An ISO date, e.g. `"2026-06-10"` |
| `updated` | date | recommended | When it was last edited | The ISO date of the latest change |
| `changelog` | string | recommended | What changed vs the parent version | One line: which failure-derived case you added, what you retired |
| `min_size` | object `{train, heldout}` | ✔ | Minimum **active** cases per split — the size gate (S5) | Keep `{ "train": 5, "heldout": 3 }` unless you deliberately raise it |

**Case fields (each entry in `cases[]`):**

| Property | Type | Required | What it means | How to set it |
|---|---|---|---|---|
| `id` | string | ✔ | Stable identifier, tracked across versions | A short slug, e.g. `"debug-race-condition"`; never reuse it for a different case |
| `split` | `"train"` \| `"heldout"` | ✔ | Which split it belongs to; **frozen during a run** | Let `split_goldenset.py` assign it, or set by hand — put your most realistic cases in `heldout` |
| `input` **or** `input_file` | string | ✔ (exactly one) | The test input: inline text **or** a path to a file | Short text → `input`; code/large input → `input_file: "./cases/<id>.input.txt"` |
| `rubric` | string[] | ✔ | **5–7** yes/no criteria that define a good answer | Plain yes/no questions; this is the *criteria*, not the answer itself |
| `provenance` | `"seed"` \| `"bootstrap"` \| `"failure-log"` \| `"human"` | ✔ | Where the case came from (evolution tracking) | `seed` = from logs · `bootstrap` = AI-drafted candidate · `failure-log` = from a past miss · `human` = you wrote it |
| `added_in_version` | string | ✔ | The version in which the case entered | The `version` it first appeared in |
| `realistic` | boolean | ✔ | Is this a real, production-like case? | `true` for real cases (placed in held-out first); `false` for toy/synthetic ones |
| `status` | `"active"` \| `"retired"` | ✔ | `retired` is excluded from scoring but kept for the record | `active` normally; **retire** (don't delete) a case that no longer discriminates |
| `notes` | string | recommended | What capability or failure this case targets | A sentence on why the case exists |
| `tags` | string[] | optional | Free classification labels | e.g. `["debugging", "concurrency"]` |

**Rules you must respect when setting these:**

- **Scoring.** Per case, score = `(rubric criteria passed) / (criteria total)`, aggregated **per split over active cases only**. Retired cases are excluded but preserved for history.
- **`input` vs `input_file`.** Provide **exactly one**. `input_file` is a path **relative to the directory containing `golden-set.json`** — the convention is a `./cases/` subfolder.
- **Reality-first held-out.** Put your hardest, most production-like cases in `heldout` (`realistic: true`). Held-out is the generalization guard the loop never optimizes against.
- **Size gate (S5).** A run refuses / warns hard below `train ≥ 5` and `heldout ≥ 3` active cases.

### Run config fields

The run config (`run-config.json`) tells the **Runner** how to execute the target "like real use" and controls the loop. Here is a minimal config (the same one ships at `examples/en/run-config.example.json` for copy-paste):

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

**What the sample sets.** Reading it block by block:

- **`_note`** is a human comment the parser ignores (any field whose name starts with `_`) — use it to annotate the file.
- **Top level.** `target` and `golden_set` point at the live file and its exam — both relative paths.
- **`runner`** uses `claude-opus-4-8` at **temperature 0.7** — the *same model and temperature you run in production*, so the noise the loop calibrates is your real noise (not an artificially quiet `temperature: 0`).
- **`grader`** uses a *different* model (`claude-sonnet-4-6`) at **temperature 0** with a pinned `version_id` — a stable, zero-variance ruler. Using a different model is what keeps grading honest (propose ≠ grade).
- **`proposer`** uses `claude-opus-4-8` at a low **0.3** for focused, single edits. It happens to share the runner's model, which is fine — the only hard separation rule is proposer ≠ grader (and bootstrapper ≠ grader).
- **`calibration.k_calib: 5`** re-runs the Runner 5× to measure `eps`; 5 is the recommended floor.
- **`loop`** caps the run at 10 turns, stops after 3 no-progress turns, and tries a subtraction every 3rd turn.
- **`budget`** caps total spend at `$20` and per-turn spend at `$3` — the run halts when either is hit.
- **`tools.mode: "none"`** = a plain text-in/text-out target (the v1 default).

There is no `bootstrapper` block here because this is a warm start; add one — with a model different from the grader — only for cold start. The full field-by-field reference follows.

**Field reference (every block):**

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

**Pre-flight validation.** Always run `validate_config.py` *before* turn 1; it STOPS the run on any error:

- **Errors (block the run):** a missing `runner`/`grader`/`proposer` block or `model` · `grader.temperature ≠ 0` · `proposer.model == grader.model` · `bootstrapper.model == grader.model` (when a bootstrapper is present). Model ids are compared case- and whitespace-insensitively, so `"Sonnet"` vs `"sonnet"` can't sneak a self-grading run past the check.
- **Warnings (proceed with caution):** `runner.temperature == 0` (no variance → `eps` collapses to the floor) · `k_calib < 5` · missing `grader.version_id` · missing `budget` block.

```bash
printf '%s' '{"config_path":"./run-config.json"}' | python3 loop-optimizer/scripts/validate_config.py
```

---

## Cold start: no golden set yet

If there is no golden set, the loop does **not** invent one and grade against it — that would be a self-graded exam. The state is detected *deterministically* (`split_goldenset.py op=state` returns `missing`/`empty`), then:

1. **Seed** inputs from logs if they exist, and/or have the **Bootstrapper** draft input *candidates*. Run the Bootstrapper even when logs exist if the logs are easy / happy-path — a flattering set finds nothing.
2. **Expose failure**: run the target once (Runner) on the candidates to surface where it actually fails.
3. **Human curates**: *you* approve/prune inputs and add missing hard cases. You own input selection, not just the rubric — this blocks correlated blind spots.
4. **Human rubric**: *you* write the yes/no criteria (5–7 per input).
5. **Split**: `split_goldenset.py` splits train/held-out *after* curation, placing the **most realistic** items in held-out, and freezes the split (hash).
6. **Size gate**: it refuses / warns hard below `train < 5` or `heldout < 3`.

The loop stops at the human-curation gate and asks you to approve inputs and write the rubric — it will not silently finalize a set and optimize against it.

---

## Quick start

This is a Claude Code skill, so you drive it in natural language — you do not call the scripts by hand in normal use; the orchestrator does. A typical kickoff:

> "Tune `./prompts/summarizer.md` so it scores better on the cases in `golden-set.json` (train and held-out are already marked), but **measure before you change anything** and only keep a change if it genuinely helps — don't overfit. Settings are in `run-config.json`."

The skill auto-triggers on requests to optimize / tune / harden / reduce the failure rate of a prompt against examples, or to set up an eval- or golden-set-driven loop — even if you never say the word "loop." It will:

1. Run the **pre-flight** config validation and verify the deterministic core.
2. Measure a **baseline** on train + held-out *before* proposing anything.
3. Run the gated loop, one change per turn, staging only.
4. Present a **batch** at the end — the diff (start vs candidate), `history.jsonl` (score trail), and `failure-log.jsonl` (what was tried and discarded) — for you to **commit** (the first and only write to the live file) or **revert**.

**This loop is semi-autonomous: it does *not* ask you to approve every change.** You sit *on* the loop (designing it), not *in* every iteration. The final end-to-end QA — actually *using* the result — stays with you; a passing golden-set score is necessary, not sufficient.

### Verify the deterministic core

Before trusting any run, verify the code that makes every irreversible decision:

```bash
python3 loop-optimizer/scripts/tests/run.py          # 145 tests, stdlib only
# or:  python3 -m pytest loop-optimizer/scripts/tests/
```

Every script reads its JSON payload on **stdin** (or a file-path arg) — never as an inline argv string:

```bash
printf '%s' '<json>' | python3 loop-optimizer/scripts/score_compare.py
```

---

## Usage examples by scenario

You drive the skill in natural language; it auto-triggers on requests to optimize, tune, harden, or reduce the failure rate of a prompt against examples — even if you never say the word "loop." The three scenario types below mirror the skill's own end-to-end evals in [`evals/evals.json`](./loop-optimizer/evals/evals.json).

### Scenario 1 — Warm start (you already have a golden set)

**You have:** a target file + a `golden-set.json` with `train`/`heldout` already marked.

> "Tune `./prompts/summarizer.md` so it scores better on the cases in `golden-set.json` — but **measure before you change anything**, and only keep a change if it genuinely helps. Don't overfit. Settings are in `run-config.json`."

**What happens:** validate config → measure a baseline on train + held-out → run the gated loop (one change per turn, staging only) → merge only changes that beat noise and survive the confirm re-run → present a diff + `history.jsonl` + `failure-log.jsonl` for you to **commit or revert**. The live file stays untouched until you commit.

### Scenario 2 — Cold start (no golden set yet)

**You have:** a target + maybe a dump of raw logs, but **no labeled test set**.

> "`classify.md` is my support-ticket classifier and it keeps mislabeling things. Make it better. I don't have a test set — there's just a dump of raw inbox lines in `seed-logs.txt`. Settings are in `run-config.json`."

**What happens:** the skill detects there is no golden set (it does **not** invent one and self-grade) → the **Bootstrapper** drafts candidate *inputs* → the target runs once to expose real failures → the loop **STOPS at the human gate** and asks you to curate the inputs and write the yes/no rubric, reminding you of the size gate (`train ≥ 5`, `heldout ≥ 3`). Only after you curate does the optimization loop run.

### Scenario 3 — Overfit guard (a tempting change that breaks generalization)

**You have:** a target + golden set, and an obvious "just always do X" fix in mind.

> "Tune my job-posting field extractor `extract.md` against `golden-set.json`. The big problem: it leaves `salary_range` null too often — I want it filled in. Settings are in `run-config.json`."

**What happens:** the natural "always fill salary" change raises **train** but breaks **held-out** (postings that state no salary), so the code returns **HALT** — the change never reaches the target. The halted attempt plus a `candidate_input` (a case for the next golden-set version) are logged. You are protected from silently teaching the prompt to hallucinate.

### Resuming an interrupted run

Every run is resumable. If one is interrupted, `state.json` records the turn and phase, and `resume.py` re-enters idempotently from the last completed step — a merge is never double-applied.

> "Resume the loop-optimizer run for `summarizer.md` where it left off."

---

## Repository layout

The README lives at the project root; the skill itself is in `loop-optimizer/`, with copy-paste-ready inputs in `examples/`.

```
.
├── README.md                          # This file (English)
├── README.ko.md                       # Korean version
├── examples/                          # Copy-paste-ready example inputs & state
│   ├── run-config.example.json        #   run config (Korean-annotated)
│   ├── golden-set/                    #   golden set + cases/ (Korean-annotated)
│   ├── loop-state/                    #   sample history / failure-log / state
│   └── en/                            #   English mirror of everything above
│       ├── run-config.example.json
│       ├── golden-set/
│       └── loop-state/
└── loop-optimizer/                    # The skill
    ├── SKILL.md                       #   the skill contract Claude Code loads (start here)
    ├── agents/                        #   the four isolated actors (one prompt each)
    │   ├── runner.md                  #     executes the target (sandboxed)
    │   ├── grader.md                  #     scores outputs vs rubric (temp 0)
    │   ├── proposer.md                #     proposes one change; reads failure log
    │   └── bootstrapper.md            #     drafts cold-start input candidates
    ├── scripts/                       #   deterministic core — stdlib only, decides every merge
    │   ├── validate_config.py         #     pre-flight: actor separation, grader temp 0
    │   ├── verify_change.py           #     ④ one localized change (unique before + locality)
    │   ├── apply_change.py            #     ⑤/⑩ write to staging, promote on merge
    │   ├── score_compare.py           #     ⑧ MERGE / DISCARD / HALT decision
    │   ├── calibrate_noise.py         #     eps_train / eps_heldout + gate_satisfiable
    │   ├── split_goldenset.py         #     classify state + split & freeze the set
    │   ├── resume.py                  #     idempotent resume after interruption
    │   ├── _common.py                 #     shared helpers (stdin payload, hashing)
    │   └── tests/                     #     145 tests over the core (run.py)
    ├── references/                    #   the "why" and the exact contracts
    │   ├── loop-concepts.md           #     principles behind every design choice
    │   ├── safety-invariants.md       #     S1–S7 in full
    │   └── data-formats.md            #     complete JSON/JSONL schemas (authoritative)
    ├── evals/
    │   └── evals.json                 #   Level-2 evals: does the SKILL itself behave?
    └── assets/
        └── loop-state/                #   template/working-state files for a run
```

The per-run working state lives in `loop/<target>/` and is fully human-readable and resumable: `golden-set.json`, `prompt.current.md` / `prompt.candidate.md` (staging — never the live file), `history.jsonl` (per-turn score trail), `failure-log.jsonl` (discarded/halted attempts + evolution candidates), and `state.json` (turn state machine for idempotent resume).

---

## Bundled scripts

Code makes every irreversible decision; the model only generates and grades. All scripts are under [`loop-optimizer/scripts/`](./loop-optimizer/scripts).

| Step | Script | Role |
|---|---|---|
| pre-flight | `validate_config.py` | Validate run-config: actor separation, grader temp 0 |
| ④ | `verify_change.py` | Verify exactly one localized change (unique `before` + locality caps) |
| ⑤ / ⑩ | `apply_change.py` | Apply to staging; promote candidate → current on merge (re-runs the verify gate) |
| ⑧ | `score_compare.py` | The merge gate: MERGE / DISCARD / HALT from a fixed inequality |
| calibration | `calibrate_noise.py` | Derive `eps_train` / `eps_heldout`; report `gate_satisfiable` |
| cold start / split | `split_goldenset.py` | Classify golden-set state (`op=state`); split & freeze (`op=split`) |
| resume | `resume.py` | Idempotent resume from the last completed phase |

---

## Cost

A turn costs roughly:

```
Runner (current + candidate-verify + confirm) × set size
  + Grader (same) + Proposer (1)
  ≈ ~49 model calls for |train| = 5, |held| = 3
  + k_calib calibration runs (once, at cold start)
```

Budget is a **first-class constraint**: set `budget.max_usd_total` and `budget.max_usd_per_turn` in `run-config.json`. You size total cost via `n_turns` and the golden-set size; the loop tracks `budget_spent_usd` in `state.json` and stops when a cap is hit.

---

## Requirements

- **Python ≥ 3.8** for `loop-optimizer/scripts/` — **standard library only**, no third-party packages.
- **Claude Code** (subagents) — to keep the four actors genuinely isolated, each running from a clean context.

---

## Further reading

- [`loop-optimizer/SKILL.md`](./loop-optimizer/SKILL.md) — the full skill contract (what Claude Code loads).
- [`references/loop-concepts.md`](./loop-optimizer/references/loop-concepts.md) — the principles behind the loop (why measure first, why one change, why proposer ≠ grader, the failure log, subtraction, the human as coach, the model/tools ceiling).
- [`references/safety-invariants.md`](./loop-optimizer/references/safety-invariants.md) — S1–S7 in full, each with the failure it prevents and the mechanism that enforces it.
- [`references/data-formats.md`](./loop-optimizer/references/data-formats.md) — the authoritative JSON/JSONL schemas for every file and contract.
- [`evals/evals.json`](./loop-optimizer/evals/evals.json) — end-to-end behavioral evals for the skill itself (warm-start merge, cold-start human gate, overfit HALT).
