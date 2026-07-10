# Building a good golden set

> The golden set is the exam, and the loop is only as smart as its exam: every
> `MERGE`, `HALT`, and `DISCARD` is computed from how your cases score. Most of the
> leverage in the whole skill lives here — and this is the one part **you own**. The
> model is never allowed to write both the cases and the grading criteria; that
> would mean grading its own homework. A set that flatters the target produces
> scores that look great and mean nothing. A set that *discriminates* — that can
> tell a better prompt from a worse one — is what makes "better" mean something.

This page teaches the craft: how to choose cases, how to write grading criteria
that measure real quality, how to split train from held-out, how to grow the set
over time, and the anti-patterns that quietly defeat the whole loop. For the exact
JSON shapes see
[`../../skills/agent-coach/references/data-formats.md`](../../skills/agent-coach/references/data-formats.md);
for the safety reasoning see
[`../../skills/agent-coach/references/safety-invariants.md`](../../skills/agent-coach/references/safety-invariants.md).

---

## 1. The core idea: every case must be able to fail

A case earns its place only if it can tell a **better** target from a **worse**
one. That means the target must be able to **fail** it. A case the target already
passes on every version carries zero information — it just pads the score.

The failure mode to watch for is **saturation**: when (almost) every case passes,
the baseline score sits near `1.0` and there is no room left to improve into. The
merge gate demands "beat the baseline by more than noise", and no change can do
that when the baseline is already at the ceiling. The loop detects this before
turn 1 — `calibrate_noise.py` returns `gate_satisfiable: false` or a `SATURATED`
warning — and **refuses to run** rather than burn turns. That refusal is the set
telling you it cannot measure progress.

> **A real example.** When we ran this skill on its own project, the first golden
> set scored the target a perfect `1.0` on both splits. The loop correctly stopped
> before turn 1 with a `SATURATED` warning. Only after we added a criterion the
> target actually *failed* — restoring room to improve — could the loop measure,
> and then merge, a real improvement.

**Aim for a baseline with headroom.** A good starting set scores the *current*
target clearly below the ceiling, so a real gain is visible above the measurement
noise.

---

## 2. Choosing the cases (the inputs)

The inputs are the situations you put the target through. Choose them to **probe
where the target is weak**, across the full breadth of its real job:

- **Use inputs that represent real production traffic**, not toy or happy-path
  ones. If the set contains only easy inputs, a passing score says nothing about
  real use.
- **Aim at the failure modes that matter:**
  - *Ambiguous or underspecified inputs* — self-contradictory, or missing the
    context the target needs; the kind it tends to mishandle.
  - *Hallucination bait* — inputs where the tempting answer is to **invent** a
    detail, cause, or fact that is not there. A good target must say "not
    specified" instead of making one up.
  - *Realistic hard cases* — inputs the target actually meets in production but
    handles inconsistently. These are the most valuable ones, and they belong in
    **held-out** (see section 4 below).
  - *Breadth* — spread the cases across the target's whole job, not one narrow
    skill.
- **A few genuinely probing cases beat a pile of near-duplicates.** Variety of
  failure modes matters more than volume.

### You own the inputs, not just the grading criteria

The guard that carries the most weight is this: **you supply your own real cases**.
This is **S5**, one of agent-coach's seven safety rules (all seven are laid out in
[how it works](./how-it-works.md)). At cold start the skill can *draft* candidate inputs for you —
that is exactly what the **Bootstrapper** role is for, and it deliberately aims at
the target's weaknesses — but what it produces are **candidates only**. You approve
them, prune them, and add the hard cases it missed. Rubber-stamping an AI-drafted
set weakens the guard: the model and the case-writer then share the same blind
spots, and the loop ends up optimizing toward a self-consistent illusion. (See
[`../../skills/agent-coach/agents/bootstrapper.md`](../../skills/agent-coach/agents/bootstrapper.md).)

---

## 3. Writing good grading criteria — the craft most people get wrong

Each case gets **5–7 yes/no criteria**. Writing them well is the highest-leverage
and least obvious skill in this whole exercise, because the criteria *are* your
definition of "good". Sharp criteria make the loop measure real quality; vague or
tangled ones make it measure noise.

**One criterion checks one thing.** Don't bundle. "Did it find the bug **and** fix
it **and** explain it?" is really three questions — split it into three criteria,
each scored on its own. The grader judges each criterion in isolation, and exactly
that granularity is what lets the loop detect a small but real improvement.

**A criterion describes what a good answer contains — not the one correct answer.**
Write "Did it propose a parameter-binding (prepared-statement) fix?" — not "Did it
output exactly *this* code?" You are defining the properties of a good response,
not pinning a single golden string.

**Include negative criteria — the "did not make things up" axis.** Some of your
most valuable criteria check what the target must **avoid**: "Did it AVOID
inventing a cause not present in the report?", "Did it AVOID asserting a severity
the input doesn't support?" These guard criteria matter enormously: they catch a
prompt that "improves" by hallucinating — the exact path the held-out check exists
to stop. For a negative criterion, `passed = true` means the output **avoided**
the bad behavior; make the direction of the question unmistakable.

**Keep criteria independent of each other.** Two specific traps, both real:

- *Don't test the same thing twice.* Two criteria that check one dimension double
  its weight in the score and crowd out everything else.
- *Don't add a criterion that **conflicts** with an existing one.* A criterion
  that fights another caps that case below 100% **forever** and poisons the
  signal.

  > **A real example.** On an ambiguous "is this even a bug?" case, our rubric
  > already rewarded *not* inventing a severity ("AVOID assigning a severity when
  > it isn't knowable"). Someone proposed a *format* criterion — "must label
  > severity as one of `P0`–`P3`" — which directly contradicts it: the correct
  > answer (mark the severity undetermined) can satisfy only one of the two. We
  > dropped the conflicting criterion and added an **orthogonal** one instead —
  > "require a `Confidence:` line" — a dimension no other criterion touched.
  > Independent criteria add signal; conflicting criteria destroy it.

**Make every criterion unambiguous for a temperature-0 grader.** The grader runs
at temperature 0 and must resolve every borderline the *same way every time* —
that zero-variance grading is what the noise margin depends on. A vague criterion
("Is the answer good?", "Is it well written?") forces a judgment call, and that
judgment call comes back as grading noise that drowns the real signal. Rule of
thumb: **if you couldn't grade it consistently by hand, neither can the model.**
Prefer checks that are close to mechanical:

| Vague (injects noise) | Crisp (measures cleanly) |
|---|---|
| "Was it appropriately confident?" | "Did it end with a line `Confidence: low\|medium\|high`?" |
| "Did it handle the edge case well?" | "Did it state that the input specifies no salary, rather than inventing one?" |
| "Is the summary good?" | "Is every decision in the summary actually present in the source notes?" |

**Why 5–7 criteria?** Enough that a change can move the score in small steps
(partial credit), few enough that each criterion stays sharp. The score is
`Σ passed / Σ total` over the active cases, so a case with more criteria
automatically weighs more — keep the counts deliberate.

---

## 4. The train / held-out split

The split is what turns a score into evidence of *generalization* — proof that a
change works beyond the cases it was tuned on.

- **Held-out is the last line of defense** — the cases the loop is **never**
  allowed to optimize against. It is your only check that a change generalizes
  instead of memorizing train. A change that lifts train but drops held-out beyond
  the noise margin triggers a terminal **HALT**: overfitting, caught.
- **Reality first.** Put your hardest, most production-like cases in **held-out**.
  `split_goldenset.py` does this automatically (cases marked `realistic: true` go
  to held-out first), or you can set each case's `split` by hand.
- **Held-out must not be a twin of train.** If both splits share the same easy
  distribution, overfitting sails through undetected — the held-out check only
  works where held-out covers situations train doesn't. Make the two splits
  genuinely different *real* cases.
- **Sizes:** at least 5 active train cases and 3 held-out cases (`train ≥ 5`,
  `heldout ≥ 3` — the minimum sizes required by safety rule S5). The skill warns hard below these numbers. A
  bigger set gives a steadier signal; balance that against per-run cost.

---

## 5. The calibration check — can this set measure anything at all?

Before turn 1, the loop runs the target `k_calib` times on the same fixed inputs,
grades every run, and measures how much the score wobbles. That wobble becomes the
noise margins `eps_train` / `eps_heldout`. Then it checks whether the merge gate is
even **satisfiable** given your baseline.

If `calibrate_noise.py` returns **`gate_satisfiable: false`** (equivalently,
`eps_train ≥ 1 − baseline_train`), your set is too easy or too small: the noise
margin is at least as large as all the room left to improve, so **no** change
could ever clear the gate. The fix is a **better set** — harder cases, cases the
target currently fails — or a higher `k_calib`. It is *not* "keep proposing." Take
the warning seriously: it is the measurement telling you it cannot see progress
through the noise. (A `SATURATED` warning is the same message at the ceiling: the
baseline is already ≈ `1.0`.)

---

## 6. Growing the set between runs

Within one run the set is **frozen** — a `split_hash` is re-checked every turn,
and any mid-run edit is an error. Between runs it is **versioned**, and growing it
well is how the target keeps improving past its first plateau:

- **Fold failures back in.** Every discarded or halted attempt can log a
  `candidate_input` in `failure-log.jsonl` — an input that *would* catch the gap
  that attempt just revealed. Promote the good ones into the next version's
  `cases[]`. (Safety rule S6 guarantees this path: today's failures become the
  next version's cases.)
- **Retire dead cases; don't delete them.** A case that every version now passes
  has lost its power to discriminate. Set `status: "retired"` — the case stays in
  the file for the record but is excluded from scoring. (Deleting it would erase
  the history.)
- **Version it, with a changelog.** Bump `version`, set `parent_version`, and
  write one line of `changelog` saying what you added and what you retired.
  **Scores are only comparable within one version** — never put two versions'
  scores head to head — and keep the grader pinned (`grader.version_id`), so that
  a cross-run trend reflects the *target* changing, not the *ruler* (the grader).

---

## 7. Anti-patterns (the checklist)

| Anti-pattern | Why it breaks the loop |
|---|---|
| **Flattering / saturated set** (everything passes) | No room to improve; the gate can certify nothing → the loop refuses to run |
| **Held-out that mirrors train** | Overfitting goes undetected — held-out only guards situations train doesn't cover |
| **Vague / subjective criteria** | A temperature-0 grader can't resolve them consistently → grading noise drowns the signal |
| **Duplicate or conflicting criteria** | Double-counts one dimension, or caps a case below 100% forever (unsatisfiable) |
| **Optimizing against held-out** (peeking at it, tuning to it) | Destroys your only generalization guard |
| **Too-small set** | `eps` becomes a noisy estimate; the gate wobbles and merges or rejects on luck |
| **Criteria beyond what the model/tools can do** | A permanent plateau — no wording extracts a capability the model lacks; change the model or tools, not the words |
| **The model writes both inputs and criteria** | A self-graded exam (violates safety rule S5) — the loop optimizes toward the model's own blind spots |

---

## 8. A worked example (from scratch)

The target: a **meeting-minutes summarizer** (`./summarizer.md`). Two cases — one
clear `train` case and one realistic `heldout` trap — are enough to show how cases
are chosen, how the "did not make things up" guard works, and why each case goes
into its split. (Full schema:
[`../../skills/agent-coach/references/data-formats.md`](../../skills/agent-coach/references/data-formats.md).)

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

**Why this works.** The `train` case is unambiguous: it checks plain extraction
*plus* one guard (criterion 4: don't invent action items). The `heldout` case is a
**realistic trap**, placed in held-out per reality-first: its rubric is built
around the *don't-fabricate* axis (criteria 1, 2, 5). A change that overfits train
by learning to "always summarize a decision" would **fail** here — exactly the
generalization failure the held-out split exists to catch. Every criterion is a
crisp yes/no that a temperature-0 grader resolves the same way every time, and
none of them conflict.

Build the set out to `train ≥ 5` / `heldout ≥ 3` with more cases in the same
spirit, then let the loop calibrate. If it reports the gate is satisfiable, you
have a set worth running.

---

## See also

- [`run-config.md`](./run-config.md) — how the **Runner** executes the target
  "like real use", and the pre-flight checks (grader at temperature 0, role
  separation) that keep grading honest.
- [`running.md`](./running.md) — the run end to end: validate → baseline → loop →
  commit or revert as a batch.
- [`../../skills/agent-coach/references/data-formats.md`](../../skills/agent-coach/references/data-formats.md)
  — the authoritative `golden-set.json` schema, field by field.
- [`../../skills/agent-coach/references/safety-invariants.md`](../../skills/agent-coach/references/safety-invariants.md)
  — the seven safety rules (S1–S7) in full, including S5 (human-owned sourcing +
  the size minimums).
- [`../../skills/golden-set-drafter/SKILL.md`](../../skills/golden-set-drafter/SKILL.md) — a companion
  skill that drafts a starting set for you (council-drafted cases + train rubrics,
  emitted unfrozen) while leaving **every held-out rubric for you to write** — and
  the craft you apply at that gate is exactly this guide.
