# Agent Coach (에이전트 코치)

> **프롬프트·스킬·지시문 파일을 *측정 기반* 자기개선 루프로 반복 개선합니다 — 감(感)이 아니라 점수로.**

*다른 언어로 보기: [English](./README.md)*

`agent-coach`는 대상 프롬프트/스킬/지시문 파일을 마치 좋은 코치가 선수를 훈련시키듯 다듬는 [Claude Code](https://docs.claude.com/en/docs/claude-code) 스킬입니다(스킬 본체는 [`agent-coach/`](./agent-coach)에 있습니다):

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
- [빠른 시작](#빠른-시작)
- [📖 전체 매뉴얼](#전체-매뉴얼-docs)
- [저장소 구조](#저장소-구조)
- [번들 스크립트](#번들-스크립트)
- [요구 사항](#요구-사항)

---

## 왜 이 스킬이 필요한가

"자기개선(self-improvement)"은 멋지게 들리지만, **측정되지 않는 순간 함정**이 됩니다. 모델이 프롬프트를 고치고, 더 나아졌다고 선언하고, 프롬프트는 감에 따라 서서히 표류합니다 — 때로는 더 나빠지는데도, 아무도 알아채지 못합니다. 이 표류가 실제 실패를 숨기는 세 가지 구체적인 방식이 있습니다:

1. **노이즈를 진보로 착각.** 실사용 temperature에서는 대상의 출력이 실행할 때마다 흔들립니다. "학습 점수 +1"은 순전히 운일 수 있습니다. 그 노이즈 대역 안에서 병합하면 무작위성을 프롬프트에 새겨 넣게 됩니다 — 점수는 슬금슬금 오르는데 프롬프트는 오히려 *나빠집니다*.
2. **과적합(overfitting).** 어떤 변경은 최적화 대상이었던 케이스들의 특이점만 외워버리고 일반화 능력을 조용히 망가뜨릴 수 있습니다 — 전형적인 "학습셋 98%, 운영에서는 고장" 함정입니다.
3. **자가 채점 시험.** 모델에게 "네 변경이 도움이 됐어?"라고 물으면, 방금 그것을 만들어낸 모델은 "그렇다"고 답하도록 편향되어 있습니다. 선수가 자기 경기의 심판을 봐서는 안 됩니다.

`agent-coach`는 이 실패 양상 각각을 **기계적으로** 제거하도록 설계되어, "더 낫다(better)"를 의견이 아니라 **측정된 값**(observed quantity)으로 만듭니다.

---

## 무엇이 다른가

| 흔한 "AI가 프롬프트를 개선" 도구 | `agent-coach` |
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

가장 중요한 구조적 규칙 하나: **변경을 제안하는 모델은 그것을 채점하는 모델이 아니며, 둘 중 어느 것도 대상을 실행하는 모델이 아니다.** 각 행위자는 [`agent-coach/agents/`](./agent-coach/agents) 아래에 자기 프롬프트를 가진 별도의 Claude Code 서브에이전트입니다. 그래서 각자 깨끗한 컨텍스트에서 시작하고, 역할 분리가 명목상이 아니라 *실제로* 보장됩니다.

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
⑨ 확인      MERGE라면: 한 번 더 재실행 + 재채점 — 후보 AND 현재(베이스라인) 프롬프트를
            둘 다; 재측정한 베이스라인 대비 향상이 여전히 유지되어야 함
⑩ 기록      MERGE  → 후보를 현재로 승격 + history.jsonl 추가
            DISCARD→ failure-log.jsonl(+ candidate_input); 실제 파일 유지
            HALT   → 정지 + 경고 + failure-log.jsonl (result: halted)
```

**왜 재채점이 아니라 재실행으로 확인하는가(⑨)?** 채점자는 temperature 0으로 돌기 때문에, *같은 텍스트*를 재채점하면 동일한 점수가 나옵니다 — 아무 의미 없는 동작입니다. 진짜 노이즈는 **실행자(Runner)**가 실행할 때마다 다른 출력을 내는 데서 옵니다. 그래서 병합은 *대상을 다시 실행해서* 새 출력을 재채점하는 방식으로 확인합니다. 확인 단계는 **후보와 현재(베이스라인) 프롬프트를 둘 다** 재실행하고, 새로 재측정한 베이스라인(`train_b2`/`held_b2`)에 대해 게이트를 다시 검사합니다: 첫 게이트의 베이스라인을 재사용하면 두 검사가 상관되어 노이즈를 걸러내는 확인의 힘이 대략 절반으로 줄기 때문입니다. 그 새 베이스라인 대비 향상이 증발하면 그것은 노이즈였습니다.

### 병합 게이트(핵심)

판단은 모델이 아니라 [`score_compare.py`](./agent-coach/scripts/score_compare.py)가 내립니다. 변경은 **다음이 모두 성립할 때만 MERGE 됩니다:**

```
train_after   >  train_before                      (엄격히 양(+)의 향상 — +0.0 동점은 절대 병합 안 함)
train_after   ≥  train_before   + eps_train        (학습에서 측정 노이즈를 이긴 향상)
heldout_after ≥  heldout_before − eps_heldout       (홀드아웃에서 실질적 퇴행 없음)
그리고 확인 재실행(⑨) 후에도 향상이 유지됨
```

그 외의 경우:

- `train`은 오르는데 `heldout`이 `eps_heldout`보다 **더 많이** 떨어지면 → **HALT** (과적합: 변경이 학습셋을 외워버리고 일반화를 망가뜨림). HALT는 종료 상태입니다.
- 그 밖에는 → **DISCARD** (실질 향상 없음; 추가가 되돌려짐).

마진 `eps_train` / `eps_heldout`은 **측정 노이즈**이며, [`calibrate_noise.py`](./agent-coach/scripts/calibrate_noise.py)가 보정합니다: 고정된 입력에 대해 실행자를 `k_calib`번(5 이상 권장) 다시 돌리고, 각각 채점해서, 분할별 점수 산포를 도출합니다 — 작은 양수 `min_eps`로 바닥을 깔아서 `+0.0` 동점이 진보처럼 보이는 일을 막습니다. 홀드아웃 마진은 **대칭(symmetric)**입니다(병합 쪽과 HALT 쪽 모두 `eps_heldout`). 그래서 평범한 홀드아웃 노이즈가 거짓 HALT를 유발하지 않습니다.

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

이 불변식들이 바로 이 스킬이 존재하는 이유입니다. 각각은 "자기개선"이 측정 없는 진화로 조용히 퇴락하는 특정한 한 가지 경로를 제거합니다. 전체 서술: [`references/safety-invariants.md`](./agent-coach/references/safety-invariants.md).

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

## 빠른 시작

이것은 Claude Code 스킬이므로 자연어로 구동합니다 — 정상 사용에서는 스크립트를 직접 호출하지 않고, 오케스트레이터가 호출합니다. 전형적인 시작:

> "`./prompts/summarizer.md`를 `golden-set.json`의 케이스들에서 점수가 더 잘 나오도록 튜닝해줘(train과 held-out은 이미 표시돼 있어). 단, **무엇이든 바꾸기 전에 먼저 측정**하고, 정말로 도움이 될 때만 변경을 유지해 — 과적합은 하지 마. 설정은 `run-config.json`에 있어."

스킬은 설정을 검증하고, train + held-out에서 **베이스라인**을 측정하고, 게이트 적용 루프(턴당 한 **스테이징** 변경)를 돌린 뒤, **커밋하거나 되돌릴 배치**를 건넵니다 — 커밋 전까지 실제 파일은 그대로입니다. 반(半)자율적입니다: 사용자는 루프 *위*에 앉고 매 턴 안에 있지 않으며, 최종 "정말 동작하는가" QA는 사용자의 몫입니다.

→ **전체 walkthrough** — 세 가지 시나리오(웜/콜드/과적합 방어), 중단된 실행 재개, 콜드 스타트, 비용 — 은 [`docs/running.ko.md`](./docs/running.ko.md)에 있습니다.

### 결정론적 코어 검증

어떤 실행이든 신뢰하기 전에, 모든 되돌릴 수 없는 결정을 내리는 그 코드를 먼저 검증하세요:

```bash
python3 agent-coach/scripts/tests/run.py          # 219개 테스트, 표준 라이브러리만 사용
# 또는:  python3 -m pytest agent-coach/scripts/tests/
```

모든 스크립트는 JSON 페이로드를 **stdin**(또는 파일 경로 인자)으로 읽습니다 — 절대로 인라인 argv 문자열이 아닙니다:

```bash
printf '%s' '<json>' | python3 agent-coach/scripts/score_compare.py
```

---

## 전체 매뉴얼: `docs/`

📖 상세 사용법 가이드는 [`docs/`](./docs)에 있습니다 — 영어와 한국어(`*.ko.md`)로:

| 가이드 | 다루는 내용 |
|---|---|
| [**좋은 골든셋 만들기**](./docs/golden-set.ko.md) | 골든셋은 해자입니다: 케이스 고르기, 루브릭 작성 craft, train/held-out 분할, 보정, 실행 사이 셋 진화, 안티패턴, 워크드 예제. |
| [**실행 설정하기**](./docs/run-config.ko.md) | `run-config.json`의 모든 필드, 측정을 정직하게 유지하는 3가지 규칙, 사전 점검. |
| [**루프 실행하기**](./docs/running.ko.md) | 빠른 시작, 세 가지 실전 시나리오, 중단된 실행 재개, 콜드 스타트, 비용. |

영문: [`golden-set.md`](./docs/golden-set.md) · [`run-config.md`](./docs/run-config.md) · [`running.md`](./docs/running.md).

---

## 저장소 구조

README는 프로젝트 루트에 있고, 스킬 본체는 `agent-coach/`에, 복사해 쓸 수 있는 입력은 `examples/`에 있습니다.

```
.
├── README.md                          # 영문 버전
├── README.ko.md                       # 이 파일 (한글)
├── docs/                              # 전체 매뉴얼 (영어 + 한국어 .ko.md)
│   ├── golden-set.md                  #   골든셋 — 해자 (케이스, 루브릭, 분할)
│   ├── run-config.md                  #   run-config.json 모든 필드 + 사전 점검
│   └── running.md                     #   빠른 시작, 시나리오, 재개, 콜드 스타트, 비용
├── examples/                          # 복붙 가능한 예시 입력 & 상태
│   ├── run-config.example.json        #   실행 설정 (한글 주석)
│   ├── golden-set/                    #   골든셋 + cases/ (한글 주석)
│   ├── loop-state/                    #   샘플 history / failure-log / state
│   └── en/                            #   위 전체의 영문 미러
│       ├── run-config.example.json
│       ├── golden-set/
│       └── loop-state/
└── agent-coach/                    # 스킬 본체
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
    │   ├── aggregate_scores.py        #     ②/⑦ 케이스별 점수 → 분할별 train/heldout
    │   ├── score_compare.py           #     ⑧ MERGE / DISCARD / HALT 결정
    │   ├── calibrate_noise.py         #     eps_train / eps_heldout + gate_satisfiable
    │   ├── split_goldenset.py         #     상태 분류 + 셋 분할 & 고정
    │   ├── resume.py                  #     중단 후 멱등(idempotent) 재개
    │   ├── check_cross_validation.py  #     자문용 교차-계열 드리프트 WARN (비차단, 게이트 아님)
    │   ├── _common.py                 #     공용 헬퍼 (stdin 페이로드, 해싱)
    │   └── tests/                     #     코어에 대한 219개 테스트 (run.py)
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

코드가 모든 되돌릴 수 없는 결정을 내립니다; 모델은 오직 생성하고 채점만 합니다. 모든 스크립트는 [`agent-coach/scripts/`](./agent-coach/scripts) 아래에 있습니다.

| 단계 | 스크립트 | 역할 |
|---|---|---|
| 사전 점검 | `validate_config.py` | run-config 검증: 행위자 분리, 채점자 temperature 0 |
| ④ | `verify_change.py` | 정확히 하나의 국소 변경 검증 (유일 `before` + 국소성 상한) |
| ⑤ / ⑩ | `apply_change.py` | 스테이징에 적용; 병합 시 후보 → 현재 승격 (검증 게이트 재실행) |
| ② / ⑦ | `aggregate_scores.py` | 케이스별 점수 → 분할별 train/heldout 집계 (Σpassed / Σtotal) |
| ⑧ | `score_compare.py` | 병합 게이트: 고정 부등식으로 MERGE / DISCARD / HALT |
| 보정 | `calibrate_noise.py` | `eps_train` / `eps_heldout` 도출; `gate_satisfiable` 보고 |
| 콜드 스타트 / 분할 | `split_goldenset.py` | 골든셋 상태 분류(`op=state`); 분할 & 고정(`op=split`) |
| 재개 | `resume.py` | 마지막으로 완료된 단계부터 멱등 재개 |

---

## 요구 사항

- `agent-coach/scripts/`를 위한 **Python ≥ 3.8** — **표준 라이브러리만** 사용, 서드파티 패키지 없음.
- **Claude Code** (서브에이전트) — 네 명의 행위자를 각자 깨끗한 컨텍스트에서 실행해 진짜로 고립시키기 위해.
