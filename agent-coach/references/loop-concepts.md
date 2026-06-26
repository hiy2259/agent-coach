# Loop concepts — the principles behind the loop

The *mechanics* live in SKILL.md and the *guarantees* in
`safety-invariants.md`. This file is the **why** — the handful of ideas that
explain every design choice. Internalize these and the rest of the skill reads as
obvious consequences.

## No evolution without measurement

The founding principle. "Self-improvement" sounds good but is a trap the moment
it is unmeasured: a model edits a prompt, declares it better, and the prompt
slowly drifts on vibes — sometimes worse, with nobody able to tell. This skill
refuses to change the target on a hunch. **Every change is decided by a score on
a fixed exam**, before/after, and a change that can't demonstrate a real gain is
not kept. The whole apparatus — golden set, Runner, Grader, code gate — exists to
make "better" an *observed quantity* rather than an opinion.

## One change at a time (causal isolation)

Each turn changes **exactly one** thing. This is not tidiness; it is the only way
to know *what* worked. If you alter three things and the score moves, you have
learned nothing about which alteration mattered — they could be helping and
hurting in unknown proportions. One isolated change per turn means every kept
change is an attributable, revertible unit of cause and effect. Bundling is how
you end up with a prompt full of cargo-cult rules nobody can justify.

## Proposer ≠ Grader (a player can't referee their own game)

The model that **proposes** a change must not be the model that **grades** it, and
neither runs the target. A model that just authored a change is primed to like
it; let it grade and it will rationalize "close enough, call it a pass," inflating
the score. Separating the roles — distinct subagents, the Grader pinned at
temperature 0, the Bootstrapper a different model again — keeps the measurement
honest. Self-grading is the single fastest way to manufacture fake progress, and
the architecture makes it structurally impossible.

## The failure log is a wrong-answer notebook

Good students keep a notebook of mistakes so they stop repeating them. The loop
does the same: every discarded or halted attempt is written to
`failure-log.jsonl` with what was tried and why it failed, and the **Proposer
reads it before proposing**. Without this memory the search re-discovers the same
losing idea ("force a formal tone") turn after turn, burning budget. With it, the
search has a map of where the gradient *isn't*. The log does double duty: each
entry also seeds a `candidate_input` for growing the golden set (see "human as
coach").

## Subtraction: prune, don't only add

Left to its instincts, anyone improving a prompt only ever **adds** rules — the
text accretes caveats until it is bloated and self-contradictory, and nobody dares
delete anything. So every third turn the loop inverts the question from "what to
add?" to **"what to remove?"**: it drops a suspected-dead rule and re-measures. If
scores hold within the noise margins, the removal stays (`SUB_KEEP`) — the prompt
got simpler at no cost. If not, the rule is restored (`SUB_DROP`). "Stays" is
literal: a `SUB_KEEP` is confirmed and **promoted to the live current prompt** the
same way a merge is — if you only record the decision but never promote the pruned
candidate, the removed rule silently stays live and the pruning was a no-op.
Deliberate, measured pruning is the counter-pressure that keeps the target lean.

## Human as coach (on the loop) + final E2E (in the loop)

The human is not a per-change approver clicking yes/no all night — that defeats
the point of automation. The human is the **coach**: they own the things judgment
can't be delegated for, and they sit **on the loop** (designing it) rather than
**in** every iteration of it:

- **Sourcing and the rubric are human-owned.** The human curates *which* inputs
  the golden set tests and authors *what counts as good* (the yes/no criteria).
  If the model wrote both, the loop would optimize toward the model's own blind
  spots — a self-graded exam (S5).
- **Batch approval, not per-change.** The loop runs N turns autonomously, then
  presents one package — diff, `history.jsonl`, `failure-log.jsonl` — and the
  human decides **commit or revert**. That commit is the first and only write to
  the live file (S4).
- **Final end-to-end QA stays human.** A passing golden-set score is necessary,
  not sufficient. Actually *using* the result — the real-world acceptance test —
  is the one step the human keeps **in** the loop.

## Golden set: frozen within a run, versioned between runs

For before/after scores to be comparable, the exam must not change mid-exam. So
**within a run** the golden set and its split are frozen — a `split_hash` is
re-checked every turn and any mid-run edit is an error. But the set is not static
forever: **between runs** the human grows it, folding in failure-derived cases
(via `candidate_input`) as a new `version`. The discipline is simple — scores are
comparable **only within a version**, so every history row records its
`golden_set_version` and versions are never compared head-to-head. Freeze to
measure; version to evolve.

## Reality-first held-out

The split is not random. The **most realistic, production-like cases go into
held-out**, because held-out is the generalization guard — the cases the loop
never optimizes against. Putting your hardest real inputs there means a change has
to survive the situations you actually care about, not just the toy cases it was
tuned on. It also prevents *correlated blind spots*: if train and held-out shared
the same easy distribution, overfitting could sail through undetected.

## The model/tools ceiling (a plateau is information)

A prompt can only do so much. Beyond a point, the score stops rising not because
the loop failed but because **the instruction text has reached the ceiling of what
the fixed model and available tools can achieve** — no wording change can extract
capability the model doesn't have. When the loop plateaus below the score you
hoped for, that is *information, not failure*: it says "this model + these tools
cap out here; to go further, change the model or add a tool, not the words."
Report the plateau honestly and stop thrashing — grinding more turns against a
ceiling just wastes budget and risks ratcheting in noise.
