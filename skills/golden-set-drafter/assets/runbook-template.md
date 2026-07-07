# Runbook authoring template (for the model composing the emit payload)

`emit_draft.py` assembles `GOLDEN-SET-DRAFT-README.md` from the `runbook`
payload blocks **you** write, then appends a machine-generated "Gate data"
appendix (held-out ids, the exact op=split command, expected first error,
ruler disclosure, top-ups, exclusions, council leftovers). You write the human
prose; the script writes the facts. Compose every block in the **case
language** resolved in Step 1 — the person authoring held-out rubrics is the
production-language user, and a runbook they skim past protects nothing.

## Required blocks

### `title`
One line. Must read as a DRAFT notice, e.g. (Korean case): "골든셋 초안 —
held-out 채점표는 당신이 작성해야 실행됩니다".

### `intro`
2–5 sentences, covering exactly these facts, plainly:
- This is a **draft**, not a finished golden set.
- agent-coach will judge usability itself (`calibrate_noise`) before any run —
  this skill guarantees structure, not usefulness.
- The set is deliberately **unfrozen** and every held-out rubric is
  **intentionally empty**: agent-coach will refuse to run until the human
  authors them. The upcoming error is expected and correct.

### `next_steps`
A numbered list, in order:
1. Review the held-out **inputs**; replace any that don't look like real
   production messages (they are AI drafts — limitation #1).
2. Author **all** held-out rubrics yourself using
   `references/heldout-rubric-guide.md` (digest its six craft rules here in
   the case language — binary/temp-0, 5–7 intentional no padding, ≥1 guard,
   independent, within ceiling, criteria-not-answers).
3. Run the op=split command from the Gate data appendix; the FIRST run is
   expected to fail listing the empty-rubric ids — that is the gate, not a bug.
4. Fill, re-run to freeze, then let agent-coach calibrate and decide.

**§5-2 phrasing rule (hard):** nowhere in any block may the text offer,
suggest, or imply that this skill / an AI can write, pre-fill, or "suggest
starting points for" the held-out rubrics. If the user asks for that later,
the answer is a brief refusal + this guide. One click of accepted AI rubrics
collapses the design into a self-graded exam.

### `limitations`
Render ALL TEN honest limitations below into the case language — faithfully
and completely, numbered 1–10 (the emitter counts numbered items and refuses
fewer). Do not soften them; surfacing residual risk honestly is a design
feature, not marketing damage.

Canonical source (translate meaning-faithfully):

1. Held-out **inputs** are still AI-drafted — the deepest residual; review and
   replace them (recommended, not enforced).
2. Train input AND rubric are AI-authored — technically the self-graded-exam
   anti-pattern on the train axis, weaker than agent-coach Bootstrapper's
   "human owns all rubrics" contract; a conscious v1 trade sealed by the
   human-owned held-out rubrics + the S1 overfit HALT. If held-out ownership
   ever drops below "all human", this seal breaks.
3. Rubric **quality** is not code-enforceable — the gate blocks only *empty*;
   a lazy one-line rubric passes and injects noise. The authoring guide is
   the mitigation.
4. Authenticity is unprovable — the gate forces the act of authoring, not the
   thought behind it.
5. Consumer-side bypasses (`require_rubric:false`, retiring cases below the
   floor) live in agent-coach's layer — this draft can only advise against
   them.
6. Usability is **delegated, not guaranteed** — agent-coach's calibration
   loudly rejects a flat/saturated set; nothing fails silently.
7. There is no gate opt-out in v1 — the gate is the only structural defense
   against a self-graded exam.
8. The expose-failure evidence is a heuristic, train-only, measured with the
   production model pinned but temperature carried as prose (identically on
   both sides); agent-coach's calibration is the authority.
9. This skill will never draft held-out rubrics — by design, without
   exceptions.
10. Held-out inputs cannot be both "AI-verified failing" and "uncorrelated
    with train" — so they were chosen for realism + coverage diversity and
    carry NO failure claim; your rubric + calibration judge them.

### `notes` (optional)
Anything case-specific worth telling the human: excluded tool-dependent cases
and why, unresolved council objections in plain words, top-up context.
