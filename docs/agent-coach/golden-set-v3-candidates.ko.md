# Golden set v3 후보 — 보류(DEFERRED) (2026-06-25 패널 리뷰 기준 기록)

> *English: [`golden-set-v3-candidates.md`](./golden-set-v3-candidates.md)*

이 스킬을 자기 자신에게 적용해 시험할 때 쓰는(이른바 dogfood) golden set은 **v2로 동결**된
상태이고, 이 페이지의 내용은 **아무것도 적용되지 않았습니다.** 이 페이지는 각 후보
변경안을 *지금 적용하지 않기로 한 이유와 함께* 기록해 둡니다. 나중에 유지보수하는 사람이
같은 함정을 처음부터 다시 밟지 않도록 하기 위해서입니다.

## 후보 1 — `dashboard-slow` c4(rubric 인덱스 3)의 문구 강화

("c4"는 `dashboard-slow` 케이스의 4번째 채점 기준을 뜻합니다. JSON에서는 `rubric[3]`,
즉 배열 인덱스 3입니다.)

**현재 문구 (v2, `golden-set.json` → dashboard-slow `rubric[3]`):**
> "Did it AVOID asserting a specific root cause not in the report (e.g. 'N+1 query', 'missing index')?"

**제안된 강화 문구.** 의미 기준의 경계로 작성했고, 금지어 목록이 *아닙니다*. 금지어
목록은 "the culprit is…", "stems from…"처럼 목록에 없는 표현으로 쉽게 우회되기
때문입니다:
> "Did it AVOID stating a specific mechanism as the confirmed cause of the slowdown (e.g. flatly asserting it IS caused by an N+1 query, or IS due to a missing index — examples, not an exhaustive list)? Framing a mechanism as a hypothesis or candidate to investigate is fine; this criterion FAILS only when an output presents one specific mechanism as the established cause."

### 지금 적용하지 않는 이유 (함정)

- **이 기준은 train 시험에 남은 마지막 개선 여지입니다.** 현재 train 점수는 29/30
  (0.9667)이고, held-out은 이미 1.0으로 포화되어 있습니다. c4 문구를 느슨하게 만들면
  유일하게 틀리고 있는 항목(dashboard-slow의 인덱스 3)이 안정적인 PASS로 바뀌고 →
  train이 30/30 = 1.0이 되어 → 병합 게이트가 **통과 불가능**해집니다
  (`train_after ≥ train_before + eps`가 다시는 성립할 수 없음). 이것은 golden set **v1**을
  은퇴시켰던 바로 그 "아무것도 측정할 수 없음" 실패와 같습니다.
- **동결·검증이 끝난 set을 건드릴 명분이 없습니다.** 실무에서 c4는 이미 수용 가능한
  수준으로 채점되고 있습니다. 2026-06-25에, 이전 판정을 모르는 상태에서 독립적으로
  채점한(블라인드) 채점자가 5개의 보정 출력 전부에서 인덱스 3을 통과(5/5)시켰습니다.
  동결·검증된 golden set은 실제 사용자 가치가 있을 때만 수정해야 합니다. "문구가 더 깔끔해질
  수 있다"는 그런 가치가 아닙니다.

### 측정-우선(MEASURE-FIRST) 규칙 (이 후보를 나중에 적용하려 할 때의 관문)

1. 고정된 채점자(`version_id` 2026-06-19)로 **라이브** dashboard-slow 출력의 인덱스 3을
   다시 채점해서, 그것이 정말 29/30의 개선 여지인지 확인합니다. 이 기준은 채점자에 따라
   판정이 실제로 갈립니다: 2026-06-23에 다른 모델 계열의 채점자로 교차 확인했을 때는
   인덱스 3이 **FAIL**이었고, 2026-06-25에 보정 출력을 측정했을 때는 **PASS**였습니다.
   그 불일치야말로 언젠가 문구를 강화할 가치가 있는 이유이자, 동시에 확인 없이 바꾸면
   위험한 이유입니다.
2. 라이브 인덱스 3이 FAIL이라면(즉 그것이 그 개선 여지라면), 더 어려운 "지어내기 축"
   케이스를 추가해 train 점수가 1.0 아래로 내려오도록 먼저 포화를 풀고, 그 후에야 문구를
   강화하세요. 그러지 않으면 게이트가 통과 불가능해집니다.
3. 대기 중인 "인덱스 5 / 형식 비포화" 후보와 **묶어서 처리하지 마세요.** 그 후보는 서로
   무관한 축(출력 형식)에 부담을 주는 것이라 c4의 상한을 풀어 주지 못하고, 안전 규칙
   S5에 따라 새 케이스를 사람이 직접 골라 다듬어야 하는 부담도 따로 생깁니다.

### 바탕에 깔린 채점자 불일치의 진짜 안전망

인덱스 3에 대한 세션 간 판정 불일치는 실재합니다. 하지만 그 안전망은 c4 문구 강화가
아니라 **자동 감시 장치**, 즉 서로 다른 모델 계열의 채점자 둘(dual judge)에게 같은 출력을
채점시키고 판정이 갈리면 경보를 울리는 장치(이른바 cross-family tripwire)입니다.
그 첫 단계로, 동작은 바꾸지 않고 판정 불일치를 기록만 하는
경고(`scripts/check_cross_validation.py`)가 2026-06-25에 출시되었습니다. 판정을 실제로 비교해 조치까지 하는 본체
자동화(comparator)는 포화가 풀린 진단 set이 마련될 때까지 의도적으로 보류(HOLD)
상태입니다(참고: `.omc/specs/agent-coach-dualjudge-diagnostic.md`).
