# golden-set-drafter — the companion skill that drafts a golden set when you have none

> **Want to improve a prompt with agent-coach, but have no golden set yet? This skill runs first.**
> It drafts a first golden set (v1) from your target file and a development-direction note — but it
> **never writes the held-out grading criteria**. Those stay yours to write, and that deliberate
> blank is the design's most important safety device.
> 한국어판: [`golden-set-drafter.ko.md`](./golden-set-drafter.ko.md)

The full skill contract: [`skills/golden-set-drafter/SKILL.md`](../../skills/golden-set-drafter/SKILL.md)

---

## What it does

`golden-set-drafter` is the companion skill to [agent-coach](../agent-coach/running.md).
agent-coach needs a golden set (the exam) before it can run, and building one from scratch
is hard if you don't yet know the golden-set rules. This skill does the heavy lifting, in
three steps:

1. **Council drafting.** Three AI roles — proposer → adversary → arbiter — work over the
   case inputs and the train-side grading criteria: one proposes, one attacks, one rules.
   Only what survives the debate goes into the draft.
2. **Failure exposure.** Every train case is run against **your real target file with your
   real production model**, and the result is attached as evidence: does the current prompt
   actually fail this case? (This check is train-only — held-out inputs are never run, so
   nothing gets an early look at them.)
3. **Unfrozen output.** What comes out is a **draft**, not a finished set: every held-out
   grading list is empty, and there is no `split_hash`. agent-coach's code gate then
   enforces that a human fills those blanks.

When no golden set exists, the correct order is: run this skill **before, and instead of,**
agent-coach.

## What you provide (inputs)

Two inputs are required; a third is optional:

| Input | Required | What it is |
|---|---|---|
| **Target file** | yes | The prompt / skill / instruction file to build the set for — a path, e.g. `./agents/support-agent.md`. |
| **Development direction** | yes | What the target should get *better at*: goals, failure stories, logs, collected experience. Free text or a file, e.g. `./direction.md`. It steers which cases the council drafts. |
| **Prior golden set** | no | If you pass an existing set, v1 replies that update/evolve mode is a v2 feature and **stops**. It only ever drafts a fresh v1 — it never half-updates an existing set. |

It also reads the target's `run-config.json` automatically, to match your **production
model + temperature** — the "ruler" it measures train failures with. (Measure with the
wrong ruler and the draft arrives saturated: everything looks fine and nothing can be
learned.) No run-config? In an interactive session it **asks you** for the real model and
temperature; in a headless run it scaffolds one and marks the ruler as *assumed*. Full
option reference: [run-config](../agent-coach/run-config.md).

## What it produces (three artifacts)

| Artifact | Contents | Example |
|---|---|---|
| `golden-set.json` | train cases (inputs + grading criteria complete) + held-out cases (inputs only, **criteria empty**), unfrozen | [`draft-output/golden-set.example.json`](../../examples/golden-set-drafter/en/draft-output/golden-set.example.json) |
| `GOLDEN-SET-DRAFT-README.md` | A runbook written in the language of your own cases: your 4 next steps + **the ten honest limitations** + a "Gate data" appendix holding the exact `op=split` command | Skeleton: [`runbook-template.md`](../../skills/golden-set-drafter/assets/runbook-template.md) |
| `GOLDEN-SET-DRAFT-RUNLOG.json` | The record of the council debate, the ruler used, and the failure-exposure results | [`draft-output/GOLDEN-SET-DRAFT-RUNLOG.example.json`](../../examples/golden-set-drafter/en/draft-output/GOLDEN-SET-DRAFT-RUNLOG.example.json) |

## Why the held-out criteria arrive empty (the heart of the design)

Held-out is the sealed exam the improvement loop can never study for — the only guard
against overfitting. Now imagine that the same AI that drafted the inputs also got to
define "what a good answer looks like" for those held-out cases. The exam would collapse
into the AI grading its own test: the loop would optimize toward that AI's blind spots,
with nothing left to catch it.

So this skill:

- **never writes held-out criteria in any form.** It refuses to provide examples, starting
  points, or "just a rough draft" — rule §5-2 of the skill contract, no exceptions. The
  refusal itself is part of the safety design.
- leaves the enforcement to **code**: agent-coach's `op=split` fails while any held-out
  criteria are empty, and its error names exactly which case ids are missing. That error
  *is* the gate — here is a real captured run:
  [`gate-first-run.example.json`](../../examples/golden-set-drafter/en/gate-first-run.example.json).

## How to run it

It is a Claude Code skill — start it in plain language:

> "I want to improve `./agents/support-agent.md` but there's no golden set yet. The
> development direction is in `./direction.md`. Draft the golden set first."

After producing the draft, the skill **stops at the gate**. What follows are your four
steps (the emitted runbook walks you through them, written in terms of your own cases):

1. Review the held-out **inputs**. They are AI drafts — replace any that don't look like
   real production requests.
2. **Write every held-out grading criterion yourself.** The guide for this step is
   [`heldout-rubric-guide.md`](../../skills/golden-set-drafter/references/heldout-rubric-guide.md).
   In short: each criterion must be a yes/no question a temperature-0 grader can answer
   consistently; 5–7 deliberate criteria per case; at least one "did not make things up"
   guard; criteria independent of each other; within what the model can actually do;
   describing the properties of a good answer, not one exact answer — and guard criteria
   spread across cases, not concentrated in one.
3. Run the **`op=split` command** from the runbook's "Gate data" appendix. The first run is
   expected to **fail** — that is the gate above, doing its job.
4. Fill in the blanks and run it again to **freeze** the set. From there, agent-coach's
   calibration judges whether the set can measure anything, and the
   [improvement loop](../agent-coach/running.md) takes over.

## Scope and honest limits

- **v1 drafts fresh sets only.** Given an existing golden set as input, it states that
  update/evolve mode is a v2 feature and **stops** — it never half-updates.
- The failure-exposure evidence is a **train-only heuristic**. The final authority on
  whether the set can drive a run (discrimination / saturation) is agent-coach's
  calibration step.
- Train inputs AND train criteria are both AI-authored — a conscious v1 trade-off. What
  seals it is the human-owned held-out criteria, plus agent-coach's S1 overfitting HALT.
- Every emitted runbook carries **all ten honest limitations in full** — the emit code
  counts the numbered items and refuses to produce a runbook with fewer.

## Further reading

| Document | Contents |
|---|---|
| [`skills/golden-set-drafter/SKILL.md`](../../skills/golden-set-drafter/SKILL.md) | The full skill contract (steps, rules, §5-2) |
| [`heldout-rubric-guide.md`](../../skills/golden-set-drafter/references/heldout-rubric-guide.md) | The writing guide for the human at the gate |
| [`examples/golden-set-drafter/`](../../examples/golden-set-drafter/en/draft-output/golden-set.example.json) | Example outputs (`ko/` / `en/` mirror) |
| [`../agent-coach/golden-set.md`](../agent-coach/golden-set.md) | Golden-set craft in general — the guide this skill defers to |
| [`../agent-coach/running.md`](../agent-coach/running.md) | Running the improvement loop after the freeze |
