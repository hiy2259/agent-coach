# Loop — measured prompt improvement

> **Two [Claude Code](https://docs.claude.com/en/docs/claude-code) skills that improve a prompt, skill, or instruction file by *measurement*, not vibes.**

*Read this in another language: [한국어](./README.ko.md)*

This repository hosts **two complementary Claude Code skills** (under [`skills/`](./skills)). Both obey one rule — **"no evolution without measurement"** — and they chain together:

| Skill | What it does | Reach for it when |
|---|---|---|
| [**agent-coach**](#agent-coach) | Tunes a target prompt/skill/instruction file with a measured self-improvement loop: measure → change one thing → measure → keep it only if the score really rose. | You have a golden set and want to improve a prompt against it. |
| [**golden-set-drafter**](#golden-set-drafter) | Drafts a v1 golden set *for* agent-coach (council-reviewed, failure-exposed), then stops at a gate where **you** author the held-out rubrics. | You want to improve a prompt but have **no golden set yet**. |

No golden set yet? Run **golden-set-drafter** first to draft one, then hand its output to **agent-coach**.

---

## agent-coach

Tunes a target prompt the way a coach trains an athlete: **measure → change ONE thing → measure again → keep it only if the score really went up.** Its governing rule is **"no evolution without measurement"** — it never edits on a hunch, and *deterministic code* (not a model's opinion) decides whether each change survives. A `MERGE` is not "the model thought it looked better"; it is a single, code-verified change that beat measured noise on training cases, held generalization on held-out cases, and survived a confirming re-run — and your live file is untouched until you commit.

What makes it different, in short:

- **Code decides every merge** — a fixed inequality, not a model's "looks better."
- **Train + held-out split** guards generalization; overfitting triggers a **HALT**.
- A gain must **beat calibrated measurement noise** *and* survive a confirming re-run.
- **Four isolated actors** — proposer ≠ grader ≠ runner ≠ bootstrapper.
- **Staging only** — your live file is byte-for-byte untouched until you commit.

### Using it

Drive it in natural language; the orchestrator runs the scripts, not you. A typical kickoff:

> "Tune `./prompts/summarizer.md` so it scores better on the cases in `golden-set.json` (train and held-out are already marked), but **measure before you change anything** and only keep a change if it genuinely helps — don't overfit. Settings are in `run-config.json`."

It validates the config, measures a **baseline** on train + held-out, runs the gated loop (one **staged** change per turn), and hands you a batch to commit or revert — your live file stays untouched until you commit. Verify the deterministic core before trusting a run:

```bash
python3 skills/agent-coach/scripts/tests/run.py          # 219 tests, stdlib only
```

📖 **Manual** — [`docs/agent-coach/`](./docs/agent-coach): [building a good golden set](./docs/agent-coach/golden-set.md) · [configuring the run](./docs/agent-coach/run-config.md) · [running the loop](./docs/agent-coach/running.md) · [how it works — design & safety](./docs/agent-coach/how-it-works.md). Korean mirrors: `*.ko.md`.

---

## golden-set-drafter

The companion that runs **before, and instead of,** agent-coach when you have no golden set. It drafts a golden-set v1 from your target file (+ a development-direction doc): a proposer → adversary → arbiter council refines the case inputs and train rubrics, and every train case is run against your **real target with the real production model** to attach failure evidence. But it **never writes the held-out rubrics** — those stay yours. That blank is the load-bearing safety device: agent-coach's `op=split` refuses to run until you author them, so the improvement loop can never "study for" its own held-out exam.

### Using it

> "I want to improve `./agents/support-agent.md` but there's no golden set yet. The development direction is in `./direction.md`. Draft the golden set first."

It emits a **draft** (every held-out rubric empty) and **stops at the gate**. From there it is your four steps: review the held-out inputs, author every held-out rubric, run the `op=split` command to freeze (the first run is meant to fail — that refusal *is* the gate), and re-run once filled to freeze the set. Then agent-coach takes over.

📖 **Document** — [`docs/golden-set-drafter/golden-set-drafter.md`](./docs/golden-set-drafter/golden-set-drafter.md) (Korean: [`golden-set-drafter.ko.md`](./docs/golden-set-drafter/golden-set-drafter.ko.md)).

---

## Repository layout

```
.
├── README.md · README.ko.md          # This landing page (English / Korean)
├── docs/                             # Full manuals — English + Korean (*.ko.md)
│   ├── agent-coach/                  #   golden-set · run-config · running · how-it-works
│   └── golden-set-drafter/           #   golden-set-drafter.md — the drafter's document
├── examples/                         # Copy-paste-ready examples per skill (ko/ + en/ mirror)
│   ├── agent-coach/
│   └── golden-set-drafter/
├── skills/                           # The two Claude Code skills
│   ├── agent-coach/                  #   SKILL.md · agents/ · scripts/ (219 tests) · references/ · evals/ · assets/
│   └── golden-set-drafter/           #   SKILL.md · agents/ · scripts/ · references/ · evals/ · assets/
└── loop/                             # Per-run working state (see below)
```

Each run's working state lives in `loop/<target>/` and is fully human-readable and resumable: `golden-set.json`, `prompt.current.md` / `prompt.candidate.md` (staging — never your live file), `history.jsonl` (per-turn score trail), `failure-log.jsonl` (discarded/halted attempts), and `state.json` (turn state machine for idempotent resume).

---

## Requirements

- **Python ≥ 3.8** for the bundled scripts — **standard library only**, no third-party packages.
- **Claude Code** (subagents) — to keep each skill's actors genuinely isolated, each running from a clean context.
