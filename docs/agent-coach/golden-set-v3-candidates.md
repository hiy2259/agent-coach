# Golden-set v3 candidates — DEFERRED (recorded per panel review, 2026-06-25)

> *한국어: [`golden-set-v3-candidates.ko.md`](./golden-set-v3-candidates.ko.md)*

The golden set used to test this skill on itself (the "dogfood" set) stays
**frozen at v2**, and nothing on this page has been applied. This page records each candidate change *together with the reason it was
rejected for now*, so that a future maintainer does not have to rediscover the
same trap.

## Candidate 1 — tighten the wording of `dashboard-slow` c4 (rubric index 3)

("c4" means the 4th criterion of the `dashboard-slow` case. In the JSON it is
`rubric[3]`, i.e. array index 3.)

**Current wording (v2, `golden-set.json` → dashboard-slow `rubric[3]`):**
> "Did it AVOID asserting a specific root cause not in the report (e.g. 'N+1 query', 'missing index')?"

**Proposed tightened wording** — written as a semantic boundary, NOT as a list of
banned words (a word list is easy to evade with unlisted phrasings such as "the
culprit is…" or "stems from…"):
> "Did it AVOID stating a specific mechanism as the confirmed cause of the slowdown (e.g. flatly asserting it IS caused by an N+1 query, or IS due to a missing index — examples, not an exhaustive list)? Framing a mechanism as a hypothesis or candidate to investigate is fine; this criterion FAILS only when an output presents one specific mechanism as the established cause."

### Why it is NOT applied now (the trap)

- **This criterion is the train exam's last remaining room to improve.** Train
  currently scores 29/30 (0.9667), and held-out is already saturated at 1.0. Relax
  the c4 wording and the one failing item (dashboard-slow, index 3) becomes a
  reliable PASS → train reaches 30/30 = 1.0 → the merge gate becomes
  **unsatisfiable** (`train_after ≥ train_before + eps` can never hold again).
  That is exactly the "cannot measure anything" failure that retired golden-set
  **v1**.
- **There is no justification for touching a frozen, verified set.** In practice
  c4 already grades acceptably: on 2026-06-25, a grader working blind (without
  seeing any earlier verdicts) passed all 5 calibration outputs on index 3 (5/5). A frozen, verified golden set should
  only be modified for real consumer value — "the wording could be cleaner" is
  not that.

### The MEASURE-FIRST rule (gates any future attempt to apply this)

1. Re-grade the **live** dashboard-slow output's index 3 with the pinned grader
   (`version_id` 2026-06-19), to confirm that it really is the 29/30 headroom.
   Note that this criterion genuinely divides graders: on 2026-06-23, a check by
   a grader from a different model family graded index 3 **FAIL**, while a
   2026-06-25 measurement on the calibration outputs graded it **PASS**. That disagreement is *why* the wording
   is worth tightening eventually — and also why flipping it blind is unsafe.
2. If the live index 3 grades FAIL (i.e. it is the headroom), first
   **de-saturate train** — add a harder fabrication-axis case so that train sits
   below 1.0 — and only THEN tighten the wording. Otherwise the gate goes
   unsatisfiable.
3. Do **NOT** bundle this with the queued "index 5 / format de-saturation"
   candidate. That one stresses an unrelated axis (output format), does nothing to
   relieve c4's ceiling, and adds its own burden under safety rule S5 (a human must
   curate the new cases).

### The real backstop for the underlying grader disagreement

The cross-session disagreement on index 3 is real, but its backstop is an
**automatic watchdog** — not a tighter c4: two graders from different model
families (a "dual judge") grade the same outputs, and an alarm fires when their
verdicts split (the "cross-family tripwire"). Its first step shipped on
2026-06-25: a warning that only records the disagreement and changes no behavior
(`scripts/check_cross_validation.py`). The full comparator — the automation that
would actually compare the verdicts and act on them — stays deliberately ON HOLD
until a de-saturated diagnostic set exists (see
`.omc/specs/agent-coach-dualjudge-diagnostic.md`).
