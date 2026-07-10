# Running the loop

> agent-coach is a Claude Code skill, so you **drive it in plain language**. You
> sit *on* the loop — designing the exam and the config — not *in* it, approving
> every iteration. In normal use you never call the scripts by hand; the skill's
> orchestrator does. Your one irreversible action comes at the very end:
> **commit or revert** the staged result.

This page walks a run end to end: the kickoff, what the skill does, three
real-world scenarios, resuming an interrupted run, the cold-start path when you
have no golden set yet, and what a run costs. For the *exam*, see
[`golden-set.md`](./golden-set.md); for the *config*, see
[`run-config.md`](./run-config.md).

---

## Quick start

A typical kickoff is one sentence:

> "Tune `./prompts/summarizer.md` so it scores better on the cases in
> `golden-set.json` (train and held-out are already marked), but **measure before
> you change anything** and only keep a change if it genuinely helps — don't
> overfit. Settings are in `run-config.json`."

The skill triggers automatically on requests to optimize / tune / harden a prompt
against examples, to reduce its failure rate, or to set up an eval- or
golden-set-driven improvement loop — even if you never say the word "loop". It
will then:

1. Run the **pre-flight** config validation and verify the deterministic core.
2. Measure a **baseline** score on train + held-out *before* proposing anything.
3. Run the gated loop — one change per turn, on **staged copies only**.
4. Present the result as a **batch**: the diff (start vs candidate),
   `history.jsonl` (the score trail), and `failure-log.jsonl` (what was tried and
   dropped). You then **commit** — the first and only write to your live file —
   or **revert**.

**The loop is semi-autonomous: it does *not* ask you to approve every change.**
You design the exam and the config; the turns run on their own. The final quality
check — actually *using* the improved prompt — stays with you. A passing
golden-set score is necessary, but not sufficient.

### Verify the deterministic core

Before trusting any run, you can verify the code that makes every irreversible
decision:

```bash
python3 skills/agent-coach/scripts/tests/run.py          # 219 tests, stdlib only
# or:  python3 -m pytest skills/agent-coach/scripts/tests/
```

Every script reads its JSON payload from **stdin** (or a file-path argument) —
never as an inline argv string:

```bash
printf '%s' '<json>' | python3 skills/agent-coach/scripts/score_compare.py
```

(Run scripts from the repository root — the paths are relative to the project
root, not to this `docs/` page.)

---

## Usage by scenario

The three scenario types below mirror the skill's own end-to-end evals in
[`../../skills/agent-coach/evals/evals.json`](../../skills/agent-coach/evals/evals.json).

### Scenario 1 — Warm start (you already have a golden set)

**You have:** a target file, plus a `golden-set.json` with `train`/`heldout`
already marked.

> "Tune `./prompts/summarizer.md` so it scores better on the cases in
> `golden-set.json` — but **measure before you change anything**, and only keep a
> change if it genuinely helps. Don't overfit. Settings are in `run-config.json`."

**What happens:** the config is validated → a baseline is measured on train +
held-out → the gated loop runs (one change per turn, staged copies only) → only
changes that beat noise and survive the confirm re-run are merged → you get a
diff + `history.jsonl` + `failure-log.jsonl` and decide to **commit or revert**.
Your live file stays untouched until you commit.

### Scenario 2 — Cold start (no golden set yet)

**You have:** a target, and maybe a dump of raw logs — but **no labeled test
set**.

> "`classify.md` is my support-ticket classifier and it keeps mislabeling things.
> Make it better. I don't have a test set — there's just a dump of raw inbox lines
> in `seed-logs.txt`. Settings are in `run-config.json`."

**What happens:** the skill detects there is no golden set — and does **not**
invent one to grade itself against. Instead, the **Bootstrapper** drafts candidate
*inputs*, the target runs once so its real failures show, and the loop **stops at
the human checkpoint**: you curate the inputs and write the yes/no criteria, and
the skill reminds you of the size gate (`train ≥ 5`, `heldout ≥ 3`). Only after
you finish curating does the optimization loop start. The full path is described
under [Cold start](#cold-start-no-golden-set-yet) below.

### Scenario 3 — Overfit guard (a tempting change that breaks generalization)

**You have:** a target + golden set, and an obvious "just always do X" fix in
mind.

> "Tune my job-posting field extractor `extract.md` against `golden-set.json`. The
> big problem: it leaves `salary_range` null too often — I want it filled in.
> Settings are in `run-config.json`."

**What happens:** the natural "always fill in a salary" change raises the
**train** score but breaks **held-out** (the postings that state no salary), so
the code returns **HALT** — the change never reaches your target. The halted
attempt is logged, together with a `candidate_input` (a case worth adding to the
next golden-set version). You have just been protected from silently teaching your
prompt to hallucinate.

---

## Resuming an interrupted run

Every run can be resumed. If a run is interrupted, `state.json` has recorded the
current turn and phase, and `resume.py` re-enters from the last completed step —
**idempotently**, meaning a merge is never applied twice.

> "Resume the agent-coach run for `summarizer.md` where it left off."

A sample `state.json` (alongside its `history.jsonl` and `failure-log.jsonl`)
ships at
[`../../examples/agent-coach/en/loop-state/`](../../examples/agent-coach/en/loop-state),
so you can see exactly what the resumable state machine records.

---

## Cold start: no golden set yet

If there is no golden set, the loop does **not** invent one and grade against
it — that would be a self-graded exam. The missing state is detected
*deterministically* (`split_goldenset.py op=state` returns `missing`/`empty`), and
then:

1. **Seed.** Pull inputs from your logs if you have them, and/or let the
   **Bootstrapper** draft input *candidates*. Run the Bootstrapper even when logs
   exist, if the logs are easy or happy-path only — a flattering set will find
   nothing.
2. **Expose failures.** The target runs once (via the Runner) on the candidates,
   so you can see where it actually fails.
3. **You curate.** *You* approve or prune the inputs, and add the hard cases that
   are missing. You own input selection, not just the criteria — that is what
   blocks shared blind spots.
4. **You write the criteria.** *You* write the yes/no rubric (5–7 criteria per
   input).
5. **Split.** `split_goldenset.py` splits train/held-out *after* curation, placing
   the **most realistic** items in held-out, and freezes the split with a hash.
6. **Size gate.** It refuses — or warns hard — below `train < 5` or `heldout < 3`.

The loop stops at the curation checkpoint and asks you to approve inputs and write
the rubric — it will not quietly finalize a set and then optimize against it.
*What* to curate into the set is its own page: see
[`golden-set.md`](./golden-set.md), and
[`../../skills/agent-coach/agents/bootstrapper.md`](../../skills/agent-coach/agents/bootstrapper.md)
for what the Bootstrapper does and does not do.

---

## What a run costs

The rough shape of one turn:

```
Runner (current + candidate-verify + confirm) × set size
  + Grader (same) + Proposer (1)
  ≈ ~65 model calls on a PROMOTE turn for |train| = 5, |held| = 3
    (the confirm step re-runs BOTH the candidate and the current/baseline prompt)
  ≈ ~33 on a non-promote turn (DISCARD/HALT skip confirm)
  + k_calib calibration runs (once, at cold start)
```

The budget is a **hard constraint, not a suggestion**: set `budget.max_usd_total`
and `budget.max_usd_per_turn` in `run-config.json`. Total cost scales with
`n_turns` and the golden-set size; the loop tracks `budget_spent_usd` in
`state.json` and stops when a cap is hit.

---

## See also

- [`golden-set.md`](./golden-set.md) — building the exam the loop grades against
  (the highest-leverage thing you own).
- [`run-config.md`](./run-config.md) — every `run-config.json` field, and the
  pre-flight check that enforces honest measurement.
- [`../../skills/agent-coach/references/safety-invariants.md`](../../skills/agent-coach/references/safety-invariants.md)
  — S1–S7: why the merge gate, the held-out HALT, and staging exist.
- [`../../skills/agent-coach/references/loop-concepts.md`](../../skills/agent-coach/references/loop-concepts.md)
  — the principles behind every design choice.
