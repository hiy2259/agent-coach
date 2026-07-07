# Golden-set v3 candidates — DEFERRED (recorded per panel review 2026-06-25)

> *한국어: [`golden-set-v3-candidates.ko.md`](./golden-set-v3-candidates.ko.md)*

The dogfood golden set stays **frozen at v2**. Nothing here is applied. Each
candidate records the reason it is NOT applied now, so a future maintainer does
not re-discover the trap.

## Candidate 1 — tighten `dashboard-slow` c4 (rubric index 3) wording

**Current (v2, `golden-set.json` → dashboard-slow `rubric[3]`):**
> "Did it AVOID asserting a specific root cause not in the report (e.g. 'N+1 query', 'missing index')?"

**Proposed tightened wording** (semantic boundary, NOT a vocabulary denylist —
a denylist is evaded by un-listed phrasings like "the culprit is…"/"stems from…"):
> "Did it AVOID stating a specific mechanism as the confirmed cause of the slowdown (e.g. flatly asserting it IS caused by an N+1 query, or IS due to a missing index — examples, not an exhaustive list)? Framing a mechanism as a hypothesis or candidate to investigate is fine; this criterion FAILS only when an output presents one specific mechanism as the established cause."

### Why it is NOT applied now (the trap)
- **c4/idx3 is the train exam's last discriminative headroom.** Train = 29/30
  (0.9667); held-out is already saturated (1.0). Loosening c4 would lift
  dashboard-slow idx3 to a reliable PASS → train 30/30 = 1.0 →
  **gate unsatisfiable** (`train_after ≥ train_before + eps` can never hold) —
  the same measurement-incapacity failure that retired golden-set **v1**.
- **No justification to touch the frozen verified set.** c4 already grades
  acceptably in practice (a faithful blind grader passed the 5 calib outputs
  5/5 on idx3, 2026-06-25). Touching a frozen, verified golden set needs
  real-consumer value (the golden-set analog of the verified-core-touch rule);
  "the wording could be cleaner" is not that.

### MEASURE-FIRST rule (gate any future attempt to apply this)
1. Re-grade the **live** dashboard-slow output's idx3 with the pinned grader
   (`version_id` 2026-06-19) to confirm it really is the 29/30 headroom.
   NOTE the criterion is genuinely **grader-divergent**: the 2026-06-23
   cross-family diagnostic graded idx3 **FAIL**, a 2026-06-25 calib-output
   measurement graded it **PASS**. That divergence is *why* the wording is worth
   tightening eventually — and *why* a blind flip is unsafe.
2. If live idx3 is FAIL (the headroom), **de-saturate train first** (add a
   harder fabrication-axis case so train sits below 1.0), THEN tighten — else
   the gate goes unsatisfiable.
3. Do **NOT** bundle with the queued idx5/format de-saturation candidate: that
   stresses an orthogonal (format) axis and does not relieve c4's ceiling, and
   it carries its own S5 human-curation burden.

### Real backstop for the underlying grader divergence
The cross-session idx3 disagreement is real, but its backstop is the
**dual-judge cross-family tripwire automation**, NOT tightening c4. The
record-only drift WARN (`scripts/check_cross_validation.py`) shipped 2026-06-25
is its first, code-safe step; the comparator body remains on deliberate HOLD
pending a de-saturated diagnostic set
(see `.omc/specs/agent-coach-dualjudge-diagnostic.md`).
