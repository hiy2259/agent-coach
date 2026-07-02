# Building a good golden set

> The golden set is the **moat**. The loop is only as smart as this exam: every
> `MERGE`, `HALT`, and `DISCARD` is computed from how your cases score. Most of the
> leverage in the whole skill lives here, and it is the one thing **you own** — the
> model never writes both the cases and the rubric, or it would be grading its own
> homework. A flattering set produces confident garbage; a *discriminating* set is
> what makes "better" mean something.

This page is the craft: how to choose cases, how to write rubric criteria that
actually measure quality, how to split, how to grow the set, and the anti-patterns
that quietly defeat the whole loop. For the exact JSON shapes see
[`../agent-coach/references/data-formats.md`](../agent-coach/references/data-formats.md);
for the safety rationale see
[`../agent-coach/references/safety-invariants.md`](../agent-coach/references/safety-invariants.md).

---

## 1. The one idea: discriminate, don't flatter

A case earns its place only if it can tell a **better** target from a **worse** one
— which means it must be able to **fail**. A case the target already aces on every
version carries zero signal; it just pads the score.

The failure mode to fear is **saturation**: if (almost) every case passes, the
baseline sits near `1.0`, there is no gradient to climb, and the merge gate can
*certify nothing* — no change can clear "beat the baseline by more than noise" when
there is no room above the baseline. The loop detects this before turn 1
(`calibrate_noise.py` returns `gate_satisfiable: false` / a `SATURATED` warning) and
**refuses to run** rather than burn turns. That refusal is the set telling you it
cannot measure progress.

> **Real example.** In this project's own dogfood, the first golden set scored the
> target `1.0` on both splits. The loop correctly halted before turn 1 with a
> `SATURATED` warning. Only after we added a criterion the target actually *failed*
> (restoring headroom) could the loop measure — and merge — a real improvement.

**Aim for a baseline that leaves room.** A good starting set scores the *current*
target somewhere clearly below the ceiling, so a real gain is visible above the
measurement noise.

---

## 2. Choosing the cases (the inputs)

The inputs are the situations you put the target through. Pick them to **probe
where the target is weak**, across the breadth of its real job:

- **Representative of real production**, not toy / happy-path. If your set only
  contains the easy inputs, a passing score means nothing about real use.
- **Aim at the failure modes that matter:**
  - *Adversarial / underspecified* — ambiguous, self-contradictory, or
    missing-context inputs the target tends to mishandle.
  - *Hallucination bait* — inputs where the tempting answer is to **invent** a
    detail, cause, or fact that isn't present, so a good target must say "not
    specified" instead of fabricating.
  - *Realistic hard cases* — the inputs the target meets in production but handles
    inconsistently. These are the most valuable, and they belong in **held-out**
    (see §4).
  - *Spread across the job* — probe the target's breadth, not one narrow skill.
- **A few genuinely probing cases beat a pile of near-duplicates.** Variety of
  failure mode > volume.

### You own the inputs, not just the rubric

The load-bearing guard is that **you supply your own real cases** (invariant S5).
The skill can *draft* candidate inputs for you at cold start — the **Bootstrapper**
actor exists for exactly this, and it deliberately aims at weaknesses — but it
drafts **candidates only**. You approve, prune, and add the hard cases it missed.
Rubber-stamping an AI-drafted set is the weak version of this guard: the model and
the case-writer share blind spots, and the loop ends up optimizing toward a
self-consistent illusion. (See
[`../agent-coach/agents/bootstrapper.md`](../agent-coach/agents/bootstrapper.md).)

---

## 3. Writing good rubric criteria — the craft most people get wrong

Each case gets **5–7 yes/no criteria**. This is the highest-leverage and least
obvious skill in the whole exercise, because the criteria *are* your definition of
"good." Get them sharp and the loop measures real quality; get them vague or
tangled and it measures noise.

**One criterion = one independently-checkable thing.** Don't bundle. "Did it find
the bug **and** fix it **and** explain it?" is three questions wearing a trench
coat — split it into three, each scored on its own. The grader judges each
criterion in isolation, and that granularity is exactly what lets the loop detect a
small, real movement.

**Criteria are the *criteria* for a good answer, not the answer itself.** Write
"Did it propose a parameter-binding (prepared-statement) fix?" — not "Did it output
exactly *this* code?" You are defining what a good response must contain, not
pinning one golden string.

**Include negative / guard criteria — the "didn't fabricate" axis.** Some of your
most valuable criteria are checks for what the target must **avoid**: "Did it AVOID
inventing a cause not present in the report?", "Did it AVOID asserting a severity
when the input doesn't support one?" These are load-bearing — they are what catch
the *overfit-by-hallucination* trajectory the held-out guard exists to stop. For a
negative criterion, `passed = true` means the output **avoided** the bad behavior;
make sure the polarity is unmistakable.

**Make criteria orthogonal.** Two specific traps, both real:

- *Don't double-count one dimension.* Two criteria that test the same thing inflate
  its weight and crowd out everything else.
- *Don't add a criterion that **conflicts** with another.* A criterion that fights
  an existing one caps that case below 100% **forever** and poisons the signal.

  > **Real example.** On an ambiguous "is this even a bug?" case, our rubric already
  > rewarded *not* inventing a severity ("AVOID assigning a severity when it isn't
  > knowable"). A proposed *format* criterion — "must label severity as one of
  > `P0`–`P3`" — directly contradicts it: the correct answer (mark it undetermined)
  > can satisfy only one. We dropped the conflicting criterion and used an
  > **orthogonal** one instead (require a `Confidence:` line — a dimension no other
  > criterion touched). Orthogonal criteria add signal; conflicting ones destroy it.

**Make each criterion unambiguous for a temperature-0 grader.** The Grader runs at
temperature 0 and must resolve every borderline the *same way every time* — that
zero-variance grading is what the noise margin depends on. A vague criterion ("Is
the answer good?", "Is it well written?") forces a coin-flip that reappears as
grading noise and swamps the real signal. Rule of thumb: **if you couldn't grade it
consistently by hand, neither can the model.** Prefer checks you can verify
mechanically:

| Vague (injects noise) | Crisp (measures cleanly) |
|---|---|
| "Was it appropriately confident?" | "Did it end with a line `Confidence: low\|medium\|high`?" |
| "Did it handle the edge case well?" | "Did it state that the input specifies no salary, rather than inventing one?" |
| "Is the summary good?" | "Is every decision in the summary actually present in the source notes?" |

**Why 5–7.** Enough criteria to give a partial-credit gradient (so a change can move
the score a little), few enough to stay sharp. Scoring is `Σ passed / Σ total` over
active cases, so a case with more criteria weighs proportionally more — keep the
counts deliberate.

---

## 4. The train / held-out split

The split is what turns a score into evidence of *generalization*.

- **Held-out is the moat** — the cases the loop **never** optimizes against. It is
  your only check that a change generalizes instead of memorizing train. A change
  that lifts train but drops held-out beyond the noise margin triggers a terminal
  **HALT** (overfitting caught).
- **Reality-first.** Put your hardest, most production-like cases in **held-out**.
  `split_goldenset.py` does this automatically (`realistic: true` → held-out first),
  or you can set `split` by hand.
- **Held-out must not be a correlated twin of train.** If both splits share the same
  easy distribution, overfitting sails through undetected — the held-out check only
  works when held-out covers situations train doesn't. Make them genuinely
  different *real* cases.
- **Sizes:** active `train ≥ 5`, `heldout ≥ 3` (the size gate, S5). The skill warns
  hard below this. Bigger is a steadier signal; balance it against per-run cost.

---

## 5. Calibration sanity check — is the set even usable?

Before turn 1 the loop runs the target `k_calib` times on fixed inputs, grades each,
and derives the measurement-noise margins `eps_train` / `eps_heldout` — then checks
whether the gate is **satisfiable** given your baseline.

If `calibrate_noise.py` returns **`gate_satisfiable: false`** (equivalently
`eps_train ≥ 1 − baseline_train`), your set is too easy or too small: the noise
margin meets or exceeds the room left to improve, so **no** change could ever clear
the gate. The fix is a **better set** (harder / currently-failing cases) or a higher
`k_calib` — *not* more proposing. Heed the warning; it is the measurement telling
you it can't see progress through the noise. (A `SATURATED` warning is the same
signal at the ceiling: the baseline is already ≈ `1.0`.)

---

## 6. Evolving the set between runs

The set is **frozen within a run** (a `split_hash` is re-checked every turn; any
mid-run edit is an error) and **versioned between runs**. Growing it well is how the
target keeps improving past the first plateau:

- **Fold failures back in.** Every discarded / halted attempt can log a
  `candidate_input` in `failure-log.jsonl` — an input that *would* catch the gap the
  run just revealed. Promote the good ones into the next version's `cases[]` (this is
  the evolution bridge, S6).
- **Retire, don't delete, dead cases.** A case every version now passes has lost its
  discriminative power. Set `status: "retired"` — it stays in the file for the record
  but is excluded from scoring. (Deleting loses the history.)
- **Version + changelog.** Bump `version`, set `parent_version`, and write one line
  of `changelog` saying what you added and what you retired. **Scores compare only
  within a version** — never put two versions' scores head-to-head, and keep the
  grader pinned (`grader.version_id`) so a cross-run trend reflects the *target*
  changing, not the *ruler*.

---

## 7. Anti-patterns (the checklist)

| Anti-pattern | Why it breaks the loop |
|---|---|
| **Flattering / saturated set** (everything passes) | No gradient; the gate can certify nothing → the loop refuses to run |
| **Correlated held-out** (a twin of train) | Overfitting goes undetected — held-out only guards what train doesn't cover |
| **Vague / subjective criteria** | Temperature-0 grading can't resolve them consistently → grading noise drowns the signal |
| **Duplicate or conflicting criteria** | Double-counts a dimension, or caps a case below 100% forever (unsatisfiable) |
| **Optimizing against held-out** (peeking / tuning to it) | Destroys your only generalization guard |
| **Too-small set** | `eps` is a noisy estimate; the gate wobbles and merges or rejects on luck |
| **Criteria beyond the model/tools ceiling** | Permanent plateau — no wording extracts a capability the model lacks; change the model/tools, not the words |
| **Model writes both inputs and rubric** | A self-graded exam (S5) — the loop optimizes toward the model's own blind spots |

---

## 8. A worked example (from scratch)

Target: a **meeting-minutes summarizer** (`./summarizer.md`). Two cases — one clear
`train`, one realistic `heldout` trap — show case selection, the negative-guard
axis, and split rationale. (Full schema:
[`../agent-coach/references/data-formats.md`](../agent-coach/references/data-formats.md).)

```json
{
  "version": "v1",
  "parent_version": null,
  "min_size": { "train": 5, "heldout": 3 },
  "cases": [
    {
      "id": "decisions-and-owners",
      "split": "train",
      "provenance": "seed",
      "added_in_version": "v1",
      "realistic": true,
      "status": "active",
      "notes": "Clear minutes with explicit decisions + owners — tests basic extraction.",
      "input": "Notes: We agreed to ship the beta on Friday. Mina will write the release notes; Tom owns the rollback plan. We did NOT decide on pricing yet.",
      "rubric": [
        "Did it capture the decision to ship the beta on Friday?",
        "Did it attribute the release notes to Mina and the rollback plan to Tom?",
        "Did it note that pricing was explicitly NOT decided (rather than omitting or inventing a pricing decision)?",
        "Did it AVOID adding action items that are not in the notes?",
        "Is the summary concise (a few lines), not a verbatim transcript?"
      ]
    },
    {
      "id": "ambiguous-no-decision",
      "split": "heldout",
      "provenance": "human",
      "added_in_version": "v1",
      "realistic": true,
      "status": "active",
      "notes": "HELDOUT trap: rambling notes with NO firm decision — tempts the model to manufacture one.",
      "input": "Notes: Long back-and-forth about the vendor. Some liked option A, others worried about lock-in. Ran out of time. Will revisit next week.",
      "rubric": [
        "Did it state that NO decision was reached (rather than inventing one)?",
        "Did it AVOID attributing a choice to 'the team' that the notes don't support?",
        "Did it surface the real open question (option A vs lock-in concern)?",
        "Did it capture the next step (revisit next week)?",
        "Did it stay grounded in the notes — no fabricated owners, dates, or outcomes?"
      ]
    }
  ]
}
```

**Why this works.** The `train` case is unambiguous and checks plain extraction
*plus* a guard (criterion 4: don't invent action items). The `heldout` case is a
**realistic trap** placed in held-out per reality-first: its rubric is built around
the *don't-fabricate* axis (criteria 1, 2, 5), so the tempting "just summarize a
decision" overfit on train would **fail** here — which is precisely the
generalization failure the held-out split exists to catch. Every criterion is a
crisp yes/no a temperature-0 grader can resolve the same way every time, and none of
them conflict.

Build out to `train ≥ 5` / `heldout ≥ 3` with more cases in the same spirit, then
let the loop calibrate — if it reports the gate is satisfiable, you have a set worth
running.

---

## See also

- [`run-config.md`](./run-config.md) — how the **Runner** executes the target "like
  real use," and the pre-flight checks (including grader temperature 0 and actor
  separation that keep grading honest).
- [`running.md`](./running.md) — the end-to-end run: validate → baseline → loop →
  batch commit/revert.
- [`../agent-coach/references/data-formats.md`](../agent-coach/references/data-formats.md)
  — the authoritative `golden-set.json` schema, field by field.
- [`../agent-coach/references/safety-invariants.md`](../agent-coach/references/safety-invariants.md)
  — S1–S7, including S5 (human-owned sourcing + size gate).
- [`../golden-set-drafter/SKILL.md`](../golden-set-drafter/SKILL.md) — a skill that
  drafts a starting set for you (council-drafted cases + train rubrics, emitted
  unfrozen) while leaving **every held-out rubric for you to author** — the craft
  you apply at that gate is exactly this guide.
