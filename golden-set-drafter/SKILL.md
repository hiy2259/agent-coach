---
name: golden-set-drafter
description: >-
  Use this to build the golden set a prompt-improvement loop needs as input —
  the train + held-out example cases plus yes/no rubrics (a.k.a. eval set,
  test cases) for a target prompt, agent, skill, or instruction file. It runs
  BEFORE and INSTEAD OF agent-coach/loop-optimizer whenever that set still
  needs creating — so trigger THIS (not the loop) even when they say "run
  agent-coach, but make the golden set first." Fire whenever they give a
  target file plus a development direction (goals, failure stories, logs) and
  want cases, rubrics, held-out inputs, or a golden-set.json drafted,
  generated, bootstrapped, or refreshed (v1 answers refresh asks with a
  guided fresh-v1 rebuild) — even if they don't know the schema/split rules
  or only say "make my agent measurable." Korean triggers include
  골든셋·평가셋 만들어줘·생성해줘·뽑아줘·갱신해줘. Emits UNFROZEN drafts —
  held-out rubrics stay empty for the human to author (S5). Do NOT use to
  run, optimize, split, freeze, grade, or review an existing golden set, or
  ghostwrite held-out rubrics.
compatibility: Requires python3 >=3.8 (standard library only) for scripts/; requires subagents (Claude Code) to keep the council actors isolated; agent-coach co-located strongly preferred (co-located agents/ originals win at runtime; integration tests exercise ../agent-coach/scripts/split_goldenset.py) — standalone installs fall back to the bundled byte-copies in agents/vendored/ (drift-guard tested) with a RUNLOG disclosure.
---

# Golden-Set Drafter

You draft a golden set so the user doesn't have to learn the schema — but you
**never** finish it. The set you emit is deliberately incomplete in exactly one
place: every held-out case ships with an **empty rubric**. agent-coach's own
code then refuses to run until a human writes those rubrics:

```
you emit:  unfrozen set (no split_hash) + held-out rubrics all []
                  │
                  ▼
agent-coach op=state  →  "unfrozen" → routes to op=split        [split_goldenset.py:307-310]
                  │
                  ▼
op=split (require_rubric, default true) → ValueError naming
the empty-rubric held-out ids → REFUSES to freeze               [split_goldenset.py:381-389]
                  │
                  ▼
only unlock: the HUMAN authors every held-out rubric → freeze → loop may start
```

Why this shape: a set where the model writes both the inputs and all the
rubrics is a **self-graded exam** — the #1 golden-set anti-pattern — and the
loop would optimize toward its own blind spots. The held-out split is the
loop's only generalization guard (S1 HALT), so *that* is the part a human must
own. Everything else (train cases, held-out inputs, structure, split, failure
exposure) you do automatically. The gate is not yours to enforce — it already
exists in agent-coach; you just emit a draft that keeps it armed.

## Hard rules — read before anything else

1. **§5-2 (no exceptions, not even on request): never write, complete, or
   offer to write a held-out rubric.** Not in the default flow, not when the
   user asks, not as a "starting point", not as "examples you can edit". The
   moment an AI drafts held-out rubrics, the human's one-click acceptance turns
   the whole set into a self-graded exam and the design collapses. When asked,
   decline briefly and hand over `references/heldout-rubric-guide.md` instead.
2. **Emission invariants are code-enforced — do not work around them.**
   `scripts/emit_draft.py` raises unless: no `split_hash`; every held-out
   rubric is `[]` with `split:"heldout"` pinned; train ≥ 5 and held-out ≥ 3;
   `provenance` is a documented enum value (never `"ai-draft"`); exactly one of
   `input`/`input_file` per case; no `require_rubric` key in any emitted JSON.
3. **Code independence.** Never modify anything under `../agent-coach/` or the
   orchestrate-claude-code repo. You *read* agent-coach's agent files and
   *depend on* its gate behavior; you never edit it. At runtime you also do
   not run agent-coach's scripts — the op=split error is the **human's**
   checkpoint moment, not yours to pre-clear (only this skill's tests exercise
   the real gate, to prove the handoff works).
4. **Same-ruler, honestly scoped.** The "this case fails today" claim is made
   **only for train cases**, whose AI-drafted rubric ships unchanged — there
   the selecting ruler and the future measuring ruler are the same. Held-out
   carries **no discrimination claim** (its rubric doesn't exist yet). Never
   present held-out inputs as "verified failing".
5. **Never weaken "ALL held-out rubrics are human-authored".** Partial human
   ownership (e.g. 1 of 3) lets the overfit signal drown in the `eps_heldout`
   noise margin and silently re-arms the self-graded exam on the train axis.

## Inputs

| Input | Required | Notes |
|---|---|---|
| Target file | yes | Any prompt / skill / instruction file (path) |
| Development direction | yes | Free text or a file: what the agent should get better at, failure stories, OCC-collected experience, etc. |
| Prior golden set | no | If supplied → say clearly: "update mode is v2; this run creates a fresh v1 set" and stop rather than silently half-updating |

## Pipeline

### Step 0 — Preflight

- **Locate agent-coach**: resolve `../agent-coach/` relative to this skill.
  Missing → stop with a clear error (declared co-location dependency); do not
  improvise a substitute Runner/Grader.
- **Resolve the production ruler**: find the target's `run-config.json` and
  read `runner.model` / `runner.temperature` / `runner.max_output_tokens`.
  If there is no run-config, the fallback order is **codified — never
  improvise, never silently default**:
  1. **Interactive session** → **ask the user** for the real production
     model + temperature (offer to scaffold from
     `examples/en/run-config.example.json`).
  2. **Non-interactive run** (headless / CI / subagent — no human to ask) →
     scaffold from `examples/en/run-config.example.json`, mark the ruler
     `[ASSUMED — production model unconfirmed]` in the RUNLOG ruler record,
     and **void the run's discrimination claims**: verified-failing flags
     measured at an assumed ruler are non-authoritative, the runbook must say
     so next to the saturation warning, and `calibrate_noise` at the real
     ruler is the judge.
  Why: a wrong ruler makes "verified failing" cases pass at the real baseline
  and the drafted set arrives saturated — and an *improvised* fallback hides
  exactly the assumption the human most needs to see.
- **Tool/network dependence**: if the target's run-config has
  `tools.mode != "none"`, or the target text plainly requires tools/network to
  answer, the tool-free Runner cannot faithfully execute it → plan to skip
  expose for those cases and tag them `baseline-excluded` (no discrimination
  claim).

### Step 1 — Case language (production language, not file language)

Run `scripts/scan_inputs.py` to collect language signals in priority order:
`failure-log.jsonl` → user-provided sample logs → run-config context. An
existing `golden-set.json` for this target is only an *incidental* extra
signal (scanned for language only — its presence does NOT trigger the
update-mode message; that fires only when the user supplies a prior set as
input). If no signal exists, **ask the user**. Never infer the case language
from the target file's own prose — this very repo is the counterexample
(agent-coach's instructions are English; its real usage is Korean). Cases in
the wrong language measure an agent nobody runs.

### Step 2 — Council (proposer → adversary → arbiter, ≤ 3 rounds)

Spawn each actor as a **separate subagent** with its own file as the prompt —
separation must be real (clean contexts), not nominal:

- `agents/gsd-proposer.md` — drafts ≥8 train candidates (input + 5–7 criteria
  each, ≥1 negative/guard criterion) and ≥4 held-out candidate **inputs only**
  (probe dimension + realism flags). All case text in the Step-1 language.
- `agents/gsd-adversary.md` — attacks the proposal against the golden-set
  anti-patterns, including the **anti-T4 twin-check** (held-out inputs must
  differ from train in scenario surface AND probe dimension). Objections only.
- `agents/gsd-arbiter.md` — rules each objection (`fix-required` /
  `accept-risk` / `reject` / `escalate`), loops back at most twice (3 rounds
  total), declares consensus. Unresolved items are not silently dropped — they
  go into the RUNLOG and runbook.

### Step 3 — Expose failure (train only)

Source the actor prompts in this order: **(1) the co-located originals**
`../agent-coach/agents/{runner,grader}.md`; **(2)** if agent-coach is not
co-located (standalone install), the byte-copies bundled at
`agents/vendored/{runner,grader}.md` — and disclose the fallback in the
RUNLOG (`actor_source: "vendored"`). A drift-guard test keeps the copies
byte-identical to the originals wherever both exist. Spawn each as a generic
subagent whose prompt is that file's content:

- **Runner** subagents: model pinned to `runner.model` from the run-config;
  execute the target on each **train** candidate. Temperature note: this
  harness pins model per subagent but has **no per-agent temperature
  parameter** — the temperature requirement travels as prose. That is not a
  defect of this skill: agent-coach runs its Runner/Grader through the *same
  mechanism*, so the ruler matches at the mechanism level (model-faithful,
  temperature-prose on **both** sides). Disclose this in the RUNLOG; the
  final authority on discrimination is agent-coach's own `calibrate_noise`.
- **Grader** subagents: grade each output against that candidate's **shipping
  train rubric** (temp-0 semantics per the grader prose). A case the target
  fails here is a case that starts the loop below ceiling — mark it
  `verified_failing`.
- **Held-out candidates are never run.** There is no rubric to grade against
  (by design), and showing the human a model output next to an input anchors
  the rubric they are about to write. Held-out earns its keep through realism
  and coverage diversity, not a manufactured failure signal.
- Tool-dependent targets: skip this step entirely; tag affected cases
  `baseline-excluded` and say so in the runbook.

### Step 4 — Curate + size floor

Prefer verified-failing train candidates. If **fewer than 5 fail**, top up to
5 with the highest-probe non-failing candidates and record `top_up:[ids]` in
the RUNLOG plus a near-ceiling warning in the runbook — `calibrate_noise`
will render the final verdict. Never emit fewer than 5 train / 3 held-out;
never abort just because the target is strong. Do not pad rubrics to hit
"5–7" — a vague filler criterion injects grading noise and dulls the gate
(the 5–7 range is guidance for *intentional* criteria, and the emitter warns
rather than blocks outside it).

### Step 5 — Emit (deterministic)

Compose the runbook sections **in the Step-1 case language** following
`assets/runbook-template.md` (the 10 honest limitations must be rendered
faithfully and completely — the emitter counts the numbered items). Then call:

```bash
printf '%s' '<payload JSON>' | python3 scripts/emit_draft.py
```

The emitter validates every invariant in Hard-rule #2, writes
`golden-set.json` (+ `cases/*.input.txt` for file-backed inputs),
`GOLDEN-SET-DRAFT-README.md` (runbook + machine appendix), and
`GOLDEN-SET-DRAFT-RUNLOG.json` (council rounds, ruler record, top-ups,
exclusions, next step). See the payload schema in the script's docstring.

### Step 6 — Hand off, and stop

Tell the user, plainly: this is a **draft**. Their next steps (also in the
runbook): review — and freely replace — the held-out *inputs* (limitation #1),
author **all** held-out rubrics using `references/heldout-rubric-guide.md`,
run agent-coach's `op=split` (the first run is *supposed* to fail with the
empty-rubric error listing exactly the held-out ids — that error is the gate
working), fill, re-run to freeze, and let agent-coach's calibration judge
whether the set is usable. Your job ends at the draft + directions. Do not
"helpfully" freeze, fill, or pre-run any of it.

## The 10 honest limitations (surface these; never hide them)

1. Held-out **inputs** are still AI-drafted — the deepest residual; the
   runbook recommends human review/replacement (not enforced).
2. Train input **and** rubric are AI-authored — technically anti-pattern #1 on
   the train axis, weaker than agent-coach Bootstrapper's "human owns all
   rubrics" contract; a conscious v1 trade sealed by the human-owned held-out
   + S1 HALT. Invariant: weaken "all held-out human" and this reignites.
3. Rubric **quality** is not enforceable — code blocks only *empty*; a lazy
   one-liner passes. Mitigation: the authoring guide at the gate.
4. Authenticity is unprovable — the gate forces the *act* of authoring, not
   the thought behind it. Accepted residual while §5-2 holds.
5. Consumer-side bypass (`require_rubric:false`, retiring cases) belongs to
   agent-coach's layer — this skill can only advise against it.
6. Satisfiability is **delegated, not guaranteed** — agent-coach's
   `calibrate_noise` loudly rejects a flat set; nothing fails silently.
7. No gate opt-out exists in v1 — the gate is the only structural S5 defense;
   the dangerous handle already lives (deliberately) in agent-coach's layer.
8. Expose-failure is a heuristic, train-only; the harness pins model, carries
   temperature as prose on both sides, and defers authority to calibration.
9. §5-2: this skill never drafts held-out rubrics — one click would collapse
   the design into a self-graded exam.
10. Held-out inputs cannot be both AI-failure-signaled and train-decorrelated
    — so they are chosen for realism + coverage diversity and carry **no**
    discrimination claim; the human rubric + (advisory) calibration judge them.

## Bundled files

| File | Purpose |
|---|---|
| `agents/gsd-proposer.md` | Council drafter: train cases + held-out inputs (strict JSON) |
| `agents/gsd-adversary.md` | Council attacker: anti-pattern + anti-T4 objections |
| `agents/gsd-arbiter.md` | Council judge: rulings, round cap, consensus |
| `agents/vendored/{runner,grader}.md` | Byte-copies of agent-coach's Runner/Grader for standalone installs (co-located originals win; drift-guard tested) |
| `scripts/emit_draft.py` | Deterministic emitter — invariants, artifacts, RUNLOG |
| `scripts/scan_inputs.py` | Language-signal collector (mechanical hints only) |
| `scripts/tests/` | Unit + integration tests (real `split_goldenset.py` round-trip) |
| `references/heldout-rubric-guide.md` | The guide handed to the human at the gate |
| `assets/runbook-template.md` | Section-by-section runbook authoring template (incl. canonical 10 limitations) |

## Data formats

The emitted `golden-set.json` follows agent-coach's schema **exactly**;
authority: `../agent-coach/references/data-formats.md` §4.4. Emitted values in
v1: `version:"v1"`, `parent_version:null`, `min_size:{train:5,heldout:3}`,
`provenance:"bootstrap"` on every case, plus true-origin tags —
`["ai-input","ai-rubric"]` on train, `["ai-input","human-rubric"]` on held-out
(`"bootstrap"` alone would read as "AI input + human rubric", the
Bootstrapper's meaning; the tags keep limitation #2 visible in the data).
