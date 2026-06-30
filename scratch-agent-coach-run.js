export const meta = {
  name: 'agent-coach-run',
  description: 'Run the agent-coach measured self-improvement loop for ONE config (calibration + N turns, deterministic python gates) and return history, scores, diff, timing.',
  phases: [
    { title: 'Load' },
    { title: 'Calibrate' },
    { title: 'Loop' },
    { title: 'Finalize' },
  ],
}

const A = (typeof args === 'string' ? JSON.parse(args) : (args || {}))
const DIR = A.dir                                   // absolute working dir
const SCRIPTS = A.scripts                           // absolute agent-coach/scripts dir
const VARIANT = A.variant || 'run'
const RUNNER = A.runner || 'sonnet'
const GRADER = A.grader || 'opus'
const PROPOSER = A.proposer || 'sonnet'
const PLUMB = 'sonnet'                              // model for mechanical python/file agents
const N_TURNS = A.nTurns || 8
const K_CALIB = A.kCalib || 5
const NO_PROGRESS_K = A.noProgressK || 3
const SUB_EVERY = A.subEvery || 3
if (!DIR || !SCRIPTS) throw new Error('args.dir and args.scripts are required')

const r4 = (x) => Math.round(x * 10000) / 10000
const mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length
const trunc = (s, n) => (s ? (s.length > (n || 80) ? s.slice(0, n || 80) + '…' : s) : '')
const numberedRubric = (rb) => rb.map((r, i) => `${i}. ${r}`).join('\n')

const LOADER_SCHEMA = { type: 'object', properties: {
  prompt: { type: 'string' },
  cases: { type: 'array', items: { type: 'object', properties: {
    id: { type: 'string' }, split: { type: 'string' }, input: { type: 'string' },
    rubric: { type: 'array', items: { type: 'string' } } }, required: ['id', 'split', 'input', 'rubric'] } }
}, required: ['prompt', 'cases'] }
const GRADER_SCHEMA = { type: 'object', properties: {
  results: { type: 'array', items: { type: 'object', properties: {
    criterion_index: { type: 'number' }, passed: { type: 'boolean' } }, required: ['criterion_index', 'passed'] } },
  passed: { type: 'number' }, total: { type: 'number' } }, required: ['results', 'passed', 'total'] }
const PROPOSER_SCHEMA = { type: 'object', properties: {
  wrote: { type: 'boolean' }, kind: { type: 'string' }, rationale: { type: 'string' }, before_preview: { type: 'string' } },
  required: ['wrote', 'kind', 'rationale'] }
const VERIFY_SCHEMA = { type: 'object', properties: {
  ok: { type: 'boolean' }, reason: { type: 'string' }, candidate_text: { type: 'string' } }, required: ['ok'] }
const COMPARE_SCHEMA = { type: 'object', properties: {
  decision: { type: 'string' }, confirm_required: { type: 'boolean' }, confirmed: { type: 'boolean' }, reason: { type: 'string' } },
  required: ['decision'] }
const CALIB_SCHEMA = { type: 'object', properties: {
  eps_train: { type: 'number' }, eps_heldout: { type: 'number' }, gate_satisfiable: { type: 'boolean' },
  warnings: { type: 'array', items: { type: 'string' } } }, required: ['eps_train', 'eps_heldout'] }

function runnerPrompt(prompt, input) {
  return `You are the RUNNER in a measurement loop. Execute the TARGET PROMPT faithfully on the INPUT, exactly as in production. Return ONLY the target's output text — no preamble, no commentary, no self-evaluation. You have no tools; if the target would call a tool, produce the text it would produce without one.

===== TARGET PROMPT (system / instructions) =====
${prompt}

===== INPUT (the user turn) =====
${input}`
}
function graderPrompt(output, rubric, caseId) {
  return `You are the GRADER, deterministic (temperature 0). Score the OUTPUT against each rubric criterion INDEPENDENTLY, yes/no. For a NEGATIVE criterion ("did NOT ..."), passed=true means the output AVOIDED the bad behavior. Judge ONLY what the rubric asks; add nothing. You do not know whether this is a before or after run — score the text as written.

===== OUTPUT TO SCORE =====
${output}

===== RUBRIC (one yes/no per line, in order) =====
${numberedRubric(rubric)}

Return ONLY this JSON: {"case_id":"${caseId}","results":[{"criterion_index":<0-based int>,"passed":<bool>}, ... exactly one per criterion in order],"passed":<count of true>,"total":<number of criteria>}.`
}
function proposerPrompt(prompt, failures, mode) {
  const kind = mode === 'subtraction' ? 'subtraction' : 'edit'
  const failText = failures.length
    ? failures.map((f, i) => `${i + 1}. [${f.reason}] rationale="${trunc(f.rationale, 100)}"`).join('\n')
    : '(none yet)'
  const modeInstr = mode === 'subtraction'
    ? `This is a SUBTRACTION turn: propose REMOVING one existing rule you most suspect is dead weight (unused / redundant / counterproductive). "after" MUST be "before" with that rule cleanly EXCISED — introduce no new wording.`
    : `Propose ONE small, targeted EDIT or addition that fixes a rubric weakness and should GENERALIZE to unseen cases (not memorize the train cases). Prefer a precise instruction over vague exhortation.`
  return `You are the PROPOSER in agent-coach. Propose EXACTLY ONE change to the target prompt below. ${modeInstr}

Hard rules:
- "before" must be a substring that occurs EXACTLY ONCE in the target, copied VERBATIM (every character, whitespace, punctuation, line break).
- Keep it LOCAL — mechanically enforced: a too-big change is REJECTED UNMEASURED (the whole turn is wasted). The verifier passes ONLY if EITHER the after-vs-before size ratio is <= 0.5, OR the addition is <= 60 chars AND <= 10 tokens. So to ADD an instruction, pick a "before" that is a LARGE verbatim block (a whole paragraph or several adjacent lines) and append your short clause to it — the wide anchor makes the addition a small fraction. NEVER anchor on a few words and bolt on a long sentence (that reads as a non-local rewrite and is rejected).
- Do NOT repeat any idea already in the FAILURE LOG.

Then DO EXACTLY THIS:
1. Use the Write tool to create the file "${DIR}/_change.json" with valid JSON (properly escape newlines/quotes in the strings):
   {"target_file":"${DIR}/prompt.current.md","before":<your verbatim before string>,"after":<your after string>,"kind":"${kind}"}
2. Return ONLY: {"wrote":true,"kind":"${kind}","rationale":"<1-2 sentences: which rubric weakness this targets and why it generalizes>","before_preview":"<first ~40 chars of before>"}.

===== TARGET PROMPT =====
${prompt}

===== FAILURE LOG (do NOT repeat) =====
${failText}`
}
function verifyApplyPrompt() {
  return `Mechanical step, NO judgment. Do EXACTLY this and return the result:
1. Run via Bash: python3 ${SCRIPTS}/verify_change.py ${DIR}/_change.json
2. If its stdout JSON has "ok": false → return {"ok":false,"reason":<the reason>,"candidate_text":""} and STOP.
3. Else read ${DIR}/_change.json, then use the Write tool to create ${DIR}/_apply.json with:
   {"op":"apply","current_file":"${DIR}/prompt.current.md","before":<before from _change.json>,"after":<after from _change.json>,"candidate_file":"${DIR}/prompt.candidate.md","kind":<kind from _change.json>}
4. Run via Bash: python3 ${SCRIPTS}/apply_change.py ${DIR}/_apply.json
5. If THAT stdout has "ok": false → return {"ok":false,"reason":<reason>,"candidate_text":""}.
6. Else Read ${DIR}/prompt.candidate.md and return {"ok":true,"reason":"applied","candidate_text":<the FULL verbatim contents of prompt.candidate.md>}.`
}
function comparePrompt(payloadObj) {
  return `Mechanical step, NO judgment. (1) Use the Write tool to create ${DIR}/_cmp.json with EXACTLY this JSON: ${JSON.stringify(payloadObj)}
(2) Run via Bash: python3 ${SCRIPTS}/score_compare.py ${DIR}/_cmp.json
(3) Return the stdout JSON object verbatim (it has: decision, confirm_required, confirmed, reason).`
}
function calibPrompt(samples, baseline) {
  const payload = { samples, baseline, min_eps: 0.02 }
  return `Mechanical step. (1) Use the Write tool to create ${DIR}/_calib.json with EXACTLY: ${JSON.stringify(payload)}
(2) Run via Bash: python3 ${SCRIPTS}/calibrate_noise.py ${DIR}/_calib.json
(3) Return the stdout JSON (fields: eps_train, eps_heldout, gate_satisfiable, warnings).`
}
function promotePrompt() {
  return `Mechanical step. (1) Use the Write tool to create ${DIR}/_promote.json with EXACTLY: {"op":"promote","current_file":"${DIR}/prompt.current.md","candidate_file":"${DIR}/prompt.candidate.md","confirmed":true}
(2) Run via Bash: python3 ${SCRIPTS}/apply_change.py ${DIR}/_promote.json
(3) Return the stdout JSON.`
}
function loaderPrompt() {
  return `Mechanical step, NO judgment. (1) Read ${DIR}/prompt.current.md . (2) Read ${DIR}/golden-set.json and for EVERY case whose "status" is "active" (missing status = active) collect {id, split, the inline "input" string, the "rubric" array}. Return JSON {"prompt":<full verbatim contents of prompt.current.md>, "cases":[{"id","split","input","rubric"} ... for ALL active cases]}. Include every active case; do not truncate any input or rubric.`
}
function finalizePrompt(history, failures) {
  const hLines = history.map((h) => JSON.stringify(h)).join('\n')
  const fLines = failures.map((f) => JSON.stringify(f)).join('\n')
  return `Mechanical step. (1) Use the Write tool to create ${DIR}/history.jsonl with this exact content:
${hLines}
(2) Use the Write tool to create ${DIR}/failure-log.jsonl with this exact content:
${fLines}
Return "written".`
}

async function measure(prompt, cases, phaseLabel, tag) {
  const outputs = await parallel(cases.map((c) => () =>
    agent(runnerPrompt(prompt, c.input), { label: `run:${tag}:${c.id}`, phase: phaseLabel, model: RUNNER })))
  const scores = await parallel(cases.map((c, i) => () => {
    const out = outputs[i] == null ? '' : outputs[i]
    return agent(graderPrompt(out, c.rubric, c.id), { label: `grade:${tag}:${c.id}`, phase: phaseLabel, model: GRADER, schema: GRADER_SCHEMA })
      .then((s) => {
        const total = (s && s.total) ? s.total : c.rubric.length
        let passed = (s && typeof s.passed === 'number') ? s.passed : 0
        if (passed < 0) passed = 0
        if (passed > total) passed = total
        return { case_id: c.id, split: c.split, passed, total }
      })
  }))
  const acc = { train: { p: 0, t: 0 }, heldout: { p: 0, t: 0 } }
  for (const s of scores) { if (acc[s.split]) { acc[s.split].p += s.passed; acc[s.split].t += s.total } }
  return {
    train: acc.train.t > 0 ? acc.train.p / acc.train.t : 0,
    heldout: acc.heldout.t > 0 ? acc.heldout.p / acc.heldout.t : 0,
    scores,
  }
}

// ---------------- Load ----------------
phase('Load')
const loaded = await agent(loaderPrompt(), { label: `load:${VARIANT}`, phase: 'Load', model: PLUMB, schema: LOADER_SCHEMA })
if (!loaded || !loaded.cases || loaded.cases.length < 8) throw new Error('loader returned too few cases: ' + (loaded ? loaded.cases && loaded.cases.length : 'null'))
let currentPrompt = loaded.prompt
const cases = loaded.cases
const startPrompt = currentPrompt
log(`loaded ${cases.length} cases (train ${cases.filter((c) => c.split === 'train').length} / heldout ${cases.filter((c) => c.split === 'heldout').length})`)

// ---------------- Calibrate ----------------
phase('Calibrate')
const trainSamples = [], heldSamples = []
for (let k = 0; k < K_CALIB; k++) {
  const m = await measure(currentPrompt, cases, 'Calibrate', `cal${k + 1}`)
  trainSamples.push(r4(m.train)); heldSamples.push(r4(m.heldout))
  log(`calib ${k + 1}/${K_CALIB}: train=${m.train.toFixed(3)} held=${m.heldout.toFixed(3)}`)
}
const baseline = { train: r4(mean(trainSamples)), heldout: r4(mean(heldSamples)) }
const calib = await agent(calibPrompt({ train: trainSamples, heldout: heldSamples }, baseline),
  { label: 'calibrate', phase: 'Calibrate', model: PLUMB, schema: CALIB_SCHEMA })
const eps_train = calib && typeof calib.eps_train === 'number' ? calib.eps_train : 0.02
const eps_heldout = calib && typeof calib.eps_heldout === 'number' ? calib.eps_heldout : 0.02
log(`baseline train=${baseline.train} held=${baseline.heldout} | eps_train=${eps_train} eps_heldout=${eps_heldout} | gate_satisfiable=${calib ? calib.gate_satisfiable : '?'}`)
if (calib && calib.gate_satisfiable === false) {
  await agent(finalizePrompt([], []), { label: 'finalize', phase: 'Finalize', model: PLUMB })
  return { variant: VARIANT, stopReason: 'gate_unsatisfiable', baseline, eps_train, eps_heldout, warnings: calib.warnings || [], history: [], failures: [], startPrompt, finalPrompt: currentPrompt, n_merges: 0 }
}

// ---------------- Loop ----------------
phase('Loop')
let before = { train: baseline.train, heldout: baseline.heldout }   // carry-over seed
const history = [], failures = []
let noProgress = 0, stopReason = null
for (let turn = 1; turn <= N_TURNS; turn++) {
  const mode = (turn % SUB_EVERY === 0) ? 'subtraction' : 'merge'
  const prop = await agent(proposerPrompt(currentPrompt, failures, mode), { label: `propose:t${turn}`, phase: 'Loop', model: PROPOSER, schema: PROPOSER_SCHEMA })
  if (!prop || !prop.wrote) {
    failures.push({ turn, result: 'discarded', rationale: prop ? prop.rationale : '(none)', reason: 'proposer produced no change' })
    noProgress++; history.push({ turn, mode, decision: 'DISCARD', reason: 'no proposal', train_before: r4(before.train), heldout_before: r4(before.heldout) })
    if (noProgress >= NO_PROGRESS_K) { stopReason = 'no_progress'; break } else continue
  }
  const va = await agent(verifyApplyPrompt(), { label: `verify:t${turn}`, phase: 'Loop', model: PLUMB, schema: VERIFY_SCHEMA })
  if (!va || !va.ok || !va.candidate_text) {
    failures.push({ turn, result: 'discarded', rationale: prop.rationale, reason: 'verify/apply rejected: ' + (va ? va.reason : 'null') })
    noProgress++; history.push({ turn, mode, decision: 'DISCARD', reason: 'verify rejected', train_before: r4(before.train), heldout_before: r4(before.heldout), rationale: prop.rationale })
    if (noProgress >= NO_PROGRESS_K) { stopReason = 'no_progress'; break } else continue
  }
  const candidatePrompt = va.candidate_text
  const after = await measure(candidatePrompt, cases, 'Loop', `t${turn}a`)
  const base = { train_b: before.train, train_a: r4(after.train), held_b: before.heldout, held_a: r4(after.heldout), eps_train, eps_heldout, mode }
  let cmp = await agent(comparePrompt(base), { label: `compare:t${turn}`, phase: 'Loop', model: PLUMB, schema: COMPARE_SCHEMA })
  let decision = cmp ? cmp.decision : 'DISCARD'
  let confirmAfter = null
  if (cmp && cmp.confirm_required && (decision === 'MERGE' || decision === 'SUB_KEEP')) {
    const a2 = await measure(candidatePrompt, cases, 'Loop', `t${turn}c-cand`)
    const b2 = await measure(currentPrompt, cases, 'Loop', `t${turn}c-base`)
    confirmAfter = a2
    cmp = await agent(comparePrompt({ ...base, train_a2: r4(a2.train), held_a2: r4(a2.heldout), train_b2: r4(b2.train), held_b2: r4(b2.heldout) }),
      { label: `confirm:t${turn}`, phase: 'Loop', model: PLUMB, schema: COMPARE_SCHEMA })
    decision = cmp ? cmp.decision : 'DISCARD'
  }
  const row = { turn, mode, decision, train_before: r4(before.train), train_after: r4(after.train), heldout_before: r4(before.heldout), heldout_after: r4(after.heldout), eps_train, eps_heldout, rationale: prop.rationale }
  if ((decision === 'MERGE' || decision === 'SUB_KEEP') && cmp && cmp.confirmed) {
    await agent(promotePrompt(), { label: `promote:t${turn}`, phase: 'Loop', model: PLUMB })
    currentPrompt = candidatePrompt
    before = { train: confirmAfter ? r4(confirmAfter.train) : r4(after.train), heldout: confirmAfter ? r4(confirmAfter.heldout) : r4(after.heldout) }
    noProgress = 0
    history.push(row)
    log(`turn ${turn}: ${decision} (train ${row.train_before}->${row.train_after}, held ${row.heldout_before}->${row.heldout_after})`)
  } else if (decision === 'HALT') {
    history.push(row); failures.push({ turn, result: 'halted', rationale: prop.rationale, reason: cmp ? cmp.reason : 'overfit' })
    stopReason = 'HALT'; log(`turn ${turn}: HALT (overfit) — terminal`); break
  } else {
    history.push(row); failures.push({ turn, result: 'discarded', rationale: prop.rationale, reason: cmp ? cmp.reason : 'discard' })
    noProgress++
    log(`turn ${turn}: ${decision} (train ${row.train_before}->${row.train_after}, held ${row.heldout_before}->${row.heldout_after})`)
    if (noProgress >= NO_PROGRESS_K) { stopReason = 'no_progress'; break }
  }
  if (before.train >= 0.999 && before.heldout >= 0.999) { stopReason = 'perfect'; break }
}
if (!stopReason) stopReason = `n_turns(${N_TURNS})`

// ---------------- Finalize ----------------
phase('Finalize')
await agent(finalizePrompt(history, failures), { label: 'finalize', phase: 'Finalize', model: PLUMB })
const n_merges = history.filter((h) => h.decision === 'MERGE' || h.decision === 'SUB_KEEP').length
return { variant: VARIANT, stopReason, baseline, eps_train, eps_heldout, n_merges, history, failures, startPrompt, finalPrompt: currentPrompt }
