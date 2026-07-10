# golden-set-drafter — golden set이 없을 때, 초안을 대신 만들어 주는 동반 스킬

> **agent-coach로 프롬프트를 개선하고 싶은데 golden set이 아직 없다면, 이 스킬이 먼저 실행됩니다.**
> 대상 파일과 발전 방향 문서로부터 golden set 첫 버전(v1)의 초안을 만들어 줍니다. 단,
> **held-out 채점 기준만은 절대 쓰지 않고** 사용자 몫으로 남겨 둡니다. 일부러 남겨 둔 그
> 공란이 이 설계에서 가장 중요한 안전장치입니다.
> English version: [`golden-set-drafter.md`](./golden-set-drafter.md)

이 스킬이 따르는 규칙 전체(스킬 계약서): [`skills/golden-set-drafter/SKILL.md`](../../skills/golden-set-drafter/SKILL.md)

---

## 무엇을 하는 스킬인가

`golden-set-drafter`는 [agent-coach](../agent-coach/running.ko.md)의 동반 스킬입니다.
agent-coach는 golden set(시험지)이 있어야 돌 수 있는데, golden set 규칙을 아직 모르는 사용자가
처음부터 직접 만들기는 어렵습니다. 이 스킬이 그 무거운 부분을 세 단계로 대신합니다:

1. **회의체 초안.** proposer(제안), adversary(공격), arbiter(판정)라는 AI 세 역할이
   케이스 입력과 train 쪽 채점 기준을 놓고 토론합니다. 한쪽이 제안하면, 한쪽이 반박하고,
   한쪽이 판정합니다. 그 토론에서 살아남은 것만 초안에 들어갑니다.
2. **실패 노출.** 모든 train 케이스를 **실제 대상 파일 + 실제 운영 모델**로 한 번씩 돌려
   보고, 그 결과를 증거로 붙입니다: "지금 프롬프트가 이 케이스를 정말 틀리는가?" (이
   확인은 train 전용입니다. held-out 입력은 절대 실행하지 않으므로, 누구도 그것을 미리
   들여다볼 수 없습니다.)
3. **확정 전(미동결) 출력.** 나오는 것은 완성본이 아니라 **초안**입니다. held-out 채점
   기준은 전부 공란이고, `split_hash`도 없습니다. 그 공란을 사람이 채우도록 agent-coach의
   코드 게이트가 강제합니다.

golden set이 없는 상황이라면, 올바른 순서는 이 스킬을 agent-coach보다 먼저, agent-coach 대신
실행하는 것입니다.

## 무엇을 주어야 하는가 (입력)

필수 입력 2개, 선택 입력 1개입니다:

| 입력 | 필수 | 설명 |
|---|---|---|
| **대상 파일** | 예 | golden set을 만들어 줄 프롬프트/스킬/지시문 파일의 경로. 예: `./agents/support-agent.md`. |
| **발전 방향** | 예 | 대상이 *무엇을 더 잘하게 되어야 하는가*: 목표, 실패 사례, 로그, 쌓아 온 경험. 자유 텍스트도 되고 파일도 됩니다(예: `./direction.md`). 회의체가 어떤 케이스를 초안할지 이것이 좌우합니다. |
| **기존 golden set** | 아니오 | 기존 set을 건네면 v1은 "갱신(update/evolve) 모드는 v2 기능"이라고 답하고 **멈춥니다**. 언제나 새 v1만 초안하며, 기존 set을 어중간하게 고치는 일은 절대 하지 않습니다. |

또한 대상의 `run-config.json`을 자동으로 읽어 **운영 모델 + temperature**를 맞춥니다.
이것이 train 실패를 잴 때 쓰는 "잣대(측정 기준)"입니다. 잣대가 틀리면 초안이 포화된 채로
나와서, 전부 멀쩡해 보이고 아무것도 배울 수 없게 됩니다. run-config가 없으면
대화형 세션에서는 실제 모델과 temperature를 **직접 물어보고**, 무인(headless) 실행에서는
기본 틀을 만들어 두되 잣대가 *가정된(assumed)* 값임을 표시합니다. 전체 옵션 레퍼런스:
[run-config](../agent-coach/run-config.ko.md).

## 무엇이 나오는가 (산출물 3개)

| 산출물 | 내용 | 예시 |
|---|---|---|
| `golden-set.json` | train 케이스(입력 + 채점 기준 완성) + held-out 케이스(입력만, **채점 기준은 공란**), 확정 전(미동결) 상태 | [`draft-output/golden-set.example.json`](../../examples/golden-set-drafter/ko/draft-output/golden-set.example.json) |
| `GOLDEN-SET-DRAFT-README.md` | 다음 할 일을 순서대로 담은 안내서(runbook), 사용자의 케이스 용어로 작성: 이후 4단계 + **정직한 한계 10가지** + 정확한 `op=split` 명령이 담긴 "Gate data" 부록 | 기본 틀: [`runbook-template.md`](../../skills/golden-set-drafter/assets/runbook-template.md) |
| `GOLDEN-SET-DRAFT-RUNLOG.json` | 회의체 토론, 사용된 잣대, 실패 노출 결과의 기록 | [`draft-output/GOLDEN-SET-DRAFT-RUNLOG.example.json`](../../examples/golden-set-drafter/ko/draft-output/GOLDEN-SET-DRAFT-RUNLOG.example.json) |

## 왜 held-out 채점 기준은 비어서 나오는가 (설계의 핵심)

held-out은 개선 루프가 절대 "공부"할 수 없는 봉인된 시험이고, 과적합을 잡아내는 유일한
방어선입니다. 그런데 입력을 초안한 바로 그 AI가 그 held-out 케이스들에 대해 "좋은 답이란
무엇인가"까지 정의한다고 상상해 보세요. 시험은 AI가 자기 시험을 자기가 채점하는 구조로
무너집니다. 루프는 그 AI의 사각지대를 향해 최적화되고, 그것을 잡아 줄 장치는 남지
않습니다.

그래서 이 스킬은:

- **held-out 채점 기준을 어떤 형태로도 쓰지 않습니다.** 예시도, 출발점도, "초안만
  살짝"도 거절합니다. 이것은 스킬 계약서(`SKILL.md`)의 5-2절에 명시된 규칙이며, 예외가
  없습니다. 이 거절 자체가 안전 설계의 일부입니다.
- 강제는 **코드**에 맡깁니다. held-out 채점 기준이 하나라도 비어 있으면, golden set을
  분할·동결하는 agent-coach 명령인 `op=split`이 실패하고, 에러 메시지에 비어 있는
  케이스 id를 정확히 나열합니다. 그 에러가
  곧 게이트입니다. 실제로 캡처한 실행 결과가
  [`gate-first-run.example.json`](../../examples/golden-set-drafter/ko/gate-first-run.example.json)에
  있습니다.

## 실행 방법

Claude Code 스킬이므로 자연어로 시작합니다:

> "`./agents/support-agent.md`를 개선하고 싶은데 golden set이 아직 없어. 발전 방향은
> `./direction.md`에 있어. golden set 초안부터 만들어줘."

초안을 만들고 나면 스킬은 **게이트 앞에서 멈춥니다**. 그다음은 사용자의 4단계입니다(함께
나온 runbook이 사용자의 케이스 용어로 하나씩 안내합니다):

1. held-out **입력**을 검토합니다. AI가 초안한 것이므로, 실제 운영에서 들어올 요청처럼
   보이지 않는 것은 교체하세요.
2. **held-out 채점 기준을 전부 직접 씁니다.** 이 단계의 가이드는
   [`heldout-rubric-guide.md`](../../skills/golden-set-drafter/references/heldout-rubric-guide.md)입니다.
   요약하면: 각 기준은 temperature 0 채점자가 일관되게 답할 수 있는 예/아니오 질문이어야
   하고, 케이스당 5~7개를 의도를 갖고 고르고, "지어내지 않았는가" 가드를 최소 1개 넣고,
   기준끼리 서로 독립이어야 하고, 모델이 실제로 할 수 있는 범위 안이어야 하고, 정답
   하나를 못 박는 대신 좋은 답의 성질을 적어야 합니다. 그리고 가드 기준은 한 케이스에
   몰지 말고 여러 케이스에 걸쳐 배치합니다.
3. runbook의 "Gate data" 부록에 있는 **`op=split` 명령을 실행합니다**. 첫 실행은 **실패하는
   것이 정상**입니다. 위에서 설명한 게이트가 제 역할을 하고 있다는 뜻입니다.
4. 공란을 다 채운 뒤 다시 실행하면 set이 **동결**됩니다(내용이 잠겨 확정됩니다). 그다음은
   agent-coach의 보정이 이 set으로 측정이 가능한지 판정하고,
   [개선 루프](../agent-coach/running.ko.md)가 이어받습니다.

## 범위와 정직한 한계

- **v1은 새 set 초안 전용입니다.** 기존 golden set을 입력으로 주면 "갱신 모드는 v2 예정"임을
  밝히고 **멈춥니다**. 어중간한 갱신은 절대 하지 않습니다.
- 실패 노출 증거는 **train 전용의 참고 지표**입니다. 이 set이 실제로 쓸 만한지, 즉 좋고
  나쁨을 가려낼 수 있는지 아니면 이미 전부 통과해 포화됐는지의 최종 판정자는 agent-coach의
  보정 단계입니다.
- train은 입력과 채점 기준 모두 AI가 작성하는데, 이것은 알면서 감수한 v1의 절충입니다.
  그 위험은 사람이 소유한 held-out 채점 기준과, 과적합이 확인되면 실행을 중단하는
  agent-coach의 안전 규칙 S1(HALT)이 막아 줍니다.
- 함께 나오는 모든 runbook에는 **정직한 한계 10가지 전문**이 실립니다. 출력을 만드는 코드가
  번호 항목 수를 직접 세고, 10개보다 적으면 runbook 생성을 거부합니다.

## 더 보기

| 문서 | 내용 |
|---|---|
| [`skills/golden-set-drafter/SKILL.md`](../../skills/golden-set-drafter/SKILL.md) | 스킬 계약서 전문 (작업 단계와 규칙; held-out 채점 기준 작성을 거부하는 5-2절 포함) |
| [`heldout-rubric-guide.md`](../../skills/golden-set-drafter/references/heldout-rubric-guide.md) | 게이트 앞에 선 사람을 위한 채점 기준 작성 가이드 |
| [`examples/golden-set-drafter/`](../../examples/golden-set-drafter/ko/draft-output/golden-set.example.json) | 산출물 예시 (`ko/` / `en/` 대칭) |
| [`../agent-coach/golden-set.ko.md`](../agent-coach/golden-set.ko.md) | golden set 만들기 일반론. 이 스킬이 준거로 삼는 문서 |
| [`../agent-coach/running.ko.md`](../agent-coach/running.ko.md) | 동결 이후 이어지는 개선 루프 실행법 |
