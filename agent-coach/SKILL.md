---
name: agent-coach
description: >-
  Iteratively improve a prompt, skill, or instruction file via a measured
  self-improvement loop. It runs the target against a human-curated golden set
  (train + held-out), grades each output by a yes/no rubric, proposes one change
  per turn, and — via deterministic code, not model judgment — merges ONLY when
  the gain beats train noise without regressing held-out beyond a symmetric
  margin, halting on overfitting. Use it whenever the user wants to optimize,
  tune, harden, or cut the failure rate of a prompt/skill against example cases;
  set up an eval-/golden-set-driven improvement loop; A/B-measure prompt changes
  with evidence; or "make this prompt better" measurably, not by vibes — even if
  they never say "loop". Especially trigger on golden sets, evals, rubrics,
  prompt regression, held-out test cases, overfitting a prompt, or "measure
  before you change." Do NOT use for a one-off single edit, for optimizing
  application/source code (use code tools), or for code-shipping like opening
  PRs or fixing CI.
compatibility: Requires python3 >=3.8 (standard library only) for scripts/; requires subagents (Claude Code) to keep the four actors isolated.
---

# Agent Coach

Improve a target prompt/skill/instruction file the way a good coach trains an
athlete: **measure → change ONE thing → measure again → keep it only if the
score really went up.** The governing rule is **"no evolution without
measurement"** — never change the target based on a hunch; change it based on a
score, and let *deterministic code* (not a model's opinion) decide whether the
change survives.

This skill is only as smart as its **golden set** — the fixed exam it grades
against. Most of the leverage lives in a representative, discriminating golden
set, which the **human owns**. Your job is to run a disciplined loop on top of
it without ever fooling yourself that a noisy or overfit change is real
progress.

## When this applies

Use it when a user points you at a prompt/skill file and wants it measurably
better against examples (e.g. "tune `./prompts/summarizer.md` so it scores
better on these cases, but don't overfit, and measure before you change").
Do **not** use it for one-off single edits, source-code optimization, or PR/CI
automation.

## Inputs

1. **Target** — the live prompt/skill/instruction file to improve (e.g.
   `./agents/dev-agent.md`).
2. **Golden set** — `golden-set.json`: human-curated inputs + a yes/no rubric
   per input + a frozen `train`/`heldout` split, plus evolution metadata. Full
   schema: **`references/data-formats.md`**. If the user has no golden set, build
   one first (see "Cold start" below) — never skip it.
3. **Run config** — `run-config.json`: which model/temperature runs the target
   (so measurement matches real use), the grader/proposer models, loop limits,
   budget caps, and `k_calib`. Schema in `references/data-formats.md`.

All work happens inside `loop/<target>/`. **The live target file is never
written until the human commits at the end** (see "Staging", S4).

**Pre-flight (before turn 1):** validate the run config with
`scripts/validate_config.py` and STOP on any error — it catches the separation
violations that quietly poison a run (proposer = grader, bootstrapper = grader)
and a non-zero grader temperature. Every `scripts/*.py` reads its JSON payload on
**stdin** (or a file-path arg), never as an inline argv string:
`printf '%s' '<json>' | python3 scripts/<tool>.py`. Verify the deterministic core
once with `python3 scripts/tests/run.py` before trusting a run.

**Golden-set entry is deterministic too.** Classify the set with
`split_goldenset.py` `op=state` — `missing`/`empty` → cold start; `unfrozen` → run
`op=split`; `mutated` → restore or re-split; `ready` → loop. The entry branch is
control flow, so code decides it (S2), not the model eyeballing the path with `ls`.

## The four actors — keep them separate

The single most important structural rule: **the model that proposes a change is
not the model that grades it, and neither is the model that runs the target.**
Self-grading inflates scores ("close enough, call it a pass"); a player must not
referee their own game. Each actor is a separate subagent with its own prompt in
`agents/`:

| Actor | Job | Read its prompt |
|---|---|---|
| **Runner** | Execute the target on a golden input → produce output | `agents/runner.md` — isolated, no write/network/shell, reads golden input only. This isolation is a security boundary (an arbitrary target prompt must not hijack the host). Matches the user's real runtime. |
| **Grader** | Score an output against the rubric → per-item yes/no | `agents/grader.md` — temperature 0, version pinned. |
| **Proposer** | Propose exactly ONE change | `agents/proposer.md` — reads the failure log to avoid repeats. |
| **Bootstrapper** | Draft cold-start input candidates | `agents/bootstrapper.md` — must differ from the Grader. |

Spawn these as subagents so each starts from a clean context and the separation
is real, not nominal.

## The optimization loop (one turn)

Run up to **N** turns (default 10, from `run-config.json`). Each turn changes at
most one thing and is gated by code. A turn:

```
① Run      Runner(current target, ALL train+heldout inputs) → outputs
           (the inputs are independent — fan the set out in PARALLEL)
② Grade    Grader(per output, rubric) → per-case Scores; attach each Score's
           `split` (train/heldout) by an id→split lookup against the frozen
           golden set, then aggregate_scores.py → train_before, heldout_before
③ Propose  Proposer → one change {target_id, before, after, rationale, kind}
④ Verify   scripts/verify_change.py: `before` matches UNIQUELY + change is local
           → reject the turn if not (this enforces "exactly one localized change")
⑤ Apply    scripts/apply_change.py: write to STAGING (prompt.candidate.md) only —
           the live target is untouched
⑥ Re-run   Runner(candidate, ALL inputs) → outputs   (parallel, as in ①)
⑦ Re-grade Grader → per-case Scores; attach `split` (id→split) as in ②;
           aggregate_scores.py → train_after, heldout_after
⑧ Compare  scripts/score_compare.py (CODE decides): MERGE / DISCARD / HALT
           (subtraction turns: SUB_KEEP / SUB_DROP). A MERGE/SUB_KEEP here is
           PROVISIONAL (confirm_required:true) until ⑨ confirms it.
⑨ Confirm  if MERGE or SUB_KEEP: re-run + re-grade the full set ONCE more — BOTH
           the candidate AND the current (baseline) prompt — then call
           score_compare AGAIN passing the confirm after-scores (train_a2/held_a2)
           AND the re-measured baseline (train_b2/held_b2). CODE re-checks the same
           inequalities against the FRESH baseline; only a confirmed:true result
           may promote. If the gain/parity evaporated → DISCARD/SUB_DROP.
⑩ Record   MERGE / SUB_KEEP → apply_change.py op=promote (confirmed:true) →
                     resume.py op=promote_done → record_decision + history.jsonl
           DISCARD/SUB_DROP→ failure-log.jsonl (one line, + candidate_input) — keep the live file
           HALT   → stop + warn + failure-log.jsonl (result: halted)
```

**Attach `split` before aggregating (②/⑦).** The Grader emits a Score with **no
`split` field** — deliberately: it must stay blind to whether an output is a
train or held-out case, or it could grade toward a wanted result. So the
orchestrator joins `split` on just before calling `aggregate_scores.py`, by
looking each `case_id` up in the frozen golden set (`id → split`, the single
frozen source of truth for the run). `aggregate_scores.py` **requires** `split`
on every Score and errors loudly if it is missing, so a forgotten join stops turn
1 rather than silently mixing the splits (which would quietly defeat the held-out
overfit guard, S1).

**Carry-over (skip ①② when the prompt is unchanged):** ①② re-measure the current
prompt at the top of every turn, but you often already have a fresh score for that
exact text — after a DISCARD the current prompt is byte-identical to last turn's,
and after a MERGE/SUB_KEEP the confirm re-run (⑨) just measured the new current.
Cache it with `resume.py op=record_scores` (keyed by `current_prompt_hash`); at ①,
if `state.last_scored_prompt_hash == current_prompt_hash`, reuse `last_train` /
`last_heldout` as the before-scores and skip the re-run + re-grade. The hash guard
keeps it safe (the text is provably identical to what was measured) and the eps
margin already covers run-to-run noise — this saves ~16 model calls on every
non-MERGE turn. It is a pure cost optimization: the gate inputs and decisions are
unchanged.

**Why ⑨ (confirm by re-running, not just re-grading):** the Grader runs at
temperature 0, so re-grading the *same text* gives the identical score (zero
variance) — a no-op. Real noise comes from the **Runner** producing different
outputs across runs. So you confirm a merge by running the target again and
re-grading the fresh output. If the gain evaporates, it was noise. This is
**code-enforced, not advisory**: `score_compare.py` only returns `confirmed:true`
when you pass the confirm re-run's scores and they still clear the gate, and
`apply_change.py` op=promote **refuses to promote without `confirmed:true`** — so
a noise change can't slip in by skipping ⑨ (S2/S7). The same applies to a
`SUB_KEEP`: a kept removal is a live change, so it must be confirmed before it is
promoted.

**Re-measure the baseline at confirm, not just the candidate (H4).** Confirm must
re-run *both* the candidate and the current prompt, and pass the fresh baseline as
`train_b2`/`held_b2` alongside `train_a2`/`held_a2`. The reason is statistical:
the first gate asks `train_a1 ≥ train_b + eps`; if confirm reused that same
`train_b` it would ask `train_a2 ≥ train_b + eps` — two checks sharing one term,
so a baseline that happened to be measured *low* sails through both at once. That
correlation roughly **halves** confirm's power to reject luck (about double the
false-merge rate, held-out guard included). A second, *independent* baseline
measurement is the whole point of confirming. `score_compare.py` **requires**
`train_b2`/`held_b2` whenever you pass confirm after-scores — omitting them is a
hard error, not a silent reuse of the stale baseline. This is the one before-score
you must NOT serve from the carry-over cache below: it has to be freshly measured.

### The merge gate (the heart — code, not the model)

`score_compare.py` accepts `{train_b, train_a, held_b, held_a, eps_train,
eps_heldout, mode}` and returns a decision. A change **MERGES only when all hold**:

```
train_after   ≥ train_before   + eps_train       (real gain on train, beyond noise)
heldout_after ≥ heldout_before − eps_heldout      (no real regression on held-out)
and the gain still holds after the confirm re-run (⑨)
```

- If `train` rises but `heldout` falls by **more than** `eps_heldout` → **HALT**
  (overfitting: the change memorized train and broke generalization).
- Otherwise → **DISCARD**.

HALT keys on a **real train gain** (`≥ eps_train`, the same `train_gain_ok` MERGE
uses) paired with a real held-out drop — the unambiguous overfit trajectory. A
*sub-eps* train wiggle that craters held-out is a **DISCARD**, not a terminal HALT:
nothing real generalized worse, the change simply didn't earn a merge (F-08). If
the baseline train is already saturated (≈1.0), an overfit that craters held-out
can't raise train, so it also lands as a DISCARD — caught earlier and more loudly
by the calibration-time `gate_satisfiable` check (above), so the loop never burns
turns on it. Reserve terminal HALT for a demonstrated overfit; let calibration
handle saturation.

The margins `eps_train` / `eps_heldout` are **measurement noise**, calibrated by
`scripts/calibrate_noise.py`: it re-runs the Runner on fixed inputs `k_calib`
times (use **≥5**), grades each, and derives the score spread per split (floored
at a small positive `min_eps` so a `+0.0` tie can never look like progress). A
change inside the noise band is not progress — it's luck. Do **not** let a model
decide "it looks better"; the inequality decides. (This is invariant **S2** / **S7**.)

**Check the gate is satisfiable first.** Pass the current baseline scores to
`calibrate_noise.py` (`"baseline": {"train": …, "heldout": …}`). If it returns
`gate_satisfiable: false` — `eps_train ≥ 1 − baseline_train`, so *no* change
could ever clear the gate (the saturated case, where the baseline is already
near 1.0, is the same condition) — **STOP and surface the warning** instead of
burning N turns. The fix is a bigger / harder golden set or a higher `k_calib`,
not more proposing. This is the calibration-time staleness signal (it also
subsumes "the golden set is too easy").

The held-out margin is **symmetric** (`eps_heldout` on both merge and HALT), not
a zero margin — otherwise ordinary held-out noise would trigger false HALTs.

All gate inequalities carry a tiny float tolerance (`1e-9`) so a score landing
*exactly* on a threshold resolves inclusively instead of on IEEE-754 dust (the
classic `0.1 + 0.2 ≠ 0.3`). Without it a real gain on the merge line is silently
discarded and — far worse — an ordinary held-out dip on the margin flips a safe
run into a *terminal* false HALT.

### Subtraction (every 3rd turn)

People only ever *add* rules. Every third turn, instead of "what to add," try
**"what to remove"** — drop one rule and re-measure. Compare in subtraction mode:
keep the removal iff `train_after ≥ train_before − eps_train AND heldout_after ≥
heldout_before − eps_heldout` → record `decision: SUB_KEEP` and reset the
no-progress counter. If it falls short, **restore the rule**, record `decision:
SUB_DROP`, and increment the counter. (`SUB_DROP` undoes a *removal*; `DISCARD`
undoes an *addition* — they are different.) A subtraction turn spends the same
"one change per turn" budget.

**A `SUB_KEEP` is a promote decision — confirm it (⑨) and promote the pruned
candidate to current (⑩) exactly like a MERGE.** This is easy to forget because
"keeping a removal" sounds passive, but the pruned text lives only in staging
until you promote it. Skip the promote and the removed rule silently stays live,
which makes pruning a no-op — and pruning is the *only* force resisting prompt
bloat, so a dead pruner means the target only ever grows.

### Stop conditions

Stop at the first of, evaluated in this **priority order** by `resume.py
op=should_stop`: **HALT** (terminal overfit) → **perfect score** → **N turns
reached** → **no-progress for K turns** (default K=3; reset on MERGE or SUB_KEEP,
+1 otherwise) → **total budget exceeded** (`max_usd_total`, the code-enforced
cap). (HALT is terminal, so it does not update the no-progress counter.)

Call `should_stop` with **every** cap each turn. Its arg names are *flat* but the
config *nests* them, so map each one explicitly:

```
printf '%s' '{"op":"should_stop","state_path":"loop/<target>/state.json","n_turns":10,"no_progress_k":3,"max_usd_total":20.0,"perfect":false}' | python3 scripts/resume.py
```

(`n_turns` ← config `loop.n_turns`, `no_progress_k` ← `loop.no_progress_k`,
`max_usd_total` ← `budget.max_usd_total`; `perfect` you compute — see below.)
**A cap you don't pass is not enforced:** `should_stop` returns `stop:false` for
any limit it wasn't given, so omitting `n_turns` or `max_usd_total` silently lets
the loop run unbounded. The whole point of "code-enforced stop" is lost if the
arg is missing — pass them every call.

**"Perfect" means train AND held-out are BOTH at the ceiling** (every criterion
passes on both splits) — never train alone. Otherwise an overfit that maxes train
while held-out lags would stop early, mislabeled "done", instead of being caught
as the regression it is.

A plateau below the user's hoped-for score is **information, not failure**: it
means the instruction text has reached the ceiling of what the fixed model and
tools allow. Report it; don't thrash.

## Cold start — build the golden set first

**Detect this case deterministically:** `split_goldenset.py` `op=state` returns
`missing` (no file) or `empty` (no active cases) → enter cold start; don't infer
it by eyeballing the path. If there is no golden set, do **not** invent one and
grade against it — that is a self-graded exam. Instead:

1. **Seed**: seed inputs from logs if they exist **and/or** have the
   **Bootstrapper** draft input *candidates*. Run the Bootstrapper even when logs
   exist if the logs are easy / happy-path — a flattering set finds nothing.
   Never use raw logs or raw candidates as-is.
2. **Expose failure**: run the target once (Runner) on the candidates to surface
   where it actually fails.
3. **Human curates**: the user approves/prunes inputs and adds missing hard
   cases. The user owns input selection, not just the rubric (this blocks
   correlated blind spots).
4. **Human rubric**: the user writes the yes/no criteria (5–7 per input).
5. **Split**: `scripts/split_goldenset.py` splits train/held-out *after*
   curation, putting the **most realistic** items in held-out, and freezes the
   split (hash).
6. **Size gate**: refuse/​warn if `train < 5` or `heldout < 3`.

**Steps 3–4 win or lose most of the leverage.** Consult
**`references/golden-set-guide.md`** (a tight checklist — choosing cases that can
*fail*, and writing crisp, guard, and orthogonal yes/no criteria) while helping the
human curate inputs and author the rubric.

## Human batch approval (end of run)

This loop is semi-autonomous: it does **not** ask the human to approve every
change. It runs N turns, then presents a batch:

- the **diff** (start vs current candidate),
- `history.jsonl` (train/held-out/margin trend per turn),
- `failure-log.jsonl` (what was tried and discarded),

and the human decides **commit** (the first and only write to the live target) or
**revert**. The final end-to-end QA — actually using the result — stays with the
human.

## Golden set is frozen *within* a run, versioned *between* runs

While the loop runs, the golden set and split are **frozen**: `split_goldenset`'s
`split_hash` is re-checked every turn, and any mid-run change is an error. This
is what makes before/after scores comparable. **Between** runs, the human grows
the golden set (adding failure-derived cases via `candidate_input` from the
failure log → a new `version`). Scores are comparable only *within* a version;
record `golden_set_version` on every `history.jsonl` row so versions are never
compared directly.

Also record `grader_version_id` on each row (F-25): scores compare only while the
*ruler* is fixed too. If the grader model or grading prompt changes between runs,
a different `grader_version_id` flags that a generation-to-generation trend may
reflect grader drift, not target change — optionally re-grade one fixed reference
output between runs as a drift canary. And on a version bump, **archive** the
prior version's `history.jsonl` / `failure-log.jsonl` to `archive/<version>/`
(F-21) so logs don't accrete across versions and each version's trail stays
self-contained.

**Record-only cross-family drift WARN (advisory — not a gate, not a safety net).**
A single grader is one ruler with one set of blind spots. The decorrelated
sanity check for that is the **dual-judge cross-family re-check** (grade the same
outputs with a second judge from a different model family and compare) — a
**manual** action the human runs, logged in
`references/baselines/dual-judge-ledger.jsonl`. To make a stale check visible,
`scripts/check_cross_validation.py` reads that ledger and emits a **non-blocking
WARN** when the current `grader_version_id` / `golden_set_version` / `split_hash`
differ from the last recorded check (or none exists). It is purely a surfacing
aid at the moment you are about to **trust a dogfood verdict**: run it then, and
if it warns, know the cross-family check has not covered this ruler/set/split.
Be clear about what it is **not**: it does **not** block, does **not** feed the
merge gate (S2), and is **not** a safety net — it cannot tell you the grader is
*wrong*, only that the cross-check is *stale*. Closing the loop still requires the
human to run the cross-family re-check (the dual-judge tripwire). A *blocking*
gate is intentionally **deferred** until a drift detector is validated on a
de-saturated diagnostic set; building one against today's near-ceiling set would
be premature (see `.omc/specs/loop-optimizer-dualjudge-diagnostic.md`).

## State layout — `loop/<target>/`

Everything is human-readable and resumable:

- `golden-set.json` — user-provided (curated inputs + rubric + frozen split + evolution metadata)
- `prompt.current.md` / `prompt.candidate.md` — staging copies (never the live file)
- `history.jsonl` — per-turn score trail
- `failure-log.jsonl` — discarded/halted attempts + evolution candidates
- `state.json` — turn state machine for idempotent resume (`scripts/resume.py`)

## Safety invariants — do not violate (S1–S7)

These are the reason the skill exists; read **`references/safety-invariants.md`**
for the full statements. In brief: **S1** held-out + HALT (overfit guard, with
`eps_heldout` margin) · **S2** code-enforced merge (never a model's "it's
better") · **S3** mechanical single change (unique `before` + locality) · **S4**
staging (live file untouched until commit) · **S5** human-owned sourcing + size
gate · **S6** failure-log feedback into the golden set + proposer read-back ·
**S7** noise margin from Runner-output variance + confirm re-run/re-grade.

## Bundled scripts (deterministic, stdlib only)

Code makes every irreversible decision; the model only generates and grades. Use:

| Step | Script |
|---|---|
| pre-flight: validate run-config (actor separation, grader temp 0) | `scripts/validate_config.py` |
| ④ verify one localized change | `scripts/verify_change.py` |
| ⑤/⑩ apply to staging, promote on MERGE/SUB_KEEP (promote requires `confirmed:true`) | `scripts/apply_change.py` |
| ②/⑦ reduce per-case Scores → per-split train/heldout (Σpassed/Σtotal) | `scripts/aggregate_scores.py` |
| ⑧/⑨ merge/HALT/discard decision + confirm gate | `scripts/score_compare.py` |
| calibrate `eps_train`/`eps_heldout` | `scripts/calibrate_noise.py` |
| classify golden-set state (deterministic cold-start entry) | `scripts/split_goldenset.py` (`op=state`) |
| split + freeze golden set | `scripts/split_goldenset.py` |
| resume after interruption (idempotent) | `scripts/resume.py` |

Run `python3 -m pytest scripts/tests/` (or `python3 scripts/tests/run.py`) to
verify the deterministic core before trusting a run.

## Cost

A turn costs roughly `Runner(current + candidate-verify + confirm) × set size +
Grader (same) + Proposer 1` ≈ ~65 model calls on a promote turn for |train|=5,
|held|=3, plus `k_calib` calibration runs at cold start. The confirm re-run (⑨) is
incurred only on a promote turn — MERGE *or* SUB_KEEP — and it re-runs **both** the
candidate and the current prompt (the H4 re-measured baseline), so it is the
heaviest part of such a turn; a plain DISCARD/SUB_DROP/HALT turn skips confirm
entirely, so it is closer to ~33 calls. Budget is a first-class constraint:
`budget.max_usd_total` is the **code-enforced** stop (`resume.py op=should_stop`).
`max_usd_per_turn`, if set, is an **advisory pre-turn estimate** for the
orchestrator (size-of-set × calls), not a hard mid-turn stop — the loop checks
budget only at turn boundaries. The user sizes cost via N and golden-set size.

**Cost scales with the golden set** (F-17/F-19): a turn is ~6 calls *per case*
(run + grade, on current + candidate + confirm), so a 50–200-case set costs
6–24× the |train|=5/|held|=3 figures above, and cold-start calibration adds
`k_calib × set-size` Runner runs. For a large set, estimate cost before turn 1 and
consider calibrating on a representative subset. **Per-call cost also creeps up
over a campaign** (F-22/F-23): each kept change lengthens the target, so later
turns send more tokens per call. This is gain-gated and self-limiting — additions
that don't beat noise are discarded and every 3rd turn prunes — *but only if
`SUB_KEEP` actually promotes* (⑩); the dollar cap bounds the worst case either way.

## Data formats & deeper reference

- **`references/data-formats.md`** — full JSON schemas: `golden-set.json`,
  `run-config.json`, `history.jsonl`, `failure-log.jsonl`, `state.json`, and the
  internal Change/Score contracts. Read this before writing any script call.
- **`references/safety-invariants.md`** — S1–S7 in full.
- **`references/loop-concepts.md`** — the principles behind the loop (why measure
  first, why one change, why proposer ≠ grader, failure log, subtraction, human
  as coach).
- **`references/golden-set-guide.md`** — agent checklist for building a
  *discriminating* golden set (case selection + rubric craft); consult at cold start
  and when evolving the set.
