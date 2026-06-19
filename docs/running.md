# Running the loop

> This is a Claude Code skill, so you **drive it in natural language** — you sit *on*
> the loop (designing the exam and the config), not *in* every iteration. You do not
> call the scripts by hand in normal use; the orchestrator does. Your one
> irreversible action is at the very end: **commit or revert** the staged result.

This page walks the run end to end — kickoff, what the skill does each turn, the
three real-world scenarios, how to resume an interrupted run, the cold-start path
when you have no golden set yet, and what a run costs. For the *exam* see
[`golden-set.md`](./golden-set.md); for the *config* see
[`run-config.md`](./run-config.md).

---

## Quick start

A typical kickoff is just a sentence:

> "Tune `./prompts/summarizer.md` so it scores better on the cases in
> `golden-set.json` (train and held-out are already marked), but **measure before you
> change anything** and only keep a change if it genuinely helps — don't overfit.
> Settings are in `run-config.json`."

The skill auto-triggers on requests to optimize / tune / harden / reduce the failure
rate of a prompt against examples, or to set up an eval- or golden-set-driven loop —
even if you never say the word "loop." It will:

1. Run the **pre-flight** config validation and verify the deterministic core.
2. Measure a **baseline** on train + held-out *before* proposing anything.
3. Run the gated loop, one change per turn, **staging only**.
4. Present a **batch** at the end — the diff (start vs candidate), `history.jsonl`
   (the score trail), and `failure-log.jsonl` (what was tried and discarded) — for
   you to **commit** (the first and only write to the live file) or **revert**.

**This loop is semi-autonomous: it does *not* ask you to approve every change.** You
sit *on* the loop (designing it), not *in* every iteration. The final end-to-end QA —
actually *using* the result — stays with you; a passing golden-set score is
necessary, not sufficient.

### Verify the deterministic core

Before trusting any run, verify the code that makes every irreversible decision:

```bash
python3 loop-optimizer/scripts/tests/run.py          # 197 tests, stdlib only
# or:  python3 -m pytest loop-optimizer/scripts/tests/
```

Every script reads its JSON payload on **stdin** (or a file-path arg) — never as an
inline argv string:

```bash
printf '%s' '<json>' | python3 loop-optimizer/scripts/score_compare.py
```

(Run scripts from the repository root — the paths are relative to the project root,
not to this `docs/` page.)

---

## Usage by scenario

The three scenario types below mirror the skill's own end-to-end evals in
[`../loop-optimizer/evals/evals.json`](../loop-optimizer/evals/evals.json).

### Scenario 1 — Warm start (you already have a golden set)

**You have:** a target file + a `golden-set.json` with `train`/`heldout` already
marked.

> "Tune `./prompts/summarizer.md` so it scores better on the cases in
> `golden-set.json` — but **measure before you change anything**, and only keep a
> change if it genuinely helps. Don't overfit. Settings are in `run-config.json`."

**What happens:** validate config → measure a baseline on train + held-out → run the
gated loop (one change per turn, staging only) → merge only changes that beat noise
and survive the confirm re-run → present a diff + `history.jsonl` + `failure-log.jsonl`
for you to **commit or revert**. The live file stays untouched until you commit.

### Scenario 2 — Cold start (no golden set yet)

**You have:** a target + maybe a dump of raw logs, but **no labeled test set**.

> "`classify.md` is my support-ticket classifier and it keeps mislabeling things.
> Make it better. I don't have a test set — there's just a dump of raw inbox lines in
> `seed-logs.txt`. Settings are in `run-config.json`."

**What happens:** the skill detects there is no golden set (it does **not** invent one
and self-grade) → the **Bootstrapper** drafts candidate *inputs* → the target runs
once to expose real failures → the loop **STOPS at the human gate** and asks you to
curate the inputs and write the yes/no rubric, reminding you of the size gate
(`train ≥ 5`, `heldout ≥ 3`). Only after you curate does the optimization loop run.
The full path is detailed under [Cold start](#cold-start-no-golden-set-yet) below.

### Scenario 3 — Overfit guard (a tempting change that breaks generalization)

**You have:** a target + golden set, and an obvious "just always do X" fix in mind.

> "Tune my job-posting field extractor `extract.md` against `golden-set.json`. The big
> problem: it leaves `salary_range` null too often — I want it filled in. Settings are
> in `run-config.json`."

**What happens:** the natural "always fill salary" change raises **train** but breaks
**held-out** (postings that state no salary), so the code returns **HALT** — the
change never reaches the target. The halted attempt plus a `candidate_input` (a case
for the next golden-set version) are logged. You are protected from silently teaching
the prompt to hallucinate.

---

## Resuming an interrupted run

Every run is resumable. If one is interrupted, `state.json` records the turn and
phase, and `resume.py` re-enters **idempotently** from the last completed step — a
merge is never double-applied.

> "Resume the loop-optimizer run for `summarizer.md` where it left off."

A sample `state.json` (alongside `history.jsonl` and `failure-log.jsonl`) ships at
[`../examples/en/loop-state/`](../examples/en/loop-state) so you can see exactly what
the resumable state machine records.

---

## Cold start: no golden set yet

If there is no golden set, the loop does **not** invent one and grade against it —
that would be a self-graded exam. The state is detected *deterministically*
(`split_goldenset.py op=state` returns `missing`/`empty`), then:

1. **Seed** inputs from logs if they exist, and/or have the **Bootstrapper** draft
   input *candidates*. Run the Bootstrapper even when logs exist if the logs are
   easy / happy-path — a flattering set finds nothing.
2. **Expose failure**: run the target once (Runner) on the candidates to surface
   where it actually fails.
3. **Human curates**: *you* approve/prune inputs and add missing hard cases. You own
   input selection, not just the rubric — this blocks correlated blind spots.
4. **Human rubric**: *you* write the yes/no criteria (5–7 per input).
5. **Split**: `split_goldenset.py` splits train/held-out *after* curation, placing
   the **most realistic** items in held-out, and freezes the split (hash).
6. **Size gate**: it refuses / warns hard below `train < 5` or `heldout < 3`.

The loop stops at the human-curation gate and asks you to approve inputs and write the
rubric — it will not silently finalize a set and optimize against it. The craft of
*what* to curate into that set is its own page: see
[`golden-set.md`](./golden-set.md), and
[`../loop-optimizer/agents/bootstrapper.md`](../loop-optimizer/agents/bootstrapper.md)
for what the Bootstrapper does and doesn't do.

---

## What a run costs

A turn costs roughly:

```
Runner (current + candidate-verify + confirm) × set size
  + Grader (same) + Proposer (1)
  ≈ ~65 model calls on a PROMOTE turn for |train| = 5, |held| = 3
    (confirm re-runs BOTH the candidate and the current/baseline prompt — the H4 re-measure)
  ≈ ~33 on a non-promote turn (DISCARD/HALT skip confirm)
  + k_calib calibration runs (once, at cold start)
```

Budget is a **first-class constraint**: set `budget.max_usd_total` and
`budget.max_usd_per_turn` in `run-config.json`. You size total cost via `n_turns` and
the golden-set size; the loop tracks `budget_spent_usd` in `state.json` and stops when
a cap is hit.

---

## See also

- [`golden-set.md`](./golden-set.md) — building the exam the loop grades against
  (the highest-leverage thing you own).
- [`run-config.md`](./run-config.md) — every `run-config.json` field, and the
  pre-flight that enforces honest measurement.
- [`../loop-optimizer/references/safety-invariants.md`](../loop-optimizer/references/safety-invariants.md)
  — S1–S7: why the merge gate, the held-out HALT, and staging exist.
- [`../loop-optimizer/references/loop-concepts.md`](../loop-optimizer/references/loop-concepts.md)
  — the principles behind every design choice.
