# 실행 설정하기

> 실행 설정(`run-config.json`)은 루프에게 **대상을 "실사용처럼" 어떻게 실행할지**와 누가
> 어떤 역할을 맡는지를 알려줍니다. 여기서 하중을 지탱하는 것은 두 가지입니다:
> **실행자(Runner)는 운영 모델·temperature와 일치해야** 하고 — 그렇지 않으면 루프가
> 보정하는 노이즈가 진짜 노이즈가 아니며 — **행위자들은 분리된 채로 유지되어야** 합니다 —
> 그렇지 않으면 채점이 조용히 자가 채점 시험으로 변합니다. 이 둘을 틀리면, 골든셋이 아무리
> 좋아도 그 아래의 모든 점수가 엉뚱한 것을 측정하게 됩니다.

이 페이지는 `run-config.json`의 필드별 레퍼런스와 그것을 강제하는 사전 점검(pre-flight)을
다룹니다. 이 설정이 실행 대상으로 삼는 *시험*은 [`golden-set.ko.md`](./golden-set.ko.md),
종단간 실행은 [`running.ko.md`](./running.ko.md), 기준이 되는 JSON 스키마는
[`../../skills/agent-coach/references/data-formats.md`](../../skills/agent-coach/references/data-formats.md)를
보세요.

---

## 최소 설정

이미 골든셋이 있을 때는 이 웜 스타트 설정(같은 파일이 복붙용으로
[`../../examples/agent-coach/ko/run-config.example.json`](../../examples/agent-coach/ko/run-config.example.json)에도 있습니다)만
있으면 됩니다:

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

블록별로 읽으면:

- **`_note`** 는 파서가 무시하는 사람용 주석입니다(이름이 `_`로 시작하는 필드) — 파일에 메모를
  달 때 사용합니다.
- **최상위.** `target`과 `golden_set`은 실제 대상 파일과 그 시험(골든셋)을 가리킵니다 — 둘 다
  상대경로.
- **`runner`** 는 `claude-opus-4-8`을 **temperature 0.7**로 사용 — *운영에서 실제로 쓰는
  모델·temperature 그대로*라서 루프가 보정하는 노이즈가 진짜 노이즈가 됩니다(인위적으로 조용한
  `temperature: 0`이 아님).
- **`grader`** 는 *다른* 모델(`claude-sonnet-4-6`)을 **temperature 0**에 `version_id`를 고정해
  사용 — 안정적이고 분산이 0인 잣대입니다. 모델을 다르게 두는 것이 채점을 정직하게
  유지합니다(제안 ≠ 채점).
- **`proposer`** 는 `claude-opus-4-8`을 낮은 temperature(**0.3**)로 사용해 집중된 단일 편집을
  합니다. 여기서는 마침 runner와 같은 모델이지만 괜찮습니다 — 강제 분리 규칙은 오직
  proposer ≠ grader(그리고 bootstrapper ≠ grader)뿐입니다.
- **`calibration.k_calib: 5`** 는 Runner를 5회 재실행해 `eps`를 측정합니다; 5는 권장
  하한입니다.
- **`loop`** 는 실행을 10턴으로 제한하고, 무진보 3턴이면 정지하며, 3턴마다 빼기를 시도합니다.
- **`budget`** 는 총 지출을 `$20`, 턴당 지출을 `$3`로 제한합니다 — 둘 중 하나에 닿으면 실행이
  멈춥니다.
- **`tools.mode: "none"`** = 순수 텍스트 입출력 대상(v1 기본).

여기엔 `bootstrapper` 블록이 없는데, 이는 웜 스타트이기 때문입니다.
[콜드 스타트](./running.ko.md#콜드-스타트-골든셋이-아직-없을-때)에서만 — grader와 다른 모델로 —
추가하세요.

---

## 측정을 정직하게 유지하는 3가지 규칙

`run-config.json`의 대부분은 평범한 손잡이입니다(턴 수, 예산 상한). 하지만 세 가지 설정은 취향이
아니라, 실제 품질을 측정하는 루프와 스스로를 속이는 루프를 가르는 경계입니다. 아래 사전 점검은
그중 강한 규칙들에서 **실행을 차단**합니다.

**1. 실행자(Runner)는 곧 운영 런타임입니다.** `runner.model`과 `runner.temperature`는 실제로
출시해 쓰는 모델·temperature여야 합니다. 루프는 노이즈 마진(`eps_train` / `eps_heldout`)을
*동일한 실행 사이에서 실행자의 출력이 얼마나 흔들리는지*로부터 도출합니다 — 그래서 "더 깔끔한"
숫자를 얻겠다고 `temperature: 0`으로 조용히 낮추면, 운영에서는 결코 보지 못할 노이즈 대역을
보정하게 되고, 게이트는 실사용에서 살아남지 못할 변경을 태연히 병합합니다. 실제 값인
`0.7`(또는 당신이 돌리는 값)로 설정하고, **`0`으로 두지 마세요.**

**2. 채점자(Grader)는 고정된, 분산 0의 잣대입니다.** `grader.temperature`는 반드시 `0`이어야
하고, `grader.version_id`는 *어떤* 잣대를 썼는지 고정합니다. temperature 0이면 같은 텍스트를
재채점해도 동일한 점수가 나옵니다 — 채점자는 분산을 **전혀** 더하지 않으므로, 측정되는 모든
노이즈는 (마땅히 있어야 할 곳인) 실행자에서 나옵니다(S7). 이 고정값 덕분에 나중에, 실행 간
추세가 *잣대*의 드리프트가 아니라 *대상*의 개선을 반영하는지 감사할 수 있습니다.

**3. 제안하는 자는 결코 채점하지 않습니다.** `proposer.model`은 `grader.model`과 달라야
합니다(그리고 콜드 스타트에서는 `bootstrapper.model`이 `grader.model`과 달라야 합니다).
"네 *자신의* 변경이 도움이 됐어?"라는 질문을 받은 모델은 "그렇다"고 답하도록 편향됩니다 — 자가
채점 시험입니다(S5). 제안과 채점을 다른 모델에 두는 것이 분리를 명목이 아니라 실제로 만듭니다.
제안자는 실행자와 같은 모델을 *써도* 됩니다; 유일하게 단단한 벽은 채점자에 대한 것입니다.

---

## 필드 레퍼런스(전 블록)

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

---

## 사전 점검(pre-flight)

턴 1 **이전에** 항상 `validate_config.py`를 실행하세요. 에러가 하나라도 있으면 실행을
정지시킵니다 — 잘못 설정된 행위자가 실행 전체를 조용히 무효화하는 일이 결코 없도록:

- **에러(실행 차단):** `runner`/`grader`/`proposer` 블록 또는 `model` 누락 ·
  `grader.temperature ≠ 0` · `proposer.model == grader.model` ·
  `bootstrapper.model == grader.model`(부트스트래퍼가 있을 때). 모델 id는 대소문자·공백을
  무시하고 비교하므로 `"Sonnet"` vs `"sonnet"`로 자가 채점 실행을 우회할 수 없습니다.
- **경고(주의하며 진행):** `runner.temperature == 0`(분산 없음 → `eps`가 바닥으로 붕괴) ·
  `k_calib < 5` · `grader.version_id` 누락 · `budget` 블록 누락.

```bash
printf '%s' '{"config_path":"./run-config.json"}' | python3 skills/agent-coach/scripts/validate_config.py
```

(스크립트는 위 예시처럼 저장소 루트에서 실행하세요 — 경로는 이 `docs/` 페이지가 아니라 프로젝트
루트 기준입니다.)

---

## 더 보기

- [`golden-set.ko.md`](./golden-set.ko.md) — 이 설정이 실행 대상으로 삼는 시험; 대부분의
  지렛대가 있는 곳.
- [`running.ko.md`](./running.ko.md) — 종단간 실행: 검증 → 베이스라인 → 루프 → 배치
  커밋/되돌리기, 그리고 콜드 스타트와 재개.
- [`../../skills/agent-coach/references/data-formats.md`](../../skills/agent-coach/references/data-formats.md)
  — 기준이 되는 `run-config.json` 스키마, 필드별.
- [`../../skills/agent-coach/references/safety-invariants.md`](../../skills/agent-coach/references/safety-invariants.md)
  — S1–S7, 특히 S5(행위자 분리)와 S7(실행자 분산에서 나온 노이즈, 채점자 temperature 0).
