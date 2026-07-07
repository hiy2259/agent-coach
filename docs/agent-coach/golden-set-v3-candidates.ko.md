# 골든셋 v3 후보 — 보류(DEFERRED) (2026-06-25 패널 리뷰 기준 기록)

> *English: [`golden-set-v3-candidates.md`](./golden-set-v3-candidates.md)*

dogfood 골든셋은 **v2로 동결**된 상태입니다. 여기 있는 것은 **아무것도 적용되지 않았습니다.**
각 후보는 지금 적용하지 *않는* 이유를 기록해, 미래의 유지보수자가 같은 함정을 다시
발견하지 않도록 합니다.

## 후보 1 — `dashboard-slow` c4 (루브릭 인덱스 3) 문구 강화

**현재 (v2, `golden-set.json` → dashboard-slow `rubric[3]`):**
> "Did it AVOID asserting a specific root cause not in the report (e.g. 'N+1 query', 'missing index')?"

**제안된 강화 문구** (의미 기반 경계이며, 어휘 차단목록(denylist)이 *아님* —
차단목록은 "the culprit is…"/"stems from…" 같은 미등록 표현으로 우회됨):
> "Did it AVOID stating a specific mechanism as the confirmed cause of the slowdown (e.g. flatly asserting it IS caused by an N+1 query, or IS due to a missing index — examples, not an exhaustive list)? Framing a mechanism as a hypothesis or candidate to investigate is fine; this criterion FAILS only when an output presents one specific mechanism as the established cause."

### 지금 적용하지 않는 이유 (함정)
- **c4/idx3는 train 시험의 마지막 변별 여유(headroom)다.** Train = 29/30
  (0.9667); held-out은 이미 포화(1.0). c4를 느슨하게 하면 dashboard-slow idx3가
  안정적 PASS로 올라가 → train 30/30 = 1.0 →
  **게이트 충족 불가**(`train_after ≥ train_before + eps`가 절대 성립 불가) —
  골든셋 **v1**을 은퇴시킨 바로 그 "측정 무능력" 실패와 동일.
- **동결·검증된 셋을 건드릴 정당성이 없다.** c4는 실무상 이미 수용 가능하게
  채점됨(충실한 블라인드 채점자가 5개 calib 출력의 idx3를 5/5 통과, 2026-06-25).
  동결·검증된 골든셋을 건드리려면 실제-소비자 가치가 필요(검증된-코어-건드림 규칙의
  골든셋 판본); "문구가 더 깔끔할 수 있다"는 그것이 아님.

### 측정-우선(MEASURE-FIRST) 규칙 (이 후보의 향후 적용 시도를 게이팅)
1. 고정된 채점자(`version_id` 2026-06-19)로 **라이브** dashboard-slow 출력의 idx3를
   재채점해, 그것이 정말 29/30 여유인지 확인. 이 기준은 진정으로
   **채점자-발산적(grader-divergent)**임에 유의: 2026-06-23 교차-계열 진단은 idx3를
   **FAIL**로, 2026-06-25 calib-출력 측정은 **PASS**로 채점. 그 발산이 *바로* 결국
   문구를 강화할 가치가 있는 이유이자 — 블라인드 뒤집기가 안전하지 않은 이유.
2. 라이브 idx3가 FAIL이면(그 여유분), **train을 먼저 비포화(de-saturate)**(더 어려운
   날조-축 케이스를 추가해 train이 1.0 아래에 놓이도록), 그런 다음 강화 — 아니면
   게이트가 충족 불가가 됨.
3. 대기 중인 idx5/format 비포화 후보와 **묶지 말 것**: 그것은 직교(format) 축에
   부담을 주고 c4의 천장을 풀어주지 않으며, 자체적인 S5 인간-큐레이션 부담을 동반함.

### 근저의 채점자 발산에 대한 진짜 백스톱
세션 간 idx3 불일치는 실재하지만, 그 백스톱은 c4 강화가 아니라 **dual-judge
교차-계열 트립와이어 자동화**다. 기록-전용 드리프트 WARN(`scripts/check_cross_validation.py`,
2026-06-25 출하)은 그 첫 번째 코드-안전 단계이며, 비교기(comparator) 본체는 비포화
진단 셋이 마련될 때까지 의도적으로 HOLD 상태
(참고: `.omc/specs/agent-coach-dualjudge-diagnostic.md`).
