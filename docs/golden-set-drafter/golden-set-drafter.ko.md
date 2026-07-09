# golden-set-drafter — 골든셋이 없을 때, 초안을 대신 만들어 주는 동반 스킬

> **agent-coach로 프롬프트를 개선하고 싶은데 골든셋이 아직 없다면, 이 스킬이 먼저 실행됩니다.**
> 대상 파일(+ 발전 방향 문서)에서 골든셋 v1 초안을 만들어 주되, **held-out 채점표만은
> 절대 쓰지 않고** 사람 몫으로 남깁니다 — 그 공란이 이 설계의 핵심 안전장치입니다.
> English version: [`golden-set-drafter.md`](./golden-set-drafter.md)

스킬 본체(계약 전문): [`skills/golden-set-drafter/SKILL.md`](../../skills/golden-set-drafter/SKILL.md)

---

## 무엇을 하는 스킬인가

`golden-set-drafter`는 [agent-coach](../agent-coach/running.ko.md)의 동반 스킬입니다.
agent-coach는 골든셋(시험지)이 있어야 돌 수 있는데, 골든셋 규칙을 모르는 사용자가 처음부터
직접 만들기는 어렵습니다. 이 스킬은 그 무거운 부분을 대신합니다:

1. **회의체 초안** — proposer(제안) → adversary(공격) → arbiter(판정) 3자 회의체가
   케이스 입력과 train 채점표를 적대적으로 다듬어 합의에 도달할 때까지 반복합니다.
2. **실패 실측(expose)** — train 케이스를 **실제 대상 프롬프트에 실제 운영 모델로**
   돌려서, "현재 프롬프트가 정말 실패하는 케이스"인지 실측 증거를 답니다(train 전용
   휴리스틱 — held-out은 절대 실행하지 않습니다. 앵커링 방지).
3. **미동결 방출** — 완성본이 아니라 **초안**을 방출합니다: held-out 채점표 전원 공란,
   `split_hash` 없음. agent-coach의 코드 게이트가 사람 작성을 강제합니다.

골든셋이 없는 상태에서는 agent-coach **보다 먼저, 그 대신** 이 스킬이 실행되는 것이
올바른 순서입니다.

## 무엇이 방출되는가 (산출물 3개)

| 산출물 | 내용 | 예시 |
|---|---|---|
| `golden-set.json` | train(입력+채점표 완성) + held-out(입력만, **채점표 공란**), 미동결 | [`draft-output/golden-set.example.json`](../../examples/golden-set-drafter/ko/draft-output/golden-set.example.json) |
| `GOLDEN-SET-DRAFT-README.md` | 케이스 언어로 쓰인 런북: 다음 단계 4개 + **정직한 한계 10가지** + Gate data 부록(정확한 op=split 명령) | 골격: [`runbook-template.md`](../../skills/golden-set-drafter/assets/runbook-template.md) |
| `GOLDEN-SET-DRAFT-RUNLOG.json` | 회의체·자(ruler)·expose 기록 | [`draft-output/GOLDEN-SET-DRAFT-RUNLOG.example.json`](../../examples/golden-set-drafter/ko/draft-output/GOLDEN-SET-DRAFT-RUNLOG.example.json) |

## 왜 held-out 채점표는 비어서 나오는가 (설계의 핵심)

held-out은 개선 루프가 절대 "공부"하지 못하는 봉인된 시험 — 과적합을 잡는 유일한
방어선입니다. 그런데 **입력을 초안한 그 AI가 "무엇이 좋은 답인지"까지 정의하면**, 시험
전체가 자기가 낸 시험을 자기가 채점하는 구조로 무너집니다. 루프는 AI 자신의 사각지대를
향해 최적화하고, 그것을 잡을 장치가 사라집니다.

그래서 이 스킬은:

- held-out 채점표를 **어떤 형태로도 쓰지 않습니다** — 예시·시작점·"초안만"도 거절합니다
  (§5-2, 예외 없음. 거절 자체가 안전장치입니다).
- 대신 agent-coach의 `op=split`이 **코드로** 사람 작성을 강제합니다: 채점표가 빈 채로
  실행하면 해당 id를 정확히 나열하며 실패합니다. 그 에러가 게이트입니다 — 실제 캡처
  출력: [`gate-first-run.example.json`](../../examples/golden-set-drafter/ko/gate-first-run.example.json).

## 실행 방법

Claude Code 스킬이므로 자연어로 시작합니다:

> "`./agents/support-agent.md`를 개선하고 싶은데 골든셋이 아직 없어. 발전 방향은
> `./direction.md`에 있어. 골든셋 초안부터 만들어줘."

방출이 끝나면 스킬은 **게이트 앞에서 멈춥니다**. 이후는 사람의 4단계입니다(방출된 런북이
케이스 언어로 안내합니다):

1. held-out **입력** 검토 — AI 초안이므로, 실제 프로덕션 요청처럼 보이지 않으면 교체.
2. held-out **채점표 전부 직접 작성** —
   [`heldout-rubric-guide.md`](../../skills/golden-set-drafter/references/heldout-rubric-guide.md)
   (이항/temp-0 · 5~7개 의도된 기준 · 가드 ≥1 · 상호 독립 · 천장 안 · 정답 아닌 기준 ·
   가드 짝은 케이스를 가로질러).
3. 런북의 Gate data 부록에 있는 **op=split 명령 실행** — 첫 실행은 실패하는 것이
   정상입니다(위 게이트).
4. 다 채운 뒤 재실행해 **동결** — 이후는 agent-coach의 캘리브레이션이 세트의 사용
   가능성을 판정하고, [개선 루프](../agent-coach/running.ko.md)가 이어받습니다.

## 범위와 정직한 한계

- **v1은 새 세트 생성 전용**입니다. 기존 골든셋을 입력으로 주면 "update/evolve 모드는
  v2 예정"임을 밝히고 **정지**합니다 — 절대 반쯤 갱신하지 않습니다.
- expose 실측은 **train 전용 휴리스틱**입니다. 세트가 실제로 쓸 만한지(변별력/포화)의
  최종 권위는 agent-coach의 캘리브레이션입니다.
- train은 입력·채점표 모두 AI 작성입니다(의식적 v1 트레이드) — 사람 소유 held-out
  채점표 + S1 과적합 HALT가 이를 봉인합니다.
- 방출되는 모든 런북에는 **정직한 한계 10가지 전문**이 포함됩니다(항목 수를 emit 코드가
  세어 강제합니다).

## 더 보기

| 문서 | 내용 |
|---|---|
| [`skills/golden-set-drafter/SKILL.md`](../../skills/golden-set-drafter/SKILL.md) | 스킬 계약 전문 (단계·규칙·§5-2) |
| [`heldout-rubric-guide.md`](../../skills/golden-set-drafter/references/heldout-rubric-guide.md) | 게이트 앞의 사람을 위한 채점표 작성 가이드 |
| [`examples/golden-set-drafter/`](../../examples/golden-set-drafter/ko/draft-output/golden-set.example.json) | 방출물 예시 (`ko/` / `en/` 미러) |
| [`../agent-coach/golden-set.ko.md`](../agent-coach/golden-set.ko.md) | 골든셋 craft 일반론 — 이 스킬이 준거하는 문서 |
| [`../agent-coach/running.ko.md`](../agent-coach/running.ko.md) | 동결 이후 이어지는 개선 루프 실행법 |
