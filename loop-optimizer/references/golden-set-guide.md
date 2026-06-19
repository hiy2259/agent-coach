# Golden-set guide — make the exam *discriminate* (agent checklist)

The golden set is the moat: every `MERGE`/`HALT`/`DISCARD` is computed from how the
cases score, and the human owns it (S5). This is the tight, operational checklist to
**consult while helping the human curate inputs and author the rubric at cold start**
(SKILL.md "Cold start", steps 3–4) and when advising on golden-set evolution. The
*why* is in [`loop-concepts.md`](./loop-concepts.md); the exact JSON shapes are in
[`data-formats.md`](./data-formats.md); the guarantees are in
[`safety-invariants.md`](./safety-invariants.md).

## The one test: can a case fail?

A case earns its place only if it can tell a **better** target from a **worse** one —
which means it must be able to **fail**. A case the target already aces on every
version is zero signal.

- **Discriminate, don't flatter.** Aim for a baseline that sits clearly **below** the
  ceiling, so a real gain is visible above the noise.
- **Saturation refuses to run.** If (almost) every case passes, the baseline is ≈1.0,
  `calibrate_noise.py` returns `gate_satisfiable: false`, and the loop STOPS — there
  is no room above the baseline for any change to clear the gate. That is the set
  telling you it cannot measure progress.
- At cold start, **expose failure first** (run the target on candidates, step 2) and
  keep the inputs it actually struggles on.

## Choosing inputs (step 3 — help, don't decide)

- **Representative of real production**, not toy / happy-path.
- **Aim at the failure modes that matter:** adversarial / underspecified (ambiguous,
  self-contradictory, missing-context); **hallucination bait** (the tempting answer
  invents a detail not present, so a good target must say "not specified"); realistic
  hard cases (these go to **held-out**).
- **Variety of failure mode > volume.** A few probing cases beat a pile of
  near-duplicates.
- **The human owns selection, not just the rubric (S5).** The Bootstrapper
  ([`../agents/bootstrapper.md`](../agents/bootstrapper.md)) drafts *candidates only*;
  the human approves, prunes, and adds the hard cases it missed. Rubber-stamping an
  AI-drafted set shares the model's blind spots — a self-consistent illusion.

## Writing rubric criteria (step 4) — 5–7 yes/no per case

The highest-leverage, least-obvious skill: the criteria *are* the definition of
"good." Check each one:

- [ ] **One criterion = one independently-checkable thing.** Split "found the bug
      **and** fixed it **and** explained it?" into three; the Grader judges each in
      isolation, and that granularity is what lets the loop detect a small real move.
- [ ] **Criteria, not the answer.** "Did it propose a parameter-binding (prepared
      statement) fix?" — not "did it output *this* exact code?"
- [ ] **Include negative / guard criteria — the "didn't fabricate" axis.** e.g. "Did
      it AVOID inventing a cause not in the input?", "Did it AVOID asserting a severity
      the input doesn't support?" `passed = true` means it **avoided** the bad
      behavior — make the polarity unmistakable. These catch the
      overfit-by-hallucination trajectory the held-out guard (S1) exists to stop.
- [ ] **Orthogonal — not duplicate, not conflicting.** Two criteria testing the same
      thing inflate one dimension. Worse, a criterion that **conflicts** with another
      caps that case below 100% **forever** and poisons the signal — e.g. a "label
      severity as P0–P3" criterion fights an "AVOID asserting severity when unknowable"
      one; the correct answer can satisfy only one. Drop the conflict; pick an
      orthogonal dimension (e.g. require a `Confidence:` line) instead.
- [ ] **Unambiguous for a temperature-0 grader.** The Grader is temp 0 and must
      resolve every borderline the same way every time — that zero-variance grading is
      what the noise margin depends on. Rule of thumb: **if you couldn't grade it
      consistently by hand, neither can the model.** Prefer mechanically-checkable:
      "ends with a line `Confidence: low|medium|high`" beats "appropriately confident."

(Scoring is `Σ passed / Σ total` over active cases, so a case with more criteria
weighs proportionally more — keep the counts deliberate.)

## Split, then sanity-check (after curation)

- **Reality-first held-out.** `split_goldenset.py` puts the **most realistic** cases
  in held-out (`realistic: true`) and freezes the split. Held-out is the
  generalization guard the loop never optimizes against.
- **Held-out must not be a correlated twin of train** — if both share the same easy
  distribution, overfitting sails through undetected.
- **Size gate (S5):** active `train ≥ 5`, `heldout ≥ 3`.
- **Is the set usable?** Pass the baseline to `calibrate_noise.py`. `gate_satisfiable:
  false` (i.e. `eps_train ≥ 1 − baseline_train`) means too easy / too small: **no**
  change could ever clear the gate. Fix = harder / currently-failing cases or a higher
  `k_calib`, **not** more proposing.

## Evolving the set between runs

- **Fold failures back in.** Promote good `candidate_input`s from `failure-log.jsonl`
  into the next version's `cases[]` (the evolution bridge, S6).
- **Retire, don't delete.** A case every version now passes lost its discriminative
  power → `status: "retired"` (kept for the record, excluded from scoring).
- **Version + changelog.** Bump `version`, set `parent_version`, write one
  `changelog` line. Scores compare **only within a version**, and only while the
  grader is pinned (`grader.version_id`) — never compare two versions head-to-head.

## Anti-patterns (quick reject)

Flattering / saturated set · correlated held-out (a twin of train) · vague /
subjective criteria · duplicate **or conflicting** criteria · optimizing against
held-out (peeking) · too-small set · criteria beyond the model/tools ceiling (no
wording extracts a capability the model lacks — change the model/tools, not the
words) · model writes both inputs and rubric (a self-graded exam, S5).
