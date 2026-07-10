# How agent-coach works — design & safety

> The mechanics behind agent-coach's measured loop, and the reasoning for them: why the skill exists, what makes it different, what happens in one turn, how the merge gate decides, the seven safety rules, and the bundled scripts.

← Back to the [repository README](../../README.md) · manual: [golden set](./golden-set.md) · [run-config](./run-config.md) · [running](./running.md)

---

## Why this exists

"Self-improvement" sounds great, but the moment it goes unmeasured it becomes a trap. A model edits a prompt, declares the edit an improvement, and over many such edits the prompt slowly drifts — sometimes getting worse — while nobody can tell. Three specific failure modes hide inside that drift:

1. **Noise mistaken for progress.** At a realistic temperature, the same prompt produces slightly different output on every run, so its score wobbles from run to run. A "+1 on the training score" can be pure luck. Keep changes on the strength of lucky scores and the score creeps upward while the prompt itself gets *worse* — you have baked randomness into the text.
2. **Overfitting.** A change can win on exactly the cases you tuned against — by memorizing their quirks — while quietly getting worse at everything else. This is the classic "98% on the test set, broken in production" trap.
3. **The self-graded exam.** Ask a model "did your change help?" right after it made the change, and it is primed to say yes. A player must not referee their own game.

agent-coach is built to remove each of these failure modes *mechanically* — with code and process, not good intentions — so that "better" is a **measured fact**, not an opinion.

---

## What makes it different

| Most "AI improves a prompt" tools | agent-coach |
|---|---|
| The model decides whether a change helped | **Deterministic code** decides every merge, using a fixed inequality |
| One score, optimized directly | **Train + held-out split**: held-out guards generalization, and overfitting triggers a **HALT** |
| Any "+1" is accepted | A gain must **beat measured noise** *and* survive a confirming re-run |
| The same model proposes and grades | **Four separated roles** — proposer ≠ grader ≠ runner ≠ bootstrapper |
| Edits your live file directly | **Staging only** — your live file is untouched until *you* commit |
| Rules only ever pile up | **Subtraction turns** try *removing* a rule every 3rd turn |
| Retries ideas that already failed | A **failure log** is read back by the proposer, so known dead ends are not repeated |

---

## How it works

### The four roles

The single most important structural rule: **the model that proposes a change never grades it, and neither of them is the model that runs the target.** Each role runs as a separate Claude Code subagent with its own prompt (under [`skills/agent-coach/agents/`](../../skills/agent-coach/agents)), starting from a clean context. That makes the separation real, not just a naming convention.

| Role | Job | Notes |
|---|---|---|
| **Runner** | Execute the target prompt on a golden-set input and produce an output | Sandboxed: no write, network, or shell access; it reads only the golden input. The sandbox is also a **security boundary** — an arbitrary target prompt must not be able to hijack the host. It runs at your real production model and temperature, so the noise it measures is the noise you will see in real use. |
| **Grader** | Score an output against the rubric — one yes/no answer per criterion | Runs at **temperature 0** with a pinned version, so grading adds zero randomness of its own. |
| **Proposer** | Propose exactly **one** change per turn | Reads `failure-log.jsonl` first, so known dead ends are not proposed again. |
| **Bootstrapper** | Draft *candidate* inputs at cold start (when no golden set exists yet) | Must be a different model from the Grader. |

### One turn of the loop

The loop runs at most **N** turns (default 10). Each turn changes **at most one thing**, and code gates the outcome:

```
① Run       Runner executes the current target on ALL train + held-out inputs
② Grade     Grader scores the outputs → train_before, heldout_before
③ Propose   Proposer suggests ONE change {target_id, before, after, rationale, kind}
④ Verify    verify_change.py checks that `before` matches exactly one place and
            that the edit is small and local — otherwise the turn is rejected
            (this enforces "exactly one localized change")
⑤ Apply     apply_change.py writes the edit to the staging copy
            (prompt.candidate.md) only — the live target file is untouched
⑥ Re-run    Runner executes the candidate on ALL inputs
⑦ Re-grade  Grader scores again → train_after, heldout_after
⑧ Compare   score_compare.py decides — in code: MERGE / DISCARD / HALT
⑨ Confirm   on MERGE only: run + grade ONCE more — BOTH the candidate AND the
            current (baseline) prompt; the gain must still hold against the
            freshly re-measured baseline
⑩ Record    MERGE   → candidate is promoted to current + a line in history.jsonl
            DISCARD → logged to failure-log.jsonl (+ candidate_input); live file kept
            HALT    → stop + warn + log to failure-log.jsonl (result: halted)
```

**Why does the confirm step (⑨) re-run the target instead of just re-grading?** The Grader runs at temperature 0, so grading the same text twice returns the identical score — re-grading alone would check nothing. The real randomness comes from the **Runner**, which produces different output on every run. So a merge is confirmed by running the target again and grading the fresh output. The confirm step re-runs **both the candidate and the current (baseline) prompt**, and re-checks the gate against the freshly measured baseline (`train_b2` / `held_b2`). Reusing the first gate's baseline instead would let the two checks share the same luck, roughly halving confirm's power to catch a fluke. If the gain evaporates against the fresh baseline, it was noise all along.

### The merge gate (the heart)

The decision is made by [`score_compare.py`](../../skills/agent-coach/scripts/score_compare.py) — a script, not a model. A change is **merged only when all of these hold:**

```
train_after   >  train_before                      (a strictly positive gain — a +0.0 tie never merges)
train_after   ≥  train_before   + eps_train        (the gain beats measurement noise on train)
heldout_after ≥  heldout_before − eps_heldout       (no real regression on held-out)
AND the gain still holds after the confirm re-run (⑨)
```

Otherwise:

- If train rises but held-out falls by **more than** `eps_heldout` → **HALT**. The change memorized the train cases and broke generalization — overfitting, caught. A HALT ends the run.
- In every other case → **DISCARD**: no real gain was demonstrated, so the change is dropped.

The margins `eps_train` / `eps_heldout` represent **measurement noise**, and [`calibrate_noise.py`](../../skills/agent-coach/scripts/calibrate_noise.py) measures them: it re-runs the Runner on the same fixed inputs `k_calib` times (5 or more recommended), grades every run, and records how widely the score spreads per split. The result is floored at a small positive `min_eps`, so a +0.0 tie can never pass for progress. The held-out margin is **symmetric** — the same `eps_heldout` is used on the merge side and on the HALT side — so ordinary held-out wobble does not trigger false HALTs.

**Check first that the gate can be satisfied at all.** Pass the baseline scores to `calibrate_noise.py`. If it returns `gate_satisfiable: false` — meaning `eps_train ≥ 1 − baseline_train`, so *no* change could ever clear the gate (this includes the saturated case where the baseline is already ≈ 1.0) — the loop **stops and reports the warning** instead of burning N turns. The fix is a bigger or harder golden set, or a higher `k_calib` — not more proposing.

### Subtraction turns

Left to instinct, anyone improving a prompt only ever **adds** rules — the text accumulates caveats until it is bloated and self-contradictory. So on **every 3rd turn** the loop flips the question from "what should we add?" to **"what can we remove?"**: it deletes one rule suspected to be dead weight and re-measures.

- If `train_after ≥ train_before − eps_train` **and** `heldout_after ≥ heldout_before − eps_heldout`, the removal is kept: the prompt got simpler at no measurable cost. This is recorded as `SUB_KEEP`, and the no-progress counter resets.
- Otherwise the rule is restored, `SUB_DROP` is recorded, and the counter increases.

(`SUB_DROP` undoes a *removal*; `DISCARD` undoes an *addition* — they are distinct outcomes.)

### Stop conditions

The loop stops at the first of: **N turns reached** · **no progress for K consecutive turns** (default 3; the counter resets on `MERGE`/`SUB_KEEP`) · **budget exceeded** (per turn or total) · **perfect score** · **HALT**.

A plateau below the score you hoped for is **information, not failure**. It means the instruction text has reached the ceiling of what the fixed model and tools can deliver. To go further, change the model or add a tool — better wording will not get you there. The loop reports the plateau honestly instead of thrashing.

---

## The seven safety rules (S1–S7)

These rules are the reason the skill exists. Each one closes a specific path by which "self-improvement" quietly turns into unmeasured drift. Full statements: [`references/safety-invariants.md`](../../skills/agent-coach/references/safety-invariants.md).

| # | Rule | Prevents | Enforced by |
|---|---|---|---|
| **S1** | Held-out split + **HALT** on overfitting (symmetric `eps_heldout` margin) | Overfit changes getting merged | `split_goldenset.py`, `score_compare.py` |
| **S2** | **Merges decided by code** — never by a model's "it's better" (and the gain must be strictly `>`) | Wishful self-assessment | `score_compare.py` |
| **S3** | **Mechanically verified single change** — a unique `before` match + locality caps | Ambiguous or bundled edits | `verify_change.py` (re-checked by `apply_change.py`) |
| **S4** | **Staging** — the live file is untouched until the human commits | Silent corruption of your real prompt | `apply_change.py` |
| **S5** | **Human-owned case sourcing** + a minimum-size gate (`train ≥ 5`, `heldout ≥ 3`) | A self-graded or too-small exam | Bootstrapper ≠ Grader, human curation, `split_goldenset.py` |
| **S6** | **Failure log** read back by the proposer | Repeating dead ends; a golden set that never evolves | `failure-log.jsonl`, `agents/proposer.md` |
| **S7** | **Noise margins measured from real Runner variance** + the confirm re-run | Noise mistaken for progress | `calibrate_noise.py`, the confirm step |

Remove any one of the seven and the loop can climb a meaningless score. With all seven in place, a `MERGE` actually means something.

---

## Bundled scripts

Code makes every irreversible decision; the models only generate text and grade it. All scripts live under [`skills/agent-coach/scripts/`](../../skills/agent-coach/scripts).

| Step | Script | Role |
|---|---|---|
| pre-flight | `validate_config.py` | Validate the run config: role separation, grader at temperature 0 |
| ④ | `verify_change.py` | Verify the proposal is exactly one localized change (unique `before` + locality caps) |
| ⑤ / ⑩ | `apply_change.py` | Apply to staging; on merge, promote candidate → current (re-running the verify gate) |
| ② / ⑦ | `aggregate_scores.py` | Reduce per-case scores to per-split train/held-out totals (Σ passed / Σ total) |
| ⑧ | `score_compare.py` | The merge gate: MERGE / DISCARD / HALT from a fixed inequality |
| calibration | `calibrate_noise.py` | Derive `eps_train` / `eps_heldout`; report `gate_satisfiable` |
| cold start / split | `split_goldenset.py` | Classify the golden set's state (`op=state`); split & freeze it (`op=split`) |
| resume | `resume.py` | Resume idempotently from the last completed phase |
