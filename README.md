# Agent Coach

> **Iteratively improve a prompt, skill, or instruction file with a *measured* self-improvement loop — never on vibes.**

*Read this in another language: [한국어](./README.ko.md)*

`agent-coach` is a [Claude Code](https://docs.claude.com/en/docs/claude-code) skill (it lives in [`agent-coach/`](./agent-coach)) that tunes a target prompt/skill/instruction file the way a good coach trains an athlete:

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
- [Quick start](#quick-start)
- [📖 Full manual](#full-manual-docs)
- [Repository layout](#repository-layout)
- [Bundled scripts](#bundled-scripts)
- [Requirements](#requirements)

---

## Why this exists

"Self-improvement" sounds great, but it is a trap the moment it goes unmeasured. A model edits a prompt, declares it better, and the prompt slowly drifts on vibes — sometimes worse, with nobody able to tell. Three specific ways that drift hides real failure:

1. **Noise mistaken for progress.** At a realistic temperature, the target's output wobbles between runs. A "+1 on training" can be pure luck. Merge inside that noise band and you ratchet randomness into the prompt — the score creeps up while the prompt gets *worse*.
2. **Overfitting.** A change can memorize the quirks of the cases you optimized against and quietly destroy generalization — the classic "98% on train, broken in production" trap.
3. **The self-graded exam.** Ask a model "did your change help?" and, having just produced it, it is primed to say yes. A player must not referee their own game.

`agent-coach` is built to remove each of these failure modes mechanically, so that "better" is an **observed quantity** rather than an opinion.

---

## What makes it different

| Most "AI improves a prompt" tools | `agent-coach` |
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

The single most important structural rule: **the model that proposes a change is not the model that grades it, and neither is the model that runs the target.** Each actor is a separate Claude Code subagent with its own prompt under [`agent-coach/agents/`](./agent-coach/agents), so each starts from a clean context and the separation is *real*, not nominal.

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
⑨ Confirm  if MERGE: re-run + re-grade ONCE more — BOTH the candidate AND the
           current (baseline) prompt; the gain must still hold vs the re-measured baseline
⑩ Record   MERGE  → promote candidate to current + append history.jsonl
           DISCARD→ failure-log.jsonl (+ candidate_input); keep the live file
           HALT   → stop + warn + failure-log.jsonl (result: halted)
```

**Why confirm by re-running, not just re-grading (⑨)?** The Grader runs at temperature 0, so re-grading the *same text* returns the identical score — a no-op. Real noise comes from the **Runner** producing different outputs across runs. So a merge is confirmed by *running the target again* and re-grading the fresh output. Confirm re-runs **both the candidate AND the current (baseline) prompt**, and re-checks the gate against the freshly re-measured baseline (`train_b2`/`held_b2`): reusing the first gate's baseline would correlate the two checks and roughly halve confirm's power to reject luck. If the gain evaporates against that fresh baseline, it was noise.

### The merge gate (the heart)

[`score_compare.py`](./agent-coach/scripts/score_compare.py) — not a model — makes the decision. A change **MERGES only when all of these hold:**

```
train_after   >  train_before                      (a strictly positive gain — a +0.0 tie never merges)
train_after   ≥  train_before   + eps_train        (the gain beats measurement noise on train)
heldout_after ≥  heldout_before − eps_heldout       (no real regression on held-out)
AND the gain still holds after the confirm re-run (⑨)
```

Otherwise:

- If `train` rises but `heldout` falls by **more than** `eps_heldout` → **HALT** (overfitting: the change memorized train and broke generalization). HALT is terminal.
- Otherwise → **DISCARD** (no real gain; the addition is reverted).

The margins `eps_train` / `eps_heldout` are **measurement noise**, calibrated by [`calibrate_noise.py`](./agent-coach/scripts/calibrate_noise.py): it re-runs the Runner on fixed inputs `k_calib` times (≥5 recommended), grades each, and derives the score spread per split — floored at a small positive `min_eps` so a `+0.0` tie can never look like progress. The held-out margin is **symmetric** (`eps_heldout` on both the merge and HALT side), so ordinary held-out noise does not trigger false HALTs.

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

These are the reason the skill exists. Each removes one specific way "self-improvement" silently degrades into evolution-without-measurement. Full statements: [`references/safety-invariants.md`](./agent-coach/references/safety-invariants.md).

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

## Quick start

This is a Claude Code skill — you drive it in natural language; the orchestrator runs the scripts, not you. A typical kickoff:

> "Tune `./prompts/summarizer.md` so it scores better on the cases in `golden-set.json` (train and held-out are already marked), but **measure before you change anything** and only keep a change if it genuinely helps — don't overfit. Settings are in `run-config.json`."

It validates the config, measures a **baseline** on train + held-out, runs the gated loop (one **staged** change per turn), and hands you a **batch to commit or revert** — your live file is untouched until you commit. It is semi-autonomous: you sit *on* the loop, not in every turn, and the final "does it actually work" QA stays with you.

→ **Full walkthrough** — the three scenarios (warm start / cold start / overfit-guard), resuming an interrupted run, cold start, and cost — is in [`docs/running.md`](./docs/running.md).

### Verify the deterministic core

Before trusting any run, verify the code that makes every irreversible decision:

```bash
python3 agent-coach/scripts/tests/run.py          # 197 tests, stdlib only
# or:  python3 -m pytest agent-coach/scripts/tests/
```

Every script reads its JSON payload on **stdin** (or a file-path arg), never as an inline argv string:

```bash
printf '%s' '<json>' | python3 agent-coach/scripts/score_compare.py
```

---

## Full manual: `docs/`

📖 The detailed how-to guide lives in [`docs/`](./docs) — in English and Korean (`*.ko.md`):

| Guide | What it covers |
|---|---|
| [**Building a good golden set**](./docs/golden-set.md) | The golden set is the moat: choosing cases, the rubric-writing craft, the train/held-out split, calibration, evolving the set between runs, anti-patterns, and a worked example. |
| [**Configuring the run**](./docs/run-config.md) | Every `run-config.json` field, the three rules that keep measurement honest, and the pre-flight check. |
| [**Running the loop**](./docs/running.md) | Quick start, the three real-world scenarios, resuming an interrupted run, cold start, and cost. |

Korean mirrors: [`golden-set.ko.md`](./docs/golden-set.ko.md) · [`run-config.ko.md`](./docs/run-config.ko.md) · [`running.ko.md`](./docs/running.ko.md).

---

## Repository layout

The README lives at the project root; the skill itself is in `agent-coach/`, with copy-paste-ready inputs in `examples/`.

```
.
├── README.md                          # This file (English)
├── README.ko.md                       # Korean version
├── docs/                              # Full manual (English + Korean .ko.md)
│   ├── golden-set.md                  #   the golden set — the moat (cases, rubric, split)
│   ├── run-config.md                  #   every run-config.json field + pre-flight
│   └── running.md                     #   quick start, scenarios, resuming, cold start, cost
├── examples/                          # Copy-paste-ready example inputs & state
│   ├── run-config.example.json        #   run config (Korean-annotated)
│   ├── golden-set/                    #   golden set + cases/ (Korean-annotated)
│   ├── loop-state/                    #   sample history / failure-log / state
│   └── en/                            #   English mirror of everything above
│       ├── run-config.example.json
│       ├── golden-set/
│       └── loop-state/
└── agent-coach/                    # The skill
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
    │   ├── aggregate_scores.py        #     ②/⑦ per-case Scores → per-split train/heldout
    │   ├── score_compare.py           #     ⑧ MERGE / DISCARD / HALT decision
    │   ├── calibrate_noise.py         #     eps_train / eps_heldout + gate_satisfiable
    │   ├── split_goldenset.py         #     classify state + split & freeze the set
    │   ├── resume.py                  #     idempotent resume after interruption
    │   ├── _common.py                 #     shared helpers (stdin payload, hashing)
    │   └── tests/                     #     197 tests over the core (run.py)
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

Code makes every irreversible decision; the model only generates and grades. All scripts are under [`agent-coach/scripts/`](./agent-coach/scripts).

| Step | Script | Role |
|---|---|---|
| pre-flight | `validate_config.py` | Validate run-config: actor separation, grader temp 0 |
| ④ | `verify_change.py` | Verify exactly one localized change (unique `before` + locality caps) |
| ⑤ / ⑩ | `apply_change.py` | Apply to staging; promote candidate → current on merge (re-runs the verify gate) |
| ② / ⑦ | `aggregate_scores.py` | Reduce per-case Scores → per-split train/heldout (Σpassed / Σtotal) |
| ⑧ | `score_compare.py` | The merge gate: MERGE / DISCARD / HALT from a fixed inequality |
| calibration | `calibrate_noise.py` | Derive `eps_train` / `eps_heldout`; report `gate_satisfiable` |
| cold start / split | `split_goldenset.py` | Classify golden-set state (`op=state`); split & freeze (`op=split`) |
| resume | `resume.py` | Idempotent resume from the last completed phase |

---

## Requirements

- **Python ≥ 3.8** for `agent-coach/scripts/` — **standard library only**, no third-party packages.
- **Claude Code** (subagents) — to keep the four actors genuinely isolated, each running from a clean context.

---
