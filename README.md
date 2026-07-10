# Loop — measured prompt improvement

> **Two [Claude Code](https://docs.claude.com/en/docs/claude-code) skills that improve a prompt, skill, or instruction file by *measurement*, not by feel.**

*Read this in another language: [한국어](./README.ko.md)*

This repository contains **two Claude Code skills that work as a pair** (both live under [`skills/`](./skills)). They share one principle — **"no evolution without measurement"**, meaning no change is kept unless a measurement shows it actually helped — and they are designed to be used in sequence:

| Skill | What it does | Use it when |
|---|---|---|
| [**agent-coach**](#agent-coach) | Improves a target prompt/skill/instruction file in small measured steps: score it, change one thing, score it again, and keep the change only if the score truly went up. | You already have a golden set and want to improve a prompt against it. |
| [**golden-set-drafter**](#golden-set-drafter) | Drafts that golden set *for* agent-coach when you don't have one, then stops at a checkpoint where **you** write the held-out grading criteria yourself. | You want to improve a prompt but **have no golden set yet**. |

**What is a golden set?** A small, fixed collection of test cases. Each case is a realistic input plus a list of yes/no grading questions (for example, "Did the answer mention X?"). It is the exam your prompt is scored against. Part of the set, called **held-out**, is kept aside and never used for tuning — it exists only to check that an improvement works on cases the loop never optimized for.

No golden set yet? Run **golden-set-drafter** first to create a draft, then hand its output to **agent-coach**.

---

## agent-coach

agent-coach improves a prompt the way a coach trains an athlete: **measure, change one thing, measure again, and keep the change only if the score really went up.** It never edits on a hunch. Whether a change survives is decided by *deterministic code*, not by a model's opinion.

Concretely, when agent-coach reports a `MERGE` (a change it kept), that means all of the following were verified:

- the change raised the training score by more than normal measurement noise,
- the held-out score did not get worse (the generalization check),
- the gain survived one more confirming re-run,
- and your live file still has not been touched — nothing changes on disk until you commit the result.

What makes it different from "let the AI rewrite my prompt":

- **Code makes every keep/discard decision** — a fixed inequality, not a model saying "this looks better."
- **Train / held-out split**: changes are tuned on the train cases and checked on the held-out cases. If a change wins on train but breaks held-out, that is overfitting, and the loop stops with a **HALT**.
- A gain must **beat measured noise** *and* hold up in a confirming re-run. A lucky +1 does not get kept.
- **Four separated roles** — the model that proposes a change never grades it (proposer ≠ grader ≠ runner ≠ bootstrapper).
- **Staging only** — all edits happen on a working copy. Your real file stays untouched until *you* commit.

### Using it

You drive it in plain language; the skill runs its own scripts. A typical kickoff:

> "Tune `./prompts/summarizer.md` so it scores better on the cases in `golden-set.json` (train and held-out are already marked), but **measure before you change anything** and only keep a change if it genuinely helps — don't overfit. Settings are in `run-config.json`."

The skill then validates the config, measures a **baseline** score on train + held-out, runs the loop (one staged change per turn, each gated by code), and finally hands you the result as a batch to **commit or revert** — committing is the first and only moment your live file changes. To check the decision-making code itself before trusting a run:

```bash
python3 skills/agent-coach/scripts/tests/run.py          # 219 tests, standard library only
```

📖 **Manual** — [`docs/agent-coach/`](./docs/agent-coach): [building a good golden set](./docs/agent-coach/golden-set.md) · [configuring the run](./docs/agent-coach/run-config.md) · [running the loop](./docs/agent-coach/running.md) · [how it works — design & safety](./docs/agent-coach/how-it-works.md). Korean versions: `*.ko.md`.

---

## golden-set-drafter

golden-set-drafter is the companion skill for the moment you have **no golden set yet**. It runs **before, and instead of,** agent-coach, and drafts a first golden set (v1) from two things you provide: the target file, and a short "development direction" note describing what the target should get better at.

How the draft is made:

- Three AI roles — a proposer, an adversary (attacker), and an arbiter (judge) — debate and refine the case inputs and the train-side grading criteria until they reach agreement.
- Every train case is then run against **your real target file with your real production model**, so each case carries evidence of whether the current prompt actually fails it.
- One thing is deliberately left blank: **the held-out grading criteria.** The skill never writes them — you do. While they are empty, agent-coach's `op=split` command refuses to run, so the improvement loop can never "study for" its own final exam. That blank is a safety device, not an oversight.

### Using it

> "I want to improve `./agents/support-agent.md` but there's no golden set yet. The development direction is in `./direction.md`. Draft the golden set first."

The skill emits a **draft** (every held-out grading list empty) and **stops at the checkpoint**. Four steps then belong to you: review the held-out inputs, write every held-out grading criterion yourself, run the `op=split` command (its first run is *supposed* to fail — that refusal is the checkpoint doing its job), and run it again once everything is filled in, which freezes the set. From there, agent-coach takes over.

📖 **Document** — [`docs/golden-set-drafter/golden-set-drafter.md`](./docs/golden-set-drafter/golden-set-drafter.md) (Korean: [`golden-set-drafter.ko.md`](./docs/golden-set-drafter/golden-set-drafter.ko.md)).

---

## Repository layout

```
.
├── README.md · README.ko.md          # This landing page (English / Korean)
├── docs/                             # Full manuals — English + Korean (*.ko.md)
│   ├── agent-coach/                  #   golden-set · run-config · running · how-it-works
│   └── golden-set-drafter/           #   golden-set-drafter.md — the drafter's document
├── examples/                         # Copy-paste-ready examples per skill (en/ + ko/ mirror)
│   ├── agent-coach/
│   └── golden-set-drafter/
├── skills/                           # The two Claude Code skills themselves
│   ├── agent-coach/                  #   SKILL.md · agents/ · scripts/ (219 tests) · references/ · evals/ · assets/
│   └── golden-set-drafter/           #   SKILL.md · agents/ · scripts/ · references/ · evals/ · assets/
└── loop/                             # Working state for each run (see below)
```

Each run keeps its working state in `loop/<target>/`. Everything there is a plain file you can open and read, and an interrupted run can be resumed from them:

- `golden-set.json` — the exam (cases + grading criteria)
- `prompt.current.md` / `prompt.candidate.md` — the working copies the loop edits (never your live file)
- `history.jsonl` — one line per turn: what was tried and how the scores moved
- `failure-log.jsonl` — attempts that were discarded or halted, and why
- `state.json` — how far the run has progressed, so resuming never repeats a completed step

---

## Requirements

- **Python ≥ 3.8** for the bundled scripts — **standard library only**, nothing to install.
- **Claude Code** with subagents — each role (runner, grader, proposer, bootstrapper) runs as its own subagent from a clean context. That is what makes the role separation real rather than nominal.
