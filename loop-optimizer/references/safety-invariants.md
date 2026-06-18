# Safety Invariants S1–S7 — the skill's constitution

These seven invariants are the **reason this skill exists**. The loop's value is
not "an LLM edits a prompt" — it is "an LLM edits a prompt *and you can trust the
result wasn't noise, overfitting, or a self-graded illusion.*" Every invariant
below removes one specific way that "self-improvement" silently degrades into
**evolution without measurement.**

If you simplify the workflow, keep the **mechanisms** intact. Dropping a
mechanism (held-out symmetry, code-enforced merge, Runner-variance calibration,
confirm re-run) does not make the loop lighter — it makes it *lie*. Each entry
states the **invariant**, the **failure it prevents**, and the **mechanism** that
enforces it.

---

## S1 — Held-out split + HALT on overfitting

**Invariant.** The golden set is split into `train` and `heldout`. A change may
merge only if it does not regress held-out beyond the symmetric noise margin
`eps_heldout`. If `train` improves while `heldout` falls by **more than**
`eps_heldout`, the loop **HALTs** the merge (and the run) instead of accepting
the change. The margin is **not zero** — it is `eps_heldout` on both sides.

**Failure it prevents.** Overfitting: a change that boosts the train cases by
memorizing their quirks while quietly destroying generalization. Without a
held-out check you would happily merge changes that look great on the cases you
optimized against and fail on everything else — the classic "98% on train, broken
in production" trap. A *zero* held-out margin would be the opposite failure:
ordinary held-out noise (a single case flipping) would trigger false HALTs and
stall every run.

**Mechanism.** `split_goldenset.py` freezes a `train`/`heldout` partition (most
realistic cases → held-out, so held-out is the hardest, most production-like
guard). `score_compare.py` enforces `heldout_after ≥ heldout_before −
eps_heldout` as a merge precondition and raises **HALT** exactly when `train`
rises but held-out drops past that symmetric margin. `eps_heldout` comes from
real measured noise (S7), not a guess.

---

## S2 — Code-enforced merge (never a model's opinion)

**Invariant.** The decision to MERGE, DISCARD, or HALT is made by **deterministic
code** comparing numbers — never by a model judging "this looks better." No actor
(Proposer, Grader, or the orchestrator) may self-declare an improvement and merge
on that basis.

**Failure it prevents.** Wishful self-assessment. A model asked "did this help?"
will, often enough, say yes — it has just spent effort producing the change and
is primed to like it. Letting the model adjudicate its own work reintroduces
exactly the bias the whole loop is built to remove, and turns a measured process
back into vibes.

**Mechanism.** `score_compare.py` takes raw before/after scores and the
calibrated margins and returns a decision from a fixed inequality (S1/S7). The
orchestration treats that return value as authoritative; the model's role is
strictly to *generate* (Proposer) and *grade individual outputs* (Grader), never
to decide what survives. The merge is a code path, full stop.

---

## S3 — Mechanical single change (unique `before` + locality)

**Invariant.** Each turn applies **exactly one** change, and that change is
verified mechanically: its `before` text must match the current target as a
**unique substring**, and the edit must be **local** (bounded span, bounded
delta). A change that fails either check is rejected before it is ever measured.

**Failure it prevents.** Two distinct failures. (1) **Ambiguous application** — a
non-unique `before` could be applied at the wrong site, corrupting the target. (2)
**Confounded measurement** — a sprawling, multi-part change makes the score delta
un-attributable, so you can never tell which part helped or hurt. Both break the
causal link between "one idea" and "one measured outcome."

**Mechanism.** `verify_change.py` rejects the change unless `before` occurs
exactly once, and enforces locality caps (e.g. `before` span ≤ ~200 tokens,
`after` delta within a percentage cap). One turn = one verified, isolated edit.
The Proposer is contractually limited to a single Change object (`agents/
proposer.md`).

---

## S4 — Staging: the live target is untouched until the human commits

**Invariant.** The loop writes only to **staging** copies inside `loop/<target>/`
(`prompt.current.md`, `prompt.candidate.md`). The **live target file is never
written by the loop** — its bytes are unchanged during the run and after an abort.
The human's `commit` at the end is the **first and only** write to the live file.

**Failure it prevents.** Silent corruption of the user's real, in-use prompt by
an autonomous process. If the loop wrote live, a bad merge, a crash mid-write, or
an overfit change would damage the artifact the user depends on — with no clean
"never mind" path. Semi-autonomy is only safe if it cannot touch production until
a human approves the whole batch.

**Mechanism.** `apply_change.py` writes candidates to staging and promotes
`candidate → current` (still staging) only on MERGE; it never touches the live
path. The live file's byte hash is invariant across the run; resume verifies it.
The end-of-run package (diff + `history.jsonl` + `failure-log.jsonl`) is what the
human reviews before choosing `commit` or `revert` — and only `commit` writes
live.

---

## S5 — Human-owned sourcing + minimum-size gate

**Invariant.** The golden set's **inputs are curated by a human** and its
**rubric is authored by a human.** Seeds may come from logs and AI-drafted
candidates, but raw candidates are **never used as-is** — a human approves,
prunes, and adds missing hard cases. The split is frozen *after* curation. The
run refuses (or warns hard) below `train ≥ 5` and `heldout ≥ 3`.

**Failure it prevents.** A self-graded exam. If the model both wrote the cases
and the rubric, the loop would optimize toward the model's own blind spots and
produce a confident illusion of progress. And a golden set too small to be
statistically meaningful (2 train cases, 1 held-out) makes every score delta
dominated by chance — "improvement" you can't believe.

**Mechanism.** Cold start routes candidate inputs (from logs or the
**Bootstrapper**, which is a *different* model from the Grader) through the Runner
to **expose failures**, then to the human for curation; the human writes the 5–7
yes/no criteria per input. `split_goldenset.py` enforces the train≥5 / held-out≥3
size gate and freezes the split. The human owns *what* is tested and *what counts
as good*; the loop owns only the disciplined search on top.

---

## S6 — Failure-log feedback + Proposer read-back

**Invariant.** Every discarded or halted attempt is recorded one-line in
`failure-log.jsonl` (the "wrong-answer notebook"), and the **Proposer reads it
before proposing** so it does not repeat known dead ends. Each failure entry also
carries a `candidate_input` — a seed for a *new golden-set case* — feeding the set
back into the human's between-runs curation.

**Failure it prevents.** Two kinds of wasted motion. (1) **Repeating losing
proposals** — without memory, the search re-proposes "force formal tone," "infer
missing context," etc., turn after turn, burning budget. (2) **A stagnant golden
set** — failures the target exhibited (e.g. it overfit by hallucinating) reveal
exactly the cases the set is missing; discarding that signal wastes the most
valuable curation lead you have.

**Mechanism.** On DISCARD/HALT the orchestration appends a `failure-log.jsonl`
line with `before`/`after`/`rationale`/`reason` and a `candidate_input`. The
Proposer is instructed to **read `failure-log.jsonl` first** (`agents/
proposer.md`) and avoid restating logged failures. Between runs, the human curates
`candidate_input`s into the next golden-set `version` (S5), so the set evolves
toward the target's real weaknesses.

---

## S7 — Noise margin from Runner-output variance + confirm re-run/re-grade

**Invariant.** The Grader runs at **temperature 0 and is version-pinned**, so it
contributes no variance. The merge margins `eps_train` / `eps_heldout` are
**calibrated from the Runner's run-to-run output variance**. A change merges only
when `train_after ≥ train_before + eps_train` **AND** `heldout_after ≥
heldout_before − eps_heldout` (symmetric) **AND** the gain still holds on a
**confirm re-run + re-grade** of the full set.

**Failure it prevents.** Mistaking luck for progress. At realistic temperature the
target's output wobbles between runs, so a +1 on train can be pure noise. Merging
inside the noise band ratchets randomness into the prompt — the score drifts up
without the prompt actually getting better, and worse changes get locked in. It
also prevents the inverse: treating ordinary noise on held-out as a real
regression.

**Mechanism.** `calibrate_noise.py` re-runs the **Runner** on fixed inputs
`k_calib` times (default 5), grades each, and derives the score spread per split
into `eps_train` / `eps_heldout`. Crucially the *Runner* is the variance source —
re-grading identical text with a temp-0 Grader has zero variance and would be a
no-op, which is why **confirmation must re-RUN the target** (step ⑨), not just
re-grade. Step ⑨ re-runs **both** the candidate AND the current (baseline)
prompt: the confirm gate compares the candidate's fresh after-score against a
**freshly re-measured baseline** (`train_b2` / `held_b2`), never against the
first-call baseline. Reusing the first baseline would make the two gate checks
share a term and so positively correlate — a baseline drawn low would clear both
at once, roughly halving confirm's power to reject luck (the H4 finding). A second
*independent* measurement is the entire point of confirming. The confirm is
**code-enforced, not advisory**: `score_compare.py` takes the confirm re-run's
after-scores (`train_a2` / `held_a2`) **and requires the re-measured baseline
(`train_b2` / `held_b2`)** — omitting the baseline is a hard error, not a silent
reuse of the stale one — and returns `confirmed:true` only when they still clear
the two-sided inequality; `apply_change.py` op=promote **refuses to promote
without `confirmed:true`** — so the safeguard cannot be skipped (this is what
makes S7 real rather than a prose promise the orchestrator might forget). A kept
subtraction (`SUB_KEEP`) is a promote too, so it carries the same confirm
requirement. The inequality itself
is evaluated with a small float tolerance (`1e-9`) so a score exactly on a
threshold can't be flipped by IEEE-754 dust into a false discard or a false HALT.

---

## How the seven fit together

| Risk if absent | Invariant | Enforced by |
|---|---|---|
| Overfit changes merged | S1 | `split_goldenset.py`, `score_compare.py` |
| Model self-declares "better" | S2 | `score_compare.py` (code decides) |
| Ambiguous / confounded edits | S3 | `verify_change.py` |
| Live prompt corrupted mid-run | S4 | `apply_change.py` (staging only) |
| Self-graded / too-small exam | S5 | Bootstrapper≠Grader, human curation, size gate |
| Repeated dead ends, stale set | S6 | `failure-log.jsonl`, Proposer read-back |
| Noise mistaken for progress | S7 | `calibrate_noise.py`, `score_compare.py` confirm gate, `apply_change.py` promote (`confirmed:true`) |

Remove any one and the loop can climb a meaningless score. Keep all seven and a
MERGE means something: a single, isolated, code-verified change that beat
measured noise on train, held generalization on held-out, survived a confirming
re-run, and never touched the live file until a human said so.

---

## Implementation hardening (2026-06)

These refine *how* the invariants are enforced; they do not change what the seven
mean.

- **S7 — eps floor + satisfiability (was the biggest gap).** `calibrate_noise.py`
  floors `eps` at a small positive `min_eps` (default 0.02), so a calibrated `0.0`
  (identical samples) can never let a `+0.0` tie merge. It also accepts the current
  `baseline` and reports `gate_satisfiable: false` when `eps_train ≥ 1 −
  baseline_train` — i.e. *no* change could ever clear the gate. The orchestrator
  must STOP and report this (enlarge / harden the golden set, raise `k_calib`)
  rather than burn N turns. The **saturated** golden set (baseline ≈ 1.0) is the
  same condition and surfaces the same way — one mechanism, no change to the merge
  contract. (In `per_split`, only **train**'s `gate_unsatisfiable` is authoritative
  — it drives the top-level `gate_satisfiable`; every other split is a *guard*, so
  its own `gate_unsatisfiable` is advisory and never blocks a run on its own. Don't
  let a harmless held-out flag train you to ignore the dangerous train one.)
- **S2 — strict gain.** `score_compare.py` MERGE additionally requires
  `train_after > train_before` (a true `+0.0` tie never merges, even if a caller
  hand-passes `eps_train = 0`). Negative eps is clamped to 0.
- **HALT scope (deliberate).** HALT keys on a *rising* train (the overfit
  trajectory). A saturated-train overfit that craters held-out cannot raise train,
  so it is a blocked **DISCARD**, not a terminal HALT — and the `gate_satisfiable`
  check above catches that saturated case earlier and louder. HALT stays the
  trajectory detector; calibration owns saturation.
- **S3 — locality is unbypassable + tightened.** `apply_change.py` now re-runs the
  *full* `verify_change` gate (uniqueness AND locality) and refuses on failure, so
  a rejected change can never be staged even if `verify` was skipped. The locality
  "absolute floor" that rescues a short target is **growth-only** and capped in
  both chars (≤60) and **tokens** (≤10, style-independent), so it admits one short
  clause but not a multi-rule pile. A `kind="subtraction"` removal gets the relaxed
  ratio only when it is a **pure deletion** (introduces no new token), so a
  "subtraction" can't swap in new rules to dodge the edit cap.
- **S5 — config-level separation.** `validate_config.py` (pre-flight) makes the
  actor-separation invariant checkable, not just nominal: it errors on
  `proposer.model == grader.model`, `bootstrapper.model == grader.model` (compared
  case/whitespace-insensitively), and a non-zero grader temperature; it warns on a
  zero-variance Runner (`runner.temperature == 0`) and a small `k_calib`.
