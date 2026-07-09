# golden-set-drafter — the companion skill that drafts a golden set when you have none

> **Want to improve a prompt with agent-coach but have no golden set yet? This skill runs first.**
> It drafts a golden-set v1 from your target file (+ a development-direction doc), but it
> **never writes the held-out rubrics** — those stay yours. That blank is the design's
> load-bearing safety device.
> 한국어판: [`golden-set-drafter.ko.md`](./golden-set-drafter.ko.md)

The skill contract in full: [`skills/golden-set-drafter/SKILL.md`](../../skills/golden-set-drafter/SKILL.md)

---

## What it does

`golden-set-drafter` is the companion skill to [agent-coach](../agent-coach/running.md).
agent-coach needs a golden set (the exam) to run, and building one from scratch is hard
for users who don't know the golden-set rules. This skill does the heavy lifting:

1. **Council drafting** — a proposer → adversary → arbiter council adversarially refines
   case inputs and train rubrics until consensus.
2. **Failure exposure** — runs the train cases against **your real target with the real
   production model**, attaching measured evidence of "does the current prompt actually
   fail here" (a train-only heuristic — held-out inputs are never run, to prevent
   anchoring).
3. **Unfrozen emission** — it emits a **draft**, not a finished set: every held-out
   rubric empty, no `split_hash`. agent-coach's code gate then enforces human authorship.

When no golden set exists, the correct order is: this skill runs **before, and instead
of,** agent-coach.

## What you provide (inputs)

Two inputs are required; a third is optional:

| Input | Required | What it is |
|---|---|---|
| **Target file** | yes | The prompt / skill / instruction file to build the set for — a path, e.g. `./agents/support-agent.md`. |
| **Development direction** | yes | What the target should get *better at* — goals, failure stories, logs, collected experience. Free text or a file, e.g. `./direction.md`. It steers which cases the council drafts. |
| **Prior golden set** | no | Passing an existing set makes v1 say "update/evolve is a v2 feature" and **stop** — it only ever drafts a **fresh v1**, never half-updates. |

It also reads, automatically, the target's `run-config.json` to match the **production model + temperature** — the "ruler" it exposes train failures at (a wrong ruler makes the draft arrive saturated). No run-config? Interactively it **asks you** for the real model/temperature; headless it scaffolds one and marks the ruler *assumed*. Full option reference: [run-config](../agent-coach/run-config.md).

## What it emits (three artifacts)

| Artifact | Contents | Example |
|---|---|---|
| `golden-set.json` | train (inputs + rubrics complete) + held-out (inputs only, **rubrics empty**), unfrozen | [`draft-output/golden-set.example.json`](../../examples/golden-set-drafter/en/draft-output/golden-set.example.json) |
| `GOLDEN-SET-DRAFT-README.md` | A runbook in the case language: 4 next steps + **ten honest limitations** + a Gate data appendix (the exact op=split command) | Skeleton: [`runbook-template.md`](../../skills/golden-set-drafter/assets/runbook-template.md) |
| `GOLDEN-SET-DRAFT-RUNLOG.json` | Council / ruler / expose record | [`draft-output/GOLDEN-SET-DRAFT-RUNLOG.example.json`](../../examples/golden-set-drafter/en/draft-output/GOLDEN-SET-DRAFT-RUNLOG.example.json) |

## Why the held-out rubrics arrive empty (the heart of the design)

Held-out is the sealed exam the improvement loop can never study for — the only guard
against overfitting. But **if the same AI that drafted the inputs also defines "what a
good answer looks like"**, the whole exam collapses into grading its own test: the loop
optimizes toward that AI's blind spots with nothing left to catch it.

So this skill:

- **never writes held-out rubrics in any form** — it refuses examples, starting points,
  and "just a draft" alike (§5-2, no exceptions; the refusal itself is load-bearing).
- instead, agent-coach's `op=split` enforces human authorship **in code**: run it while
  rubrics are empty and it fails, naming exactly those ids. That error is the gate —
  real captured output:
  [`gate-first-run.example.json`](../../examples/golden-set-drafter/en/gate-first-run.example.json).

## How to run it

It is a Claude Code skill — kick it off in natural language:

> "I want to improve `./agents/support-agent.md` but there's no golden set yet. The
> development direction is in `./direction.md`. Draft the golden set first."

After emission the skill **stops at the gate**. What follows are the human's four steps
(the emitted runbook walks you through them in the case language):

1. Review the held-out **inputs** — they are AI drafts; replace any that don't look
   like real production requests.
2. **Author every held-out rubric yourself** —
   [`heldout-rubric-guide.md`](../../skills/golden-set-drafter/references/heldout-rubric-guide.md)
   (binary/temp-0 · 5–7 intentional criteria · ≥1 guard · independent · within the
   ceiling · criteria-not-answers · guard pairs across cases).
3. Run the **op=split command** from the runbook's Gate data appendix — the first run
   is expected to fail (the gate above).
4. Re-run after filling to **freeze** — from there, agent-coach's calibration judges
   the set's usability and the [improvement loop](../agent-coach/running.md) takes over.

## Scope and honest limits

- **v1 drafts fresh sets only.** Given an existing golden set as input, it states that
  update/evolve mode is a v2 feature and **stops** — it never half-updates.
- The expose evidence is a **train-only heuristic**. The final authority on whether the
  set can drive a run (discrimination/saturation) is agent-coach's calibration.
- Train inputs AND rubrics are AI-authored (a conscious v1 trade) — sealed by the
  human-owned held-out rubrics plus the S1 overfit HALT.
- Every emitted runbook carries **all ten honest limitations in full** (the emit code
  counts the numbered items and refuses fewer).

## Further reading

| Document | Contents |
|---|---|
| [`skills/golden-set-drafter/SKILL.md`](../../skills/golden-set-drafter/SKILL.md) | The full skill contract (steps, rules, §5-2) |
| [`heldout-rubric-guide.md`](../../skills/golden-set-drafter/references/heldout-rubric-guide.md) | The authoring guide for the human at the gate |
| [`examples/golden-set-drafter/`](../../examples/golden-set-drafter/en/draft-output/golden-set.example.json) | Example emissions (`ko/` / `en/` mirror) |
| [`../agent-coach/golden-set.md`](../agent-coach/golden-set.md) | Golden-set craft in general — the doc this skill defers to |
| [`../agent-coach/running.md`](../agent-coach/running.md) | Running the improvement loop after the freeze |
