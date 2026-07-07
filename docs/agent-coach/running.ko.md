# 루프 실행하기

> 이것은 Claude Code 스킬이므로 **자연어로 구동**합니다 — 사용자는 루프의 매 반복 *안*이 아니라
> 루프 *위*(시험과 설정을 설계하는 자리)에 앉습니다. 정상 사용에서 스크립트를 직접 호출하지
> 않고, 오케스트레이터가 호출합니다. 사용자의 단 하나의 되돌릴 수 없는 행동은 맨 마지막에
> 있습니다: 스테이징된 결과를 **커밋하거나 되돌리는 것**.

이 페이지는 실행을 처음부터 끝까지 따라갑니다 — 시작(kickoff), 매 턴에 스킬이 하는 일, 세 가지
실전 시나리오, 중단된 실행 재개, 골든셋이 아직 없을 때의 콜드 스타트 경로, 그리고 비용. *시험*은
[`golden-set.ko.md`](./golden-set.ko.md), *설정*은 [`run-config.ko.md`](./run-config.ko.md)를
보세요.

---

## 빠른 시작

전형적인 시작은 문장 하나면 됩니다:

> "`./prompts/summarizer.md`를 `golden-set.json`의 케이스들에서 점수가 더 잘 나오도록
> 튜닝해줘(train과 held-out은 이미 표시돼 있어). 단, **무엇이든 바꾸기 전에 먼저 측정**하고,
> 정말로 도움이 될 때만 변경을 유지해 — 과적합은 하지 마. 설정은 `run-config.json`에 있어."

이 스킬은 예시 케이스에 대해 프롬프트를 최적화/튜닝/강화하거나 실패율을 낮추려는 요청, 또는
eval·골든셋 기반 루프를 세팅하려는 요청에 자동으로 발동합니다 — 사용자가 "루프"라는 단어를 한 번도
쓰지 않아도요. 스킬은 다음을 수행합니다:

1. **사전 점검** 설정 검증을 실행하고 결정론적 코어를 검증합니다.
2. 무엇이든 제안하기 *전에* train + held-out에서 **베이스라인**을 측정합니다.
3. 게이트가 적용된 루프를 돌립니다 — 턴당 한 변경, **스테이징 전용**.
4. 마지막에 **배치(batch)**를 제시합니다 — 디프(시작 vs 후보), `history.jsonl`(점수 추이),
   `failure-log.jsonl`(시도하고 버린 것) — 사용자가 **커밋**(실제 파일에 대한 최초이자 유일한
   쓰기)하거나 **되돌리도록(revert)**.

**이 루프는 반(半)자율적입니다: 모든 변경마다 승인을 요청하지 *않습니다*.** 사용자는 루프의 매
반복 *안*에 있는 것이 아니라 루프 *위*(루프를 설계하는 자리)에 앉습니다. 최종 종단간(end-to-end)
QA — 결과를 실제로 *사용해 보는 것* — 은 사용자의 몫으로 남습니다. 골든셋 점수 통과는 필요조건이지
충분조건이 아닙니다.

### 결정론적 코어 검증

어떤 실행이든 신뢰하기 전에, 모든 되돌릴 수 없는 결정을 내리는 그 코드를 먼저 검증하세요:

```bash
python3 skills/agent-coach/scripts/tests/run.py          # 219개 테스트, 표준 라이브러리만 사용
# 또는:  python3 -m pytest skills/agent-coach/scripts/tests/
```

모든 스크립트는 JSON 페이로드를 **stdin**(또는 파일 경로 인자)으로 읽습니다 — 절대로 인라인 argv
문자열이 아닙니다:

```bash
printf '%s' '<json>' | python3 skills/agent-coach/scripts/score_compare.py
```

(스크립트는 저장소 루트에서 실행하세요 — 경로는 이 `docs/` 페이지가 아니라 프로젝트 루트
기준입니다.)

---

## 시나리오별 사용법

아래 세 가지 시나리오 유형은 스킬 자체의 종단간 eval([`../../skills/agent-coach/evals/evals.json`](../../skills/agent-coach/evals/evals.json))과
대응됩니다.

### 시나리오 1 — 웜 스타트 (이미 골든셋이 있는 경우)

**가진 것:** 대상 파일 + `train`/`heldout`이 이미 표시된 `golden-set.json`.

> "`./prompts/summarizer.md`를 `golden-set.json` 케이스에서 점수가 더 잘 나오게 튜닝해줘 — 단,
> **무엇이든 바꾸기 전에 먼저 측정**하고, 정말 도움이 될 때만 유지해. 과적합 금지. 설정은
> `run-config.json`."

**동작:** 설정 검증 → train + held-out 베이스라인 측정 → 게이트 적용 루프(턴당 한 변경, 스테이징
전용) → 노이즈를 이기고 확인 재실행을 통과한 변경만 병합 → 디프 + `history.jsonl` +
`failure-log.jsonl`을 제시해 **커밋/되돌리기** 선택. 커밋 전까지 실제 파일은 그대로입니다.

### 시나리오 2 — 콜드 스타트 (골든셋이 아직 없는 경우)

**가진 것:** 대상 + (있다면) 원시 로그 더미, 하지만 **라벨된 테스트셋 없음**.

> "`classify.md`가 내 고객지원 티켓 분류기인데 자꾸 오분류해. 더 좋게 만들어줘. 테스트셋은 없고
> `seed-logs.txt`에 원시 수신함 줄들만 있어. 설정은 `run-config.json`."

**동작:** 골든셋이 없음을 감지(스스로 만들어 자가 채점하지 **않음**) → **부트스트래퍼**가 후보
*입력* 초안 작성 → 실제 실패를 드러내려 대상을 한 번 실행 → **사람 게이트에서 정지**하고 입력
큐레이션과 yes/no 루브릭 작성을 요청하며 크기 게이트(`train ≥ 5`, `heldout ≥ 3`)도 상기시킴.
큐레이션을 마친 뒤에야 최적화 루프가 실행됩니다. 전체 경로는 아래
[콜드 스타트](#콜드-스타트-골든셋이-아직-없을-때)에 자세히 있습니다.

### 시나리오 3 — 과적합 방어 (일반화를 깨는 솔깃한 변경)

**가진 것:** 대상 + 골든셋, 그리고 "그냥 항상 X 하게 하면 되지" 같은 뻔한 수정 아이디어.

> "채용공고 필드 추출기 `extract.md`를 `golden-set.json`에 맞춰 튜닝해줘. 큰 문제:
> `salary_range`를 너무 자주 null로 둬 — 채워줬으면 해. 설정은 `run-config.json`."

**동작:** 자연스러운 "항상 급여 채우기" 변경은 **train**을 올리지만 **held-out**(급여를 명시하지
않은 공고)을 깨므로, 코드가 **HALT**를 반환 — 변경은 대상에 닿지 않습니다. 정지된 시도와
`candidate_input`(다음 골든셋 버전용 케이스)이 기록됩니다. 프롬프트가 조용히 환각을 학습하는
것으로부터 보호됩니다.

---

## 중단된 실행 재개

모든 실행은 재개 가능합니다. 중단되면 `state.json`이 턴과 단계를 기록하고, `resume.py`가 마지막으로
완료된 단계부터 **멱등하게** 재진입합니다 — 병합은 절대 이중 적용되지 않습니다.

> "`summarizer.md`에 대한 agent-coach 실행을 멈춘 지점부터 이어서 해줘."

샘플 `state.json`(`history.jsonl`, `failure-log.jsonl`과 함께)이
[`../../examples/agent-coach/loop-state/`](../../examples/agent-coach/loop-state)에 있어, 재개 가능한 상태 기계가 정확히 무엇을
기록하는지 볼 수 있습니다.

---

## 콜드 스타트: 골든셋이 아직 없을 때

골든셋이 없으면 루프는 스스로 하나를 지어내 그것에 채점하지 **않습니다** — 그것은 자가 채점 시험이
될 테니까요. 이 상태는 *결정론적으로* 감지됩니다(`split_goldenset.py op=state`가
`missing`/`empty` 반환). 그다음:

1. **씨앗(Seed)**: 로그가 있으면 거기서 입력을 가져오고, 그리고/또는 **부트스트래퍼**가 입력
   *후보*를 초안 작성합니다. 로그가 쉽거나 해피패스(happy-path)뿐이라면, 로그가 있어도
   부트스트래퍼를 돌리세요 — 비위 맞추는 셋은 아무것도 못 찾습니다.
2. **실패 노출**: 후보에 대해 대상을 한 번 실행(Runner)해서 실제로 어디서 실패하는지 드러냅니다.
3. **사람이 큐레이션**: *사용자가* 입력을 승인/가지치기하고 누락된 어려운 케이스를 추가합니다.
   사용자는 루브릭만이 아니라 입력 선택까지 직접 맡습니다 — 이것이 상관된 사각지대(correlated
   blind spots)를 차단합니다.
4. **사람이 루브릭 작성**: *사용자가* yes/no 기준을 작성합니다(입력당 5~7개).
5. **분할(Split)**: `split_goldenset.py`가 큐레이션 *이후에* train/held-out을 나누되, **가장
   현실적인** 항목을 홀드아웃에 두고 분할을 고정(해시)합니다.
6. **크기 게이트**: `train < 5` 또는 `heldout < 3`이면 거부하거나 강하게 경고합니다.

루프는 사람 큐레이션 게이트에서 멈춰 입력 승인과 루브릭 작성을 요청합니다 — 셋을 조용히 확정해
거기에 최적화하지 않습니다. 큐레이션할 *무엇*을 고르는 craft는 그 자체로 한 페이지입니다:
[`golden-set.ko.md`](./golden-set.ko.md)를 보고, 부트스트래퍼가 무엇을 하고 무엇을 하지 않는지는
[`../../skills/agent-coach/agents/bootstrapper.md`](../../skills/agent-coach/agents/bootstrapper.md)를 보세요.

---

## 한 번의 실행 비용

한 턴의 대략적 비용:

```
Runner (현재 + 후보 검증 + 확인) × 셋 크기
  + Grader (동일) + Proposer (1)
  ≈ |train| = 5, |held| = 3 일 때 승격(promote) 턴에서 모델 호출 약 65회
    (확인 단계가 후보 AND 현재/베이스라인 프롬프트를 둘 다 재실행 — H4 재측정)
  ≈ 비승격 턴은 약 33회 (DISCARD/HALT는 확인 생략)
  + k_calib 보정 실행 (콜드 스타트 시 1회)
```

예산은 **일급 제약(first-class constraint)**입니다: `run-config.json`에 `budget.max_usd_total`과
`budget.max_usd_per_turn`을 설정하세요. 총비용은 `n_turns`와 골든셋 크기로 조절하며, 루프는
`state.json`에서 `budget_spent_usd`를 추적하다가 상한에 닿으면 멈춥니다.

---

## 더 보기

- [`golden-set.ko.md`](./golden-set.ko.md) — 루프가 채점하는 시험 만들기(당신이 소유한 가장
  강력한 지렛대).
- [`run-config.ko.md`](./run-config.ko.md) — 모든 `run-config.json` 필드와, 정직한 측정을
  강제하는 사전 점검.
- [`../../skills/agent-coach/references/safety-invariants.md`](../../skills/agent-coach/references/safety-invariants.md)
  — S1–S7: 병합 게이트·홀드아웃 HALT·스테이징이 존재하는 이유.
- [`../../skills/agent-coach/references/loop-concepts.md`](../../skills/agent-coach/references/loop-concepts.md)
  — 모든 설계 선택의 배경 원칙.
