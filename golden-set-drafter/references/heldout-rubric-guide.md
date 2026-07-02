# Held-out rubric authoring guide (for the human at the gate)

You are here because agent-coach's `op=split` stopped with an error naming
held-out cases with empty rubrics. **That error is the gate working.** The
drafter deliberately left every held-out rubric empty: the held-out split is
the loop's only generalization guard, and if the same AI that drafted the
inputs also defined "good" for them, the whole exam would grade itself — the
loop would then optimize toward the AI's own blind spots with nothing to catch
it. Your rubric is the one part of this set that must come from you.

This guide is the condensed craft. Full treatment:
`../../docs/golden-set.md` and `../../agent-coach/references/golden-set-guide.md`.

## Before writing a single criterion

- **Review the held-out INPUTS first — replace freely.** They are AI drafts
  (the deepest residual of this design). If an input doesn't look like
  something your real users actually send, swap it for one that does. Real
  production messages beat invented ones every time.
- **Do not run the target on these inputs first.** Writing criteria while
  looking at the model's answer anchors you to that answer — you end up
  grading "did it do what it did", not "did it do what a good answer needs".
  Define "good" from your domain judgment, then let the loop do the running.

## Writing the criteria — the craft in seven rules

1. **Binary and checkable at temperature 0.** Each criterion is a yes/no
   question a careful reader answers the same way every time. "Did it name
   the deadline owner explicitly?" — yes. "Is it well-organized?" — no
   (two readers disagree; that's grading noise, and noise drowns the merge
   signal the loop depends on).
2. **5–7 intentional criteria — never pad.** If a case honestly supports 4
   sharp criteria, keep 4. A filler criterion added to reach a number injects
   noise and dulls the overfit guard. (The code gate only rejects *empty*;
   the quality is yours to hold.)
3. **At least one negative/guard criterion.** "Did it avoid inventing a
   requirement not present in the input?" Guards define the failure you never
   want to trade for — they are what stops the loop from optimizing into
   confident fabrication. For guards, *pass* means the bad thing did NOT
   happen.
4. **Independent criteria — no duplicates, no conflicts.** Two criteria that
   measure the same thing double-count one dimension. Two that cannot both
   pass cap the case below 100% forever, and the loop's gate can never
   certify it (unsatisfiable).
5. **Within the model + tool ceiling.** Don't demand what no wording can
   deliver (live web lookups when the runner has no tools, knowledge the
   model lacks). Ceiling-breaking criteria create a permanent plateau the
   loop will chase pointlessly.
6. **Criteria, not answers.** The rubric is not "the correct output" — it is
   the properties a good output must have for *this* input. Ask "what would
   make me accept an answer here?", not "what would the answer say?".
7. **Pair guards across cases — never inside one.** If one case guards
   against inventing a deadline when none exists, make sure a DIFFERENT case
   (whose input has a real deadline) requires capturing it — otherwise an
   agent that simply never mentions deadlines sails through your guard
   (omission gaming). Keep the two sides in different cases: both sides in
   one case's rubric is a conflicting pair that caps that case below 100%
   forever (this repo's dogfood hit exactly that with a "Severity" criterion
   — see `docs/golden-set.md`).

## Per-case template

For each held-out case id the error named:

```
Case: <id>            (input: read it fully first — replace it if unrealistic)
What this case probes: <the capability/failure this input exercises>

rubric:
  1. Did it <concrete, observable property>?
  2. Did it <second independent property>?
  3. Did it avoid <the failure this case exists to catch>?   <- guard
  4. ...
  (5-7 intentional criteria; fewer only if honestly sufficient)
```

## Worked micro-example

Input (production-like): "다음 회의록 요약해줘: …(회의록에 마감일 언급 없음)…"

```json
"rubric": [
  "Did it list every decision actually made in the transcript?",
  "Did it attribute each action item to the person named in the transcript?",
  "Did it state that no deadline was specified, rather than inventing one?",
  "Did it keep the summary under the requested length?",
  "Did it avoid adding agenda items that never appeared in the transcript?"
]
```

Note the third and fifth: guards against fabrication — the axis AI-drafted
train rubrics most often under-protect.

## Final checklist before re-running op=split

- [ ] Every held-out input reviewed; unrealistic ones replaced
- [ ] Every held-out case has 5–7 (or honestly fewer) binary criteria
- [ ] ≥ 1 guard criterion per case
- [ ] No two criteria measure the same thing; none conflict
- [ ] Nothing demands capabilities the runner/model doesn't have
- [ ] You did NOT look at target outputs while writing
- [ ] You wrote these yourself — not an AI, not this skill (asking the
      drafter to fill them turns the exam back into a self-graded one; it
      will refuse, and the refusal is load-bearing)

Then re-run the `op=split` command from the runbook. It will freeze the set
(`split_hash` appears), `op=state` answers `"ready"`, and agent-coach's
calibration takes over as the authority on whether the set can drive a run.
