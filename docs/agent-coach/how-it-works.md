# How agent-coach works — design & safety

> The mechanics and the reasoning behind agent-coach's measured loop: why it exists, what makes it different, one turn of the loop, the merge gate, the seven safety invariants, and the bundled scripts.

← Back to the [repository README](../../README.md) · manual: [golden set](./golden-set.md) · [run-config](./run-config.md) · [running](./running.md)

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

The single most important structural rule: **the model that proposes a change is not the model that grades it, and neither is the model that runs the target.** Each actor is a separate Claude Code subagent with its own prompt under [`skills/agent-coach/agents/`](../../skills/agent-coach/agents), so each starts from a clean context and the separation is *real*, not nominal.

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

[`score_compare.py`](../../skills/agent-coach/scripts/score_compare.py) — not a model — makes the decision. A change **MERGES only when all of these hold:**

```
train_after   >  train_before                      (a strictly positive gain — a +0.0 tie never merges)
train_after   ≥  train_before   + eps_train        (the gain beats measurement noise on train)
heldout_after ≥  heldout_before − eps_heldout       (no real regression on held-out)
AND the gain still holds after the confirm re-run (⑨)
```

Otherwise:

- If `train` rises but `heldout` falls by **more than** `eps_heldout` → **HALT** (overfitting: the change memorized train and broke generalization). HALT is terminal.
- Otherwise → **DISCARD** (no real gain; the addition is reverted).

The margins `eps_train` / `eps_heldout` are **measurement noise**, calibrated by [`calibrate_noise.py`](../../skills/agent-coach/scripts/calibrate_noise.py): it re-runs the Runner on fixed inputs `k_calib` times (≥5 recommended), grades each, and derives the score spread per split — floored at a small positive `min_eps` so a `+0.0` tie can never look like progress. The held-out margin is **symmetric** (`eps_heldout` on both the merge and HALT side), so ordinary held-out noise does not trigger false HALTs.

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

These are the reason the skill exists. Each removes one specific way "self-improvement" silently degrades into evolution-without-measurement. Full statements: [`references/safety-invariants.md`](../../skills/agent-coach/references/safety-invariants.md).

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

## Bundled scripts

Code makes every irreversible decision; the model only generates and grades. All scripts are under [`skills/agent-coach/scripts/`](../../skills/agent-coach/scripts).

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
