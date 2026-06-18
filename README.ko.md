# Loop Optimizer (루프 옵티마이저)

> **프롬프트·스킬·지시문 파일을 *측정 기반* 자기개선 루프로 반복 개선합니다 — 감(感)이 아니라 점수로.**

*다른 언어로 보기: [English](./README.md)*

`loop-optimizer`는 대상 프롬프트/스킬/지시문 파일을 마치 좋은 코치가 선수를 훈련시키듯 다듬는 [Claude Code](https://docs.claude.com/en/docs/claude-code) 스킬입니다(스킬 본체는 [`loop-optimizer/`](./loop-optimizer)에 있습니다):

> **측정한다 → 딱 한 가지만 바꾼다 → 다시 측정한다 → 점수가 정말로 올랐을 때만 유지한다.**

이 스킬을 지배하는 원칙은 **"측정 없는 진화는 없다(no evolution without measurement)"** 입니다. 절대로 감으로 대상을 바꾸지 않습니다. 점수에 근거해서 바꾸고, 그 변경을 유지할지 말지는 *모델의 의견이 아니라 결정론적(deterministic) 코드*가 판단합니다. 여기서의 `MERGE`(병합)는 "모델이 보기에 더 나아 보였다"가 아닙니다. 그것은 **학습(train) 케이스에서 측정 노이즈를 이긴, 홀드아웃(held-out) 케이스에서 일반화를 유지한, 확인 재실행을 통과한, 그리고 사람이 승인하기 전까지는 실제 파일을 단 한 바이트도 건드리지 않은** 단 하나의 고립되고 코드로 검증된 변경입니다.

---

## 목차

- [왜 이 스킬이 필요한가](#왜-이-스킬이-필요한가)
- [무엇이 다른가](#무엇이-다른가)
- [동작 방식](#동작-방식)
  - [네 명의 행위자(actor)](#네-명의-행위자actor)
  - [루프 한 턴(turn)](#루프-한-턴turn)
  - [병합 게이트(핵심)](#병합-게이트핵심)
  - [빼기(subtraction) 턴](#빼기subtraction-턴)
  - [정지 조건](#정지-조건)
- [일곱 가지 안전 불변식(S1–S7)](#일곱-가지-안전-불변식s1s7)
- [사용자가 제공하는 입력](#사용자가-제공하는-입력)
  - [골든셋 프로퍼티별 설명](#골든셋-프로퍼티별-설명)
  - [실행 설정 프로퍼티별 설명](#실행-설정-프로퍼티별-설명)
- [콜드 스타트: 골든셋이 아직 없을 때](#콜드-스타트-골든셋이-아직-없을-때)
- [빠른 시작](#빠른-시작)
- [사용법 시나리오별 예시](#사용법-시나리오별-예시)
- [저장소 구조](#저장소-구조)
- [번들 스크립트](#번들-스크립트)
- [비용](#비용)
- [요구 사항](#요구-사항)
- [더 읽을거리](#더-읽을거리)

---

## 왜 이 스킬이 필요한가

"자기개선(self-improvement)"은 멋지게 들리지만, **측정되지 않는 순간 함정**이 됩니다. 모델이 프롬프트를 고치고, 더 나아졌다고 선언하고, 프롬프트는 감에 따라 서서히 표류합니다 — 때로는 더 나빠지는데도, 아무도 알아채지 못합니다. 이 표류가 실제 실패를 숨기는 세 가지 구체적인 방식이 있습니다:

1. **노이즈를 진보로 착각.** 실사용 temperature에서는 대상의 출력이 실행할 때마다 흔들립니다. "학습 점수 +1"은 순전히 운일 수 있습니다. 그 노이즈 대역 안에서 병합하면 무작위성을 프롬프트에 새겨 넣게 됩니다 — 점수는 슬금슬금 오르는데 프롬프트는 오히려 *나빠집니다*.
2. **과적합(overfitting).** 어떤 변경은 최적화 대상이었던 케이스들의 특이점만 외워버리고 일반화 능력을 조용히 망가뜨릴 수 있습니다 — 전형적인 "학습셋 98%, 운영에서는 고장" 함정입니다.
3. **자가 채점 시험.** 모델에게 "네 변경이 도움이 됐어?"라고 물으면, 방금 그것을 만들어낸 모델은 "그렇다"고 답하도록 편향되어 있습니다. 선수가 자기 경기의 심판을 봐서는 안 됩니다.

`loop-optimizer`는 이 실패 양상 각각을 **기계적으로** 제거하도록 설계되어, "더 낫다(better)"를 의견이 아니라 **측정된 값**(observed quantity)으로 만듭니다.

---

## 무엇이 다른가

| 흔한 "AI가 프롬프트를 개선" 도구 | `loop-optimizer` |
|---|---|
| 변경이 도움이 됐는지 모델이 판단 | **결정론적 코드**가 모든 병합을 판단 — 판단이 아니라 고정된 부등식 |
| 점수 하나로 그것에 최적화 | **학습 + 홀드아웃 분할**; 홀드아웃은 일반화 방어선이며, 과적합은 **HALT(정지)**를 유발 |
| "+1"이면 수용 | 향상은 **보정된 측정 노이즈를 이겨야** 하고 *또한* 확인 재실행을 통과해야 함 |
| 같은 모델이 제안하고 채점 | **네 명의 고립된 행위자** — 제안자 ≠ 채점자 ≠ 실행자 ≠ 부트스트래퍼 |
| 실제 파일을 직접 수정 | **스테이징 전용**; 사용자가 커밋하기 전까지 실제 파일은 한 바이트도 안 바뀜 |
| 규칙은 오직 쌓이기만 함 | **빼기 턴**이 3턴마다 죽은 규칙을 가지치기 |
| 같은 실패 아이디어를 반복 | **실패 로그(failure log)**를 제안자가 다시 읽어 알려진 막다른 길을 회피 |

---

## 동작 방식

### 네 명의 행위자(actor)

가장 중요한 구조적 규칙 하나: **변경을 제안하는 모델은 그것을 채점하는 모델이 아니며, 둘 중 어느 것도 대상을 실행하는 모델이 아니다.** 각 행위자는 [`loop-optimizer/agents/`](./loop-optimizer/agents) 아래에 자기 프롬프트를 가진 별도의 Claude Code 서브에이전트입니다. 그래서 각자 깨끗한 컨텍스트에서 시작하고, 역할 분리가 명목상이 아니라 *실제로* 보장됩니다.

| 행위자 | 역할 | 비고 |
|---|---|---|
| **Runner (실행자)** | 골든 입력에 대해 대상을 실행 → 출력 생성 | 고립됨: 쓰기/네트워크/셸 없음. 골든 입력만 읽음. 이 고립은 **보안 경계**이기도 함 — 임의의 대상 프롬프트가 호스트를 탈취해선 안 됨. 측정 노이즈가 실제와 같도록 사용자의 실제 운영 모델·temperature로 실행. |
| **Grader (채점자)** | 출력을 루브릭(rubric)에 따라 채점 → 항목별 yes/no | **temperature 0** + 버전 고정 → 측정에 분산을 더하지 않음. |
| **Proposer (제안자)** | 정확히 **하나**의 변경을 제안 | 먼저 `failure-log.jsonl`을 읽어 막다른 길 반복을 회피. |
| **Bootstrapper (부트스트래퍼)** | 콜드 스타트용 입력 *후보*를 초안 작성 | 반드시 채점자와 다른 모델이어야 함. |

### 루프 한 턴(turn)

루프는 최대 **N**턴(기본 10) 실행됩니다. 각 턴은 **많아야 한 가지**만 바꾸고, 코드가 게이트를 통과시킵니다:

```
① 실행      Runner(현재 대상, 모든 train+heldout 입력) → 출력들
② 채점      Grader(출력들, 루브릭) → train_before, heldout_before
③ 제안      Proposer → 변경 1개 {target_id, before, after, rationale, kind}
④ 검증      verify_change.py: `before`가 유일하게 일치 + 변경이 국소적(local)
            → 아니면 이번 턴 거부  ("정확히 하나의 국소 변경" 강제)
⑤ 적용      apply_change.py: 스테이징(prompt.candidate.md)에만 기록 —
            실제 대상은 손대지 않음
⑥ 재실행    Runner(후보, 모든 입력) → 출력들
⑦ 재채점    Grader → train_after, heldout_after
⑧ 비교      score_compare.py (코드가 결정): MERGE / DISCARD / HALT
⑨ 확인      MERGE라면: 전체 셋을 한 번 더 재실행 + 재채점; 향상이 유지되어야 함
⑩ 기록      MERGE  → 후보를 현재로 승격 + history.jsonl 추가
            DISCARD→ failure-log.jsonl(+ candidate_input); 실제 파일 유지
            HALT   → 정지 + 경고 + failure-log.jsonl (result: halted)
```

**왜 재채점이 아니라 재실행으로 확인하는가(⑨)?** 채점자는 temperature 0으로 돌기 때문에, *같은 텍스트*를 재채점하면 동일한 점수가 나옵니다 — 아무 의미 없는 동작입니다. 진짜 노이즈는 **실행자(Runner)**가 실행할 때마다 다른 출력을 내는 데서 옵니다. 그래서 병합은 *대상을 다시 실행해서* 새 출력을 재채점하는 방식으로 확인합니다. 향상이 증발하면 그것은 노이즈였습니다.

### 병합 게이트(핵심)

판단은 모델이 아니라 [`score_compare.py`](./loop-optimizer/scripts/score_compare.py)가 내립니다. 변경은 **다음이 모두 성립할 때만 MERGE 됩니다:**

```
train_after   >  train_before                      (엄격히 양(+)의 향상 — +0.0 동점은 절대 병합 안 함)
train_after   ≥  train_before   + eps_train        (학습에서 측정 노이즈를 이긴 향상)
heldout_after ≥  heldout_before − eps_heldout       (홀드아웃에서 실질적 퇴행 없음)
그리고 확인 재실행(⑨) 후에도 향상이 유지됨
```

그 외의 경우:

- `train`은 오르는데 `heldout`이 `eps_heldout`보다 **더 많이** 떨어지면 → **HALT** (과적합: 변경이 학습셋을 외워버리고 일반화를 망가뜨림). HALT는 종료 상태입니다.
- 그 밖에는 → **DISCARD** (실질 향상 없음; 추가가 되돌려짐).

마진 `eps_train` / `eps_heldout`은 **측정 노이즈**이며, [`calibrate_noise.py`](./loop-optimizer/scripts/calibrate_noise.py)가 보정합니다: 고정된 입력에 대해 실행자를 `k_calib`번(5 이상 권장) 다시 돌리고, 각각 채점해서, 분할별 점수 산포를 도출합니다 — 작은 양수 `min_eps`로 바닥을 깔아서 `+0.0` 동점이 진보처럼 보이는 일을 막습니다. 홀드아웃 마진은 **대칭(symmetric)**입니다(병합 쪽과 HALT 쪽 모두 `eps_heldout`). 그래서 평범한 홀드아웃 노이즈가 거짓 HALT를 유발하지 않습니다.

**먼저 게이트가 만족 가능한지(satisfiable) 확인하세요.** 베이스라인 점수를 `calibrate_noise.py`에 전달합니다. 만약 `gate_satisfiable: false`가 반환되면 — 즉 `eps_train ≥ 1 − baseline_train`이라서 *어떤* 변경도 게이트를 결코 넘을 수 없다면(베이스라인이 이미 ≈1.0인 포화 상태도 여기에 포함) — 루프는 N턴을 낭비하지 않고 **정지하고 경고를 표면화**합니다. 해법은 더 많은 제안이 아니라, 더 크거나 더 어려운 골든셋, 또는 더 높은 `k_calib`입니다.

### 빼기(subtraction) 턴

본능에 맡기면, 프롬프트를 개선하는 누구든 규칙을 **추가**하기만 합니다 — 텍스트에 단서 조항이 계속 쌓여 비대해지고 자기모순에 빠집니다. 그래서 **3턴마다** 루프는 질문을 "무엇을 더할까?"에서 **"무엇을 뺄까?"**로 뒤집습니다: 죽은 것으로 의심되는 규칙 하나를 떼어내고 다시 측정합니다.

- `train_after ≥ train_before − eps_train` **그리고** `heldout_after ≥ heldout_before − eps_heldout`이면 제거를 유지 → `SUB_KEEP` 기록(공짜로 프롬프트가 더 간결해짐) 후 무진보 카운터 초기화.
- 그렇지 않으면 규칙을 복원하고 `SUB_DROP` 기록 후 카운터 증가.

(`SUB_DROP`은 *제거*를 되돌리고, `DISCARD`는 *추가*를 되돌립니다 — 둘은 별개입니다.)

### 정지 조건

루프는 다음 중 먼저 도달하는 것에서 멈춥니다: **N턴 도달** · **K턴 동안 무진보**(기본 3; `MERGE`/`SUB_KEEP` 시 초기화) · **예산 초과**(턴당 또는 총합) · **만점** · **HALT**.

기대했던 점수에 못 미치는 **정체(plateau)는 실패가 아니라 정보입니다**: 지시문 텍스트가 고정된 모델과 도구가 허용하는 천장에 도달했다는 뜻입니다. 더 나아가려면 단어가 아니라 모델을 바꾸거나 도구를 추가해야 합니다. 루프는 헛돌지 않고 정체를 정직하게 보고합니다.

---

## 일곱 가지 안전 불변식(S1–S7)

이 불변식들이 바로 이 스킬이 존재하는 이유입니다. 각각은 "자기개선"이 측정 없는 진화로 조용히 퇴락하는 특정한 한 가지 경로를 제거합니다. 전체 서술: [`references/safety-invariants.md`](./loop-optimizer/references/safety-invariants.md).

| # | 불변식 | 방지하는 것 | 강제 주체 |
|---|---|---|---|
| **S1** | 홀드아웃 분할 + 과적합 시 **HALT** (대칭 `eps_heldout` 마진) | 과적합 변경의 병합 | `split_goldenset.py`, `score_compare.py` |
| **S2** | **코드로 강제된 병합** — 모델의 "더 낫다"가 아님 (게다가 엄격한 `>` 향상) | 희망적 자가 평가 | `score_compare.py` |
| **S3** | **기계적 단일 변경** — 유일한 `before` + 국소성 상한 | 모호하거나 교란된 편집 | `verify_change.py` (`apply_change.py`가 재검증) |
| **S4** | **스테이징** — 사람이 커밋할 때까지 실제 파일 불변 | 실제 프롬프트의 조용한 손상 | `apply_change.py` |
| **S5** | **사람이 관리하는 입력 출처** + 최소 크기 게이트 (`train ≥ 5`, `heldout ≥ 3`) | 자가 채점 / 너무 작은 시험 | 부트스트래퍼 ≠ 채점자, 사람 큐레이션, `split_goldenset.py` |
| **S6** | **실패 로그 피드백** + 제안자 재읽기 | 막다른 길 반복; 정체된 골든셋 | `failure-log.jsonl`, `agents/proposer.md` |
| **S7** | **실행자 분산에서 나온 노이즈 마진** + 확인 재실행/재채점 | 노이즈를 진보로 착각 | `calibrate_noise.py`, 확인 단계 |

이 중 하나라도 빼면 루프는 무의미한 점수를 기어오를 수 있습니다. 일곱 개를 모두 지키면 `MERGE`가 *무언가를 의미*하게 됩니다.

---

## 사용자가 제공하는 입력

모든 작업은 `loop/<target>/` 작업 디렉터리 안에서 일어납니다. 사용자는 세 가지를 제공하며, 각 프로퍼티는 아래에서 항목별로 설명합니다. 기준이 되는 전체 스키마는 [`references/data-formats.md`](./loop-optimizer/references/data-formats.md)에 있습니다.

1. **대상(Target)** — 개선할 실제 프롬프트/스킬/지시문 파일, 예: `./agents/dev-agent.md`. **마지막에 커밋하기 전까지 절대 기록되지 않습니다.**
2. **골든셋(`golden-set.json`)** — **사용자의 몫입니다.** 루프가 채점하는 고정된 시험이며, 대부분의 지렛대 효과가 여기에 있습니다. 없으면 루프가 사용자와 *함께* 만듭니다([콜드 스타트](#콜드-스타트-골든셋이-아직-없을-때) 참고) — 절대로 스스로 만들어 그것에 채점하지 않습니다.
3. **실행 설정(`run-config.json`)** — 대상을 "실사용처럼" 실행하는 방법과 루프·예산 제어를 담습니다.

> **골든셋: 한 번의 실행 *안*에서는 고정, 실행 *사이*에서는 버전 관리.** 루프가 도는 동안 셋과 분할은 고정됩니다(매 턴 `split_hash`를 재확인하며, 실행 중 변경은 오류). 이것이 전후(前後) 점수를 비교 가능하게 만듭니다. 실행 사이에는 *사용자가* 셋을 키우며, 실패에서 파생된 케이스(실패 로그의 `candidate_input`)를 새 `version`에 반영합니다. 점수는 **같은 버전 안에서만** 비교 가능하므로, 모든 `history.jsonl` 행은 자신의 `golden_set_version`을 기록합니다.

### 골든셋 프로퍼티별 설명

골든셋(`golden-set.json`)은 고정된 시험입니다 — **입력 큐레이션과 루브릭 작성은 사람이 직접 맡습니다**(S5). 데이터셋 수준의 **헤더 필드**와 **`cases[]`** 목록으로 구성됩니다. 아래는 완전한 샘플입니다(같은 파일이 복붙용으로 `examples/golden-set/golden-set.example.json`에도 있습니다):

```json
{
  "_note": "포맷 설명용 축약 예시입니다. 실제 골든셋은 min_size(active train≥5 · heldout≥3)를 충족해야 합니다. '_' 접두 필드는 파서가 무시합니다.",
  "target": "./agents/dev-agent.md",
  "version": "v2",
  "parent_version": "v1",
  "created": "2026-06-10",
  "updated": "2026-06-16",
  "changelog": "v1 포화 후 실전에서 드러난 '동시성 버그 미탐지' 실패를 train에 추가(failure-log 유래). 변별력 없던 'print-hello'는 은퇴.",
  "min_size": { "train": 5, "heldout": 3 },
  "cases": [
    {
      "id": "regex-email-fix",
      "split": "train",
      "provenance": "seed",
      "added_in_version": "v1",
      "realistic": true,
      "status": "active",
      "tags": ["regex", "debugging"],
      "notes": "실제 로그에서 자주 나온 정규식 디버깅 요청. 짧은 입력이라 인라인 사용.",
      "input": "이 정규식이 이메일을 제대로 매칭하지 못합니다: ^\\w+@\\w+$ — 무엇이 문제이고 어떻게 고치나요?",
      "rubric": [
        "TLD(.com 등)와 점(.)을 처리하지 못하는 한계를 지적했는가?",
        "동작하는 개선 정규식을 제시했는가?",
        "코드에 없는 가짜 문제를 지어내지 않았는가?"
      ]
    },
    {
      "id": "debug-race-condition",
      "split": "train",
      "provenance": "failure-log",
      "added_in_version": "v2",
      "realistic": true,
      "status": "active",
      "tags": ["debugging", "concurrency"],
      "notes": "v1 에이전트가 실전에서 음수 잔액 버그를 못 잡은 실패에서 유래. 진화(S6 가교)의 대표 사례. 코드 입력이라 input_file 사용.",
      "input_file": "./cases/debug-race-condition.input.txt",
      "rubric": [
        "레이스 컨디션(check-then-act)을 진짜 원인으로 지목했는가?",
        "락 또는 원자적 연산으로 올바르게 고쳤는가?",
        "코드에 없는 가짜 원인을 지어내지 않았는가?",
        "기존 withdraw 시그니처를 깨지 않았는가?",
        "왜 그게 원인인지 한두 줄로 설명했는가?"
      ]
    },
    {
      "id": "review-sql-injection",
      "split": "heldout",
      "provenance": "human",
      "added_in_version": "v1",
      "realistic": true,
      "status": "active",
      "tags": ["code-review", "security"],
      "notes": "실제 PR에서 가져온 현실 케이스 → reality-first 규칙으로 held-out 우선 배치.",
      "input_file": "./cases/review-sql-injection.input.txt",
      "rubric": [
        "SQL 인젝션 취약점을 지적했는가?",
        "파라미터 바인딩(prepared statement) 해법을 제시했는가?",
        "심각도를 적절히(높음) 평가했는가?",
        "존재하지 않는 문제를 날조하지 않았는가?",
        "실제로 동작하는 수정 예시를 보였는가?"
      ]
    },
    {
      "id": "print-hello",
      "split": "train",
      "provenance": "bootstrap",
      "added_in_version": "v1",
      "realistic": false,
      "status": "retired",
      "tags": ["trivial"],
      "notes": "모든 버전이 통과 → 변별력 0. v2에서 은퇴(채점 제외, 기록은 보존). 골든셋 레벨의 '빼기' 예시.",
      "input": "파이썬으로 'hello'를 출력하세요.",
      "rubric": ["hello를 출력하는 코드를 제시했는가?"]
    }
  ]
}
```

**이 샘플이 보여주는 것.** 일부러 *축약된* 예시입니다 — `_note`가 밝히듯 실제 셋은 `min_size`를 충족해야 하지만, 이 샘플은 활성 `train` 2개 + `heldout` 1개뿐이라 `train ≥ 5` / `heldout ≥ 3` 게이트 미만이므로 실제 실행 시 경고가 납니다. 위에서 아래로 읽으면:

- **헤더 블록.** `version: "v2"`는 `parent_version: "v1"`에서 진화했고, `changelog`는 v2가 *왜* 생겼는지 기록합니다: 실전의 동시성 버그 미탐지 실패를 실패 로그에서 가져와 반영하고, 변별력 없는 케이스를 은퇴시켰습니다. `min_size`는 크기 게이트(S5)입니다.
- **`regex-email-fix`** — 짧은 **인라인 `input`**을 가진 `train` 케이스이고 `provenance: "seed"`(실제 로그 유래)입니다. yes/no 기준 3개가 좋은 답을 정의합니다.
- **`debug-race-condition`** — 코드가 **`input_file`**로 파일에 담긴 `train` 케이스이며 `provenance: "failure-log"`: *실전 실패에서 파생*되었습니다(진화의 가교, S6). 루브릭이 모델이 원인을 **지어내지 않는지**까지 검사하는 점에 주목하세요 — 환각 방어입니다.
- **`review-sql-injection`** — **홀드아웃** 케이스입니다. `realistic: true`가 바로 이것이 홀드아웃에 놓인 이유(현실 우선)이며, 루프가 절대 최적화하지 않는 일반화 방어선입니다.
- **`print-hello`** — `status: "retired"`: 모든 버전이 통과해 변별력을 잃었으므로 채점에서는 제외하되 기록은 보존합니다(골든셋 수준의 "빼기").

모든 `rubric`은 5~7개의 평이한 yes/no 기준 — 답 자체가 아니라 좋은 답의 *기준* — 이며, 점수는 **활성** 케이스만 분할별로 집계합니다. 아래에 필드별 상세 레퍼런스가 이어집니다.

**헤더(데이터셋 수준) 필드:**

| 프로퍼티 | 타입 | 필수 | 의미 | 설정 방법 |
|---|---|---|---|---|
| `target` | string | ✔ | 개선할 실제 대상 파일의 상대경로 | 실제 프롬프트/스킬 파일을 가리킴, 예: `./agents/dev-agent.md` |
| `version` | string | ✔ | 골든셋 버전 id; 점수는 **같은 버전 안에서만** 비교 | `"v1"`에서 시작; 실행 사이 셋을 키울 때마다 `"v2"`…로 증가 |
| `parent_version` | string \| null | ✔ | 이 버전이 진화해 나온 부모 버전(계보) | 첫 버전은 `null`, 이후엔 직전 id |
| `created` | date | 권장 | 셋을 처음 만든 날짜 | ISO 날짜, 예: `"2026-06-10"` |
| `updated` | date | 권장 | 마지막으로 편집한 날짜 | 최근 변경의 ISO 날짜 |
| `changelog` | string | 권장 | 부모 버전 대비 무엇이 바뀌었는지 | 한 줄: 추가한 실패 유래 케이스, 은퇴시킨 케이스 |
| `min_size` | object `{train, heldout}` | ✔ | 분할별 최소 **활성** 케이스 수 — 크기 게이트(S5) | 특별한 이유가 없으면 `{ "train": 5, "heldout": 3 }` 유지 |

**케이스 필드(`cases[]`의 각 항목):**

| 프로퍼티 | 타입 | 필수 | 의미 | 설정 방법 |
|---|---|---|---|---|
| `id` | string | ✔ | 버전 간 추적되는 안정적 식별자 | 짧은 슬러그, 예: `"debug-race-condition"`; 다른 케이스에 재사용 금지 |
| `split` | `"train"` \| `"heldout"` | ✔ | 어느 분할인지; **실행 중 고정** | `split_goldenset.py`가 배정하게 하거나 직접 지정 — 가장 현실적인 케이스는 `heldout`에 |
| `input` **또는** `input_file` | string | ✔ (정확히 하나) | 테스트 입력: 인라인 텍스트 **또는** 파일 경로 | 짧은 텍스트 → `input`; 코드/큰 입력 → `input_file: "./cases/<id>.input.txt"` |
| `rubric` | string[] | ✔ | 좋은 답을 정의하는 yes/no 기준 **5~7개** | 평이한 yes/no 질문으로 작성; 답 자체가 아니라 *기준* |
| `provenance` | `"seed"` \| `"bootstrap"` \| `"failure-log"` \| `"human"` | ✔ | 케이스 출처(진화 추적) | `seed`=로그 유래 · `bootstrap`=AI 초안 후보 · `failure-log`=과거 실패 유래 · `human`=사용자 작성 |
| `added_in_version` | string | ✔ | 케이스가 들어온 버전 | 처음 등장한 `version` |
| `realistic` | boolean | ✔ | 실제 운영급 케이스인가? | 실제 케이스는 `true`(우선 held-out 배치); 장난감/합성은 `false` |
| `status` | `"active"` \| `"retired"` | ✔ | `retired`는 채점 제외, 기록은 보존 | 보통 `active`; 변별력 잃은 케이스는 삭제 말고 **은퇴(retire)** |
| `notes` | string | 권장 | 이 케이스가 겨냥하는 능력/실패 | 케이스가 존재하는 이유 한 문장 |
| `tags` | string[] | 선택 | 자유 분류 라벨 | 예: `["debugging", "concurrency"]` |

**설정 시 반드시 지켜야 할 규칙:**

- **채점.** 케이스당 점수 = `(통과한 루브릭 기준 수) / (전체 기준 수)`, **활성 케이스만** 분할별로 집계. 은퇴 케이스는 채점에서 제외하되 이력은 보존.
- **`input` vs `input_file`.** **정확히 하나**만. `input_file`은 **`golden-set.json`이 있는 디렉터리 기준 상대경로** — 관례는 `./cases/` 하위 폴더.
- **현실 우선 held-out.** 가장 어렵고 운영급인 케이스를 `heldout`(`realistic: true`)에 배치. 홀드아웃은 루프가 절대 최적화하지 않는 일반화 방어선입니다.
- **크기 게이트(S5).** 활성 `train ≥ 5`, `heldout ≥ 3` 미만이면 실행을 거부하거나 강하게 경고.

### 실행 설정 프로퍼티별 설명

실행 설정(`run-config.json`)은 **실행자(Runner)**가 대상을 "실사용처럼" 어떻게 돌릴지 지정하고 루프를 제어합니다. 아래는 최소 설정입니다(같은 파일이 복붙용으로 `examples/run-config.example.json`에도 있습니다):

```json
{
  "_note": "런타임/루프 설정 예시. 모델 ID는 실제 사용 값으로 교체하세요. 핵심 규칙: grader != proposer(제안≠채점), runner는 실사용 모델/temp 매칭. '_' 접두 필드는 무시됩니다.",
  "target": "./agents/dev-agent.md",
  "golden_set": "./golden-set.json",
  "runner":   { "model": "claude-opus-4-8", "temperature": 0.7, "max_output_tokens": 4096 },
  "grader":   { "model": "claude-sonnet-4-6", "temperature": 0, "version_id": "2026-06-16" },
  "proposer": { "model": "claude-opus-4-8", "temperature": 0.3 },
  "calibration": { "k_calib": 5 },
  "loop":     { "n_turns": 10, "no_progress_k": 3, "subtraction_every": 3 },
  "budget":   { "max_usd_total": 20.0, "max_usd_per_turn": 3.0 },
  "tools":    { "mode": "none" }
}
```

**이 설정이 지정하는 것.** 블록별로 읽으면:

- **`_note`** 는 파서가 무시하는 사람용 주석입니다(이름이 `_`로 시작하는 필드) — 파일에 메모를 달 때 사용합니다.
- **최상위.** `target`과 `golden_set`은 실제 대상 파일과 그 시험(골든셋)을 가리킵니다 — 둘 다 상대경로.
- **`runner`** 는 `claude-opus-4-8`을 **temperature 0.7**로 사용 — *운영에서 실제로 쓰는 모델·temperature 그대로*라서 루프가 보정하는 노이즈가 진짜 노이즈가 됩니다(인위적으로 조용한 `temperature: 0`이 아님).
- **`grader`** 는 *다른* 모델(`claude-sonnet-4-6`)을 **temperature 0**에 `version_id`를 고정해 사용 — 안정적이고 분산이 0인 잣대입니다. 모델을 다르게 두는 것이 채점을 정직하게 유지합니다(제안 ≠ 채점).
- **`proposer`** 는 `claude-opus-4-8`을 낮은 temperature(**0.3**)로 사용해 집중된 단일 편집을 합니다. 여기서는 마침 runner와 같은 모델이지만 괜찮습니다 — 강제 분리 규칙은 오직 proposer ≠ grader(그리고 bootstrapper ≠ grader)뿐입니다.
- **`calibration.k_calib: 5`** 는 Runner를 5회 재실행해 `eps`를 측정합니다; 5는 권장 하한입니다.
- **`loop`** 는 실행을 10턴으로 제한하고, 무진보 3턴이면 정지하며, 3턴마다 빼기를 시도합니다.
- **`budget`** 는 총 지출을 `$20`, 턴당 지출을 `$3`로 제한합니다 — 둘 중 하나에 닿으면 실행이 멈춥니다.
- **`tools.mode: "none"`** = 순수 텍스트 입출력 대상(v1 기본).

여기엔 `bootstrapper` 블록이 없는데, 이는 웜 스타트이기 때문입니다. 콜드 스타트에서만 — grader와 다른 모델로 — 추가하세요. 아래에 필드별 상세 레퍼런스가 이어집니다.

**필드 레퍼런스(전 블록):**

| 블록 | 프로퍼티 | 타입 | 의미 | 설정 방법 |
|---|---|---|---|---|
| (최상위) | `target` | string | 실제 대상 파일의 상대경로 | 골든셋의 `target`과 같은 파일 |
| (최상위) | `golden_set` | string | `golden-set.json`의 상대경로 | 예: `./golden-set.json` |
| `runner` | `model` | string | 대상을 실행하는 모델 | **실제 운영 런타임과 일치해야** 측정 노이즈가 진짜가 됨 |
| `runner` | `temperature` | number | 실사용 temperature — `eps`의 분산 원천 | 실제 운영 temperature, 예: `0.7` (`0` 아님) |
| `runner` | `max_output_tokens` | number | 각 대상 실행의 출력 상한 | 완전한 답에 충분하게, 예: `4096` |
| `grader` | `model` | string | 채점 모델(실행 내내 고정) | **제안자와 다른** 유능한 모델 |
| `grader` | `temperature` | number | **반드시 `0`** — 채점 분산 0 (S7) | 항상 `0` (아니면 사전 점검이 에러) |
| `grader` | `version_id` | string | 드리프트 감사를 위해 기록하는 고정 id | 날짜나 태그, 예: `"2026-06-16"` |
| `proposer` | `model` | string | 턴당 한 변경을 제안하는 모델 | **`grader.model`과 반드시 달라야 함** (제안 ≠ 채점) |
| `proposer` | `temperature` | number | 집중된 제안을 위한 낮은 temperature | 예: `0.3` |
| `bootstrapper` | `model` | string (선택) | 콜드 스타트에서 후보 입력을 초안 작성 | 콜드 스타트에만 필요; 있으면 **`grader.model`과 달라야 함** |
| `calibration` | `k_calib` | number | 노이즈 보정을 위한 Runner 재실행 횟수 | **≥ 5** (작으면 `eps` 추정이 불안정 → 경고) |
| `loop` | `n_turns` | number | 최대 턴 수 | 기본 `10`; 탐색을 넓히려면 올림(비용도 비례) |
| `loop` | `no_progress_k` | number | `MERGE`/`SUB_KEEP` 없이 K턴이면 정지 | 기본 `3` |
| `loop` | `subtraction_every` | number | N턴마다 빼기 시도 | 기본 `3` |
| `budget` | `max_usd_total` | number | 총 지출 상한(일급 제약) | `n_turns` × 셋 크기로 가늠; 도달 시 정지 |
| `budget` | `max_usd_per_turn` | number | 턴당 지출 상한 | 폭주 턴을 막는 가드레일 |
| `tools` | `mode` | `"none"` \| `"mocked"` | `none` = 텍스트 입출력 대상(v1 기본) | `"none"` 유지; `"mocked"`는 미정세이며 v2 사안 |

**사전 점검(pre-flight).** 턴 1 *이전에* 항상 `validate_config.py`를 실행하세요. 에러가 하나라도 있으면 실행을 정지시킵니다:

- **에러(실행 차단):** `runner`/`grader`/`proposer` 블록 또는 `model` 누락 · `grader.temperature ≠ 0` · `proposer.model == grader.model` · `bootstrapper.model == grader.model`(부트스트래퍼가 있을 때). 모델 id는 대소문자·공백을 무시하고 비교하므로 `"Sonnet"` vs `"sonnet"`로 자가 채점 실행을 우회할 수 없습니다.
- **경고(주의하며 진행):** `runner.temperature == 0`(분산 없음 → `eps`가 바닥으로 붕괴) · `k_calib < 5` · `grader.version_id` 누락 · `budget` 블록 누락.

```bash
printf '%s' '{"config_path":"./run-config.json"}' | python3 loop-optimizer/scripts/validate_config.py
```

---

## 콜드 스타트: 골든셋이 아직 없을 때

골든셋이 없으면 루프는 스스로 하나를 지어내 그것에 채점하지 **않습니다** — 그것은 자가 채점 시험이 될 테니까요. 이 상태는 *결정론적으로* 감지됩니다(`split_goldenset.py op=state`가 `missing`/`empty` 반환). 그다음:

1. **씨앗(Seed)**: 로그가 있으면 거기서 입력을 가져오고, 그리고/또는 **부트스트래퍼**가 입력 *후보*를 초안 작성합니다. 로그가 쉽거나 해피패스(happy-path)뿐이라면, 로그가 있어도 부트스트래퍼를 돌리세요 — 비위 맞추는 셋은 아무것도 못 찾습니다.
2. **실패 노출**: 후보에 대해 대상을 한 번 실행(Runner)해서 실제로 어디서 실패하는지 드러냅니다.
3. **사람이 큐레이션**: *사용자가* 입력을 승인/가지치기하고 누락된 어려운 케이스를 추가합니다. 사용자는 루브릭만이 아니라 입력 선택까지 직접 맡습니다 — 이것이 상관된 사각지대(correlated blind spots)를 차단합니다.
4. **사람이 루브릭 작성**: *사용자가* yes/no 기준을 작성합니다(입력당 5~7개).
5. **분할(Split)**: `split_goldenset.py`가 큐레이션 *이후에* train/held-out을 나누되, **가장 현실적인** 항목을 홀드아웃에 두고 분할을 고정(해시)합니다.
6. **크기 게이트**: `train < 5` 또는 `heldout < 3`이면 거부하거나 강하게 경고합니다.

루프는 사람 큐레이션 게이트에서 멈춰 입력 승인과 루브릭 작성을 요청합니다 — 셋을 조용히 확정해 거기에 최적화하지 않습니다.

---

## 빠른 시작

이것은 Claude Code 스킬이므로 자연어로 구동합니다 — 정상 사용에서는 스크립트를 직접 호출하지 않고, 오케스트레이터가 호출합니다. 전형적인 시작:

> "`./prompts/summarizer.md`를 `golden-set.json`의 케이스들에서 점수가 더 잘 나오도록 튜닝해줘(train과 held-out은 이미 표시돼 있어). 단, **무엇이든 바꾸기 전에 먼저 측정**하고, 정말로 도움이 될 때만 변경을 유지해 — 과적합은 하지 마. 설정은 `run-config.json`에 있어."

이 스킬은 예시 케이스에 대해 프롬프트를 최적화/튜닝/강화하거나 실패율을 낮추려는 요청, 또는 eval·골든셋 기반 루프를 세팅하려는 요청에 자동으로 발동합니다 — 사용자가 "루프"라는 단어를 한 번도 쓰지 않아도요. 스킬은 다음을 수행합니다:

1. **사전 점검** 설정 검증을 실행하고 결정론적 코어를 검증합니다.
2. 무엇이든 제안하기 *전에* train + held-out에서 **베이스라인**을 측정합니다.
3. 게이트가 적용된 루프를 돌립니다 — 턴당 한 변경, 스테이징 전용.
4. 마지막에 **배치(batch)**를 제시합니다 — 디프(시작 vs 후보), `history.jsonl`(점수 추이), `failure-log.jsonl`(시도하고 버린 것) — 사용자가 **커밋**(실제 파일에 대한 최초이자 유일한 쓰기)하거나 **되돌리도록(revert)**.

**이 루프는 반(半)자율적입니다: 모든 변경마다 승인을 요청하지 *않습니다*.** 사용자는 루프의 매 반복 *안*에 있는 것이 아니라 루프 *위*(루프를 설계하는 자리)에 앉습니다. 최종 종단간(end-to-end) QA — 결과를 실제로 *사용해 보는 것* — 은 사용자의 몫으로 남습니다. 골든셋 점수 통과는 필요조건이지 충분조건이 아닙니다.

### 결정론적 코어 검증

어떤 실행이든 신뢰하기 전에, 모든 되돌릴 수 없는 결정을 내리는 그 코드를 먼저 검증하세요:

```bash
python3 loop-optimizer/scripts/tests/run.py          # 145개 테스트, 표준 라이브러리만 사용
# 또는:  python3 -m pytest loop-optimizer/scripts/tests/
```

모든 스크립트는 JSON 페이로드를 **stdin**(또는 파일 경로 인자)으로 읽습니다 — 절대로 인라인 argv 문자열이 아닙니다:

```bash
printf '%s' '<json>' | python3 loop-optimizer/scripts/score_compare.py
```

---

## 사용법 시나리오별 예시

스킬은 자연어로 구동하며, 예시 케이스에 대해 프롬프트를 최적화/튜닝/강화하거나 실패율을 낮추려는 요청에 자동 발동합니다 — "루프"라는 단어를 쓰지 않아도요. 아래 세 가지 시나리오 유형은 스킬 자체의 종단간 eval([`evals/evals.json`](./loop-optimizer/evals/evals.json))과 대응됩니다.

### 시나리오 1 — 웜 스타트 (이미 골든셋이 있는 경우)

**가진 것:** 대상 파일 + `train`/`heldout`이 이미 표시된 `golden-set.json`.

> "`./prompts/summarizer.md`를 `golden-set.json` 케이스에서 점수가 더 잘 나오게 튜닝해줘 — 단, **무엇이든 바꾸기 전에 먼저 측정**하고, 정말 도움이 될 때만 유지해. 과적합 금지. 설정은 `run-config.json`."

**동작:** 설정 검증 → train + held-out 베이스라인 측정 → 게이트 적용 루프(턴당 한 변경, 스테이징 전용) → 노이즈를 이기고 확인 재실행을 통과한 변경만 병합 → 디프 + `history.jsonl` + `failure-log.jsonl`을 제시해 **커밋/되돌리기** 선택. 커밋 전까지 실제 파일은 그대로입니다.

### 시나리오 2 — 콜드 스타트 (골든셋이 아직 없는 경우)

**가진 것:** 대상 + (있다면) 원시 로그 더미, 하지만 **라벨된 테스트셋 없음**.

> "`classify.md`가 내 고객지원 티켓 분류기인데 자꾸 오분류해. 더 좋게 만들어줘. 테스트셋은 없고 `seed-logs.txt`에 원시 수신함 줄들만 있어. 설정은 `run-config.json`."

**동작:** 골든셋이 없음을 감지(스스로 만들어 자가 채점하지 **않음**) → **부트스트래퍼**가 후보 *입력* 초안 작성 → 실제 실패를 드러내려 대상을 한 번 실행 → **사람 게이트에서 정지**하고 입력 큐레이션과 yes/no 루브릭 작성을 요청하며 크기 게이트(`train ≥ 5`, `heldout ≥ 3`)도 상기시킴. 큐레이션을 마친 뒤에야 최적화 루프가 실행됩니다.

### 시나리오 3 — 과적합 방어 (일반화를 깨는 솔깃한 변경)

**가진 것:** 대상 + 골든셋, 그리고 "그냥 항상 X 하게 하면 되지" 같은 뻔한 수정 아이디어.

> "채용공고 필드 추출기 `extract.md`를 `golden-set.json`에 맞춰 튜닝해줘. 큰 문제: `salary_range`를 너무 자주 null로 둬 — 채워줬으면 해. 설정은 `run-config.json`."

**동작:** 자연스러운 "항상 급여 채우기" 변경은 **train**을 올리지만 **held-out**(급여를 명시하지 않은 공고)을 깨므로, 코드가 **HALT**를 반환 — 변경은 대상에 닿지 않습니다. 정지된 시도와 `candidate_input`(다음 골든셋 버전용 케이스)이 기록됩니다. 프롬프트가 조용히 환각을 학습하는 것으로부터 보호됩니다.

### 중단된 실행 재개

모든 실행은 재개 가능합니다. 중단되면 `state.json`이 턴과 단계를 기록하고, `resume.py`가 마지막으로 완료된 단계부터 멱등하게 재진입합니다 — 병합은 절대 이중 적용되지 않습니다.

> "`summarizer.md`에 대한 loop-optimizer 실행을 멈춘 지점부터 이어서 해줘."

---

## 저장소 구조

README는 프로젝트 루트에 있고, 스킬 본체는 `loop-optimizer/`에, 복사해 쓸 수 있는 입력은 `examples/`에 있습니다.

```
.
├── README.md                          # 영문 버전
├── README.ko.md                       # 이 파일 (한글)
├── examples/                          # 복붙 가능한 예시 입력 & 상태
│   ├── run-config.example.json        #   실행 설정 (한글 주석)
│   ├── golden-set/                    #   골든셋 + cases/ (한글 주석)
│   ├── loop-state/                    #   샘플 history / failure-log / state
│   └── en/                            #   위 전체의 영문 미러
│       ├── run-config.example.json
│       ├── golden-set/
│       └── loop-state/
└── loop-optimizer/                    # 스킬 본체
    ├── SKILL.md                       #   Claude Code가 로드하는 스킬 계약 (여기서 시작)
    ├── agents/                        #   네 명의 고립된 행위자 (각자 프롬프트 하나)
    │   ├── runner.md                  #     대상 실행 (샌드박스)
    │   ├── grader.md                  #     출력을 루브릭에 따라 채점 (temperature 0)
    │   ├── proposer.md                #     한 변경 제안; 실패 로그를 읽음
    │   └── bootstrapper.md            #     콜드 스타트 입력 후보 초안
    ├── scripts/                       #   결정론적 코어 — 표준 라이브러리만, 모든 병합을 결정
    │   ├── validate_config.py         #     사전 점검: 행위자 분리, 채점자 temperature 0
    │   ├── verify_change.py           #     ④ 하나의 국소 변경 (유일 before + 국소성)
    │   ├── apply_change.py            #     ⑤/⑩ 스테이징에 기록, 병합 시 승격
    │   ├── score_compare.py           #     ⑧ MERGE / DISCARD / HALT 결정
    │   ├── calibrate_noise.py         #     eps_train / eps_heldout + gate_satisfiable
    │   ├── split_goldenset.py         #     상태 분류 + 셋 분할 & 고정
    │   ├── resume.py                  #     중단 후 멱등(idempotent) 재개
    │   ├── _common.py                 #     공용 헬퍼 (stdin 페이로드, 해싱)
    │   └── tests/                     #     코어에 대한 145개 테스트 (run.py)
    ├── references/                    #   "왜"와 정확한 계약
    │   ├── loop-concepts.md           #     모든 설계 선택의 배경 원칙
    │   ├── safety-invariants.md       #     S1–S7 전문
    │   └── data-formats.md            #     완전한 JSON/JSONL 스키마 (기준 문서)
    ├── evals/
    │   └── evals.json                 #   레벨-2 eval: 스킬 자체가 올바르게 동작하는가?
    └── assets/
        └── loop-state/                #   한 번의 실행을 위한 템플릿/작업 상태 파일
```

실행별 작업 상태는 `loop/<target>/`에 위치하며, 사람이 읽을 수 있고 재개 가능합니다: `golden-set.json`, `prompt.current.md` / `prompt.candidate.md`(스테이징 — 실제 파일이 아님), `history.jsonl`(턴별 점수 추이), `failure-log.jsonl`(버려진/정지된 시도 + 진화 후보), `state.json`(멱등 재개를 위한 턴 상태 기계).

---

## 번들 스크립트

코드가 모든 되돌릴 수 없는 결정을 내립니다; 모델은 오직 생성하고 채점만 합니다. 모든 스크립트는 [`loop-optimizer/scripts/`](./loop-optimizer/scripts) 아래에 있습니다.

| 단계 | 스크립트 | 역할 |
|---|---|---|
| 사전 점검 | `validate_config.py` | run-config 검증: 행위자 분리, 채점자 temperature 0 |
| ④ | `verify_change.py` | 정확히 하나의 국소 변경 검증 (유일 `before` + 국소성 상한) |
| ⑤ / ⑩ | `apply_change.py` | 스테이징에 적용; 병합 시 후보 → 현재 승격 (검증 게이트 재실행) |
| ⑧ | `score_compare.py` | 병합 게이트: 고정 부등식으로 MERGE / DISCARD / HALT |
| 보정 | `calibrate_noise.py` | `eps_train` / `eps_heldout` 도출; `gate_satisfiable` 보고 |
| 콜드 스타트 / 분할 | `split_goldenset.py` | 골든셋 상태 분류(`op=state`); 분할 & 고정(`op=split`) |
| 재개 | `resume.py` | 마지막으로 완료된 단계부터 멱등 재개 |

---

## 비용

한 턴의 대략적 비용:

```
Runner (현재 + 후보 검증 + 확인) × 셋 크기
  + Grader (동일) + Proposer (1)
  ≈ |train| = 5, |held| = 3 일 때 모델 호출 약 49회
  + k_calib 보정 실행 (콜드 스타트 시 1회)
```

예산은 **일급 제약(first-class constraint)**입니다: `run-config.json`에 `budget.max_usd_total`과 `budget.max_usd_per_turn`을 설정하세요. 총비용은 `n_turns`와 골든셋 크기로 조절하며, 루프는 `state.json`에서 `budget_spent_usd`를 추적하다가 상한에 닿으면 멈춥니다.

---

## 요구 사항

- `loop-optimizer/scripts/`를 위한 **Python ≥ 3.8** — **표준 라이브러리만** 사용, 서드파티 패키지 없음.
- **Claude Code** (서브에이전트) — 네 명의 행위자를 각자 깨끗한 컨텍스트에서 실행해 진짜로 고립시키기 위해.

---

## 더 읽을거리

- [`loop-optimizer/SKILL.md`](./loop-optimizer/SKILL.md) — 전체 스킬 계약 (Claude Code가 로드하는 것).
- [`references/loop-concepts.md`](./loop-optimizer/references/loop-concepts.md) — 루프의 배경 원칙 (왜 먼저 측정하는가, 왜 한 변경인가, 왜 제안자 ≠ 채점자인가, 실패 로그, 빼기, 코치로서의 사람, 모델/도구 천장).
- [`references/safety-invariants.md`](./loop-optimizer/references/safety-invariants.md) — S1–S7 전문, 각각 방지하는 실패와 그것을 강제하는 메커니즘 포함.
- [`references/data-formats.md`](./loop-optimizer/references/data-formats.md) — 모든 파일과 계약의 기준이 되는 JSON/JSONL 스키마.
- [`evals/evals.json`](./loop-optimizer/evals/evals.json) — 스킬 자체에 대한 종단간 행동 eval (웜 스타트 병합, 콜드 스타트 사람 게이트, 과적합 HALT).
