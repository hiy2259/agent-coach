# 실행 설정하기

> 실행 설정 파일(`run-config.json`)은 루프에게 **대상을 "실사용과 같은 조건"으로 돌리는
> 방법**과, 어느 모델이 어느 역할을 맡는지를 알려 줍니다. 이 중 두 가지 설정이 측정
> 전체를 떠받칩니다. 첫째, **Runner(실행)는 운영에서 쓰는 모델·temperature 그대로**여야
> 합니다 — 아니면 루프가 보정하는 노이즈가 실제 노이즈가 아니게 됩니다. 둘째, **역할은
> 반드시 분리되어야** 합니다 — 아니면 채점이 슬그머니 자가 채점 시험으로 변합니다. 이 둘
> 중 하나라도 틀리면, 골든셋이 아무리 좋아도 그 뒤의 모든 점수가 엉뚱한 것을 재게 됩니다.

이 페이지는 `run-config.json`의 필드별 레퍼런스와, 그 규칙을 강제하는 사전
점검(pre-flight)을 다룹니다. 이 설정이 돌리는 *시험지*는
[`golden-set.ko.md`](./golden-set.ko.md), 실행의 처음부터 끝까지는
[`running.ko.md`](./running.ko.md), 기준이 되는 JSON 스키마는
[`../../skills/agent-coach/references/data-formats.md`](../../skills/agent-coach/references/data-formats.md)를
보세요.

---

## 최소 설정

골든셋이 이미 있다면 이 웜 스타트 설정 하나면 충분합니다. (같은 파일이 복사해 쓸 수 있게
[`../../examples/agent-coach/ko/run-config.example.json`](../../examples/agent-coach/ko/run-config.example.json)에도
들어 있습니다.)

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

블록별로 읽어 보면:

- **`_note`** 는 사람을 위한 주석입니다. 이름이 `_`로 시작하는 필드는 파서가 무시하므로,
  파일에 자유롭게 메모를 남길 수 있습니다.
- **최상위.** `target`과 `golden_set`은 실제 대상 파일과 그 시험지(골든셋)를 가리킵니다.
  둘 다 상대 경로입니다.
- **`runner`** 는 `claude-opus-4-8`을 **temperature 0.7**로 씁니다 — *운영에서 실제로 쓰는
  모델·temperature 그대로*입니다. 그래야 루프가 보정하는 노이즈가 진짜 노이즈가 됩니다.
  `temperature: 0`으로 인위적으로 조용하게 만든 노이즈가 아니라요.
- **`grader`** 는 *다른* 모델(`claude-sonnet-4-6`)을 **temperature 0**으로, `version_id`를
  고정해서 씁니다 — 스스로는 무작위성을 전혀 더하지 않는, 안정된 잣대입니다. 제안자와 다른
  모델로 두는 것이 채점을 정직하게 지킵니다(제안 ≠ 채점).
- **`proposer`** 는 `claude-opus-4-8`을 낮은 temperature(**0.3**)로 써서, 집중된 단일
  편집을 만듭니다. 여기서는 마침 Runner와 같은 모델인데, 그래도 괜찮습니다 — 반드시
  지켜야 할 분리 규칙은 proposer ≠ grader와 bootstrapper ≠ grader뿐입니다.
- **`calibration.k_calib: 5`** 는 노이즈 허용 오차 `eps`를 재기 위해 Runner를 5번 반복
  실행한다는 뜻입니다. 5가 권장 최솟값입니다.
- **`loop`** 는 실행을 최대 10턴으로 제한하고, 진전 없는 턴이 3번 이어지면 멈추고, 3턴마다
  빼기(규칙 하나 제거해 보기)를 시도합니다.
- **`budget`** 는 총 지출을 `$20`, 턴당 지출을 `$3`로 제한합니다. 둘 중 하나에 닿으면
  실행이 멈춥니다.
- **`tools.mode: "none"`** 은 대상이 순수 텍스트 입력/출력이라는 뜻입니다(v1 기본값).

이 예시에 `bootstrapper` 블록이 없는 것은 웜 스타트이기 때문입니다.
[콜드 스타트](./running.ko.md#콜드-스타트-골든셋이-아직-없을-때)일 때만 — grader와 다른
모델로 — 추가하세요.

---

## 측정을 정직하게 지키는 세 가지 규칙

`run-config.json`의 대부분은 평범한 조절값입니다: 턴 수, 예산 상한 같은 것들. 하지만 세
가지 설정은 취향의 문제가 아닙니다 — 루프가 실제 품질을 측정하느냐, 스스로를 속이느냐를
가릅니다. 아래 사전 점검은 이 중 강한 규칙이 어긋나면 **실행을 차단합니다**.

**1. Runner는 곧 운영 환경입니다.** `runner.model`과 `runner.temperature`는 실제 서비스에
쓰는 모델과 temperature여야 합니다. 루프는 노이즈 허용 오차(`eps_train` / `eps_heldout`)를
"같은 실행을 반복했을 때 Runner의 출력이 얼마나 달라지는가"에서 계산합니다. "더 깔끔한"
숫자를 보겠다고 `temperature: 0`으로 낮추면, 운영에서는 결코 겪지 않을 노이즈 대역을
보정하게 되고, 게이트는 실사용에서 버티지 못할 변경을 태연히 병합하게 됩니다. 실제
값(예: `0.7`)을 쓰고, **`0`으로 두지 마세요.**

**2. Grader는 고정된, 흔들리지 않는 잣대입니다.** `grader.temperature`는 반드시 `0`이어야
하고, `grader.version_id`에는 *어떤* 잣대를 썼는지 기록합니다. temperature 0에서는 같은
텍스트를 두 번 채점하면 완전히 같은 점수가 나옵니다 — 즉 Grader는 무작위성을 **전혀**
보태지 않고, 측정되는 노이즈는 전부 (마땅히 그래야 할) Runner 쪽에서 나옵니다(S7). 버전을
고정해 두면 나중에 "실행 간 점수 추세가 *대상*의 개선을 반영한 것인지, *잣대*가 슬며시
변한 것인지"를 확인할 수 있습니다.

**3. 제안한 자는 채점하지 않습니다.** `proposer.model`은 `grader.model`과 달라야
합니다(콜드 스타트에서는 `bootstrapper.model`도 `grader.model`과 달라야 합니다). "네가
*직접* 만든 변경이 도움이 됐어?"라는 질문을 받은 모델은 "그렇다"고 답하는 쪽으로 이미
기울어 있습니다 — 자가 채점 시험이지요(S5). 제안과 채점을 서로 다른 모델에 맡기는 것이
역할 분리를 말뿐이 아니라 실제로 만듭니다. 제안자가 Runner와 같은 모델을 쓰는 것은
*괜찮습니다*. 절대 넘으면 안 되는 벽은 Grader와의 사이에만 있습니다.

---

## 필드 레퍼런스 (전 블록)

| 블록 | 프로퍼티 | 타입 | 의미 | 설정 방법 |
|---|---|---|---|---|
| (최상위) | `target` | string | 실제 대상 파일의 상대 경로 | 골든셋의 `target`이 가리키는 것과 같은 파일 |
| (최상위) | `golden_set` | string | `golden-set.json`의 상대 경로 | 예: `./golden-set.json` |
| `runner` | `model` | string | 대상을 실행하는 모델 | **실제 운영 환경과 일치해야** 측정 노이즈가 진짜가 됩니다 |
| `runner` | `temperature` | number | 실사용 temperature — `eps`를 만들어 내는 분산의 원천 | 실제 운영 temperature, 예: `0.7` (`0` 아님) |
| `runner` | `max_output_tokens` | number | 대상 실행 1회의 출력 상한 | 완전한 답이 나올 만큼, 예: `4096` |
| `grader` | `model` | string | 채점 모델 (실행 내내 동일하게 유지) | **제안자와 다른**, 채점을 맡길 만한 모델 |
| `grader` | `temperature` | number | **반드시 `0`** — 채점은 분산을 더하지 않음 (S7) | 항상 `0` (아니면 사전 점검이 에러) |
| `grader` | `version_id` | string | 잣대 변동(드리프트)을 나중에 확인하기 위한 고정 기록 | 날짜나 태그, 예: `"2026-06-16"` |
| `proposer` | `model` | string | 턴마다 변경 한 건을 제안하는 모델 | **`grader.model`과 반드시 달라야 함** (제안 ≠ 채점) |
| `proposer` | `temperature` | number | 집중된 제안을 위한 낮은 temperature | 예: `0.3` |
| `bootstrapper` | `model` | string (선택) | 콜드 스타트에서 입력 후보를 초안 | 콜드 스타트에만 필요; 있다면 **`grader.model`과 달라야 함** |
| `calibration` | `k_calib` | number | 노이즈를 재기 위한 Runner 반복 실행 횟수 | **5 이상** (작으면 `eps` 추정이 불안정 → 경고) |
| `loop` | `n_turns` | number | 최대 턴 수 | 기본 `10`; 더 길게 탐색하려면 올리세요 (비용도 함께 커집니다) |
| `loop` | `no_progress_k` | number | `MERGE`/`SUB_KEEP` 없이 K턴 연속이면 정지 | 기본 `3` |
| `loop` | `subtraction_every` | number | N턴마다 빼기 시도 | 기본 `3` |
| `budget` | `max_usd_total` | number | 총 지출 상한 (권장이 아니라 강제 제약) | `n_turns` × 셋 크기로 가늠; 도달하면 실행 정지 |
| `budget` | `max_usd_per_turn` | number | 턴당 지출 상한 | 한 턴이 폭주하는 것을 막는 가드레일 |
| `tools` | `mode` | `"none"` \| `"mocked"` | `none` = 순수 텍스트 입출력 대상 (v1 기본값) | `"none"` 유지; `"mocked"`는 아직 사양이 덜 정해진 v2 사안 |

---

## 사전 점검 (pre-flight)

턴 1을 시작하기 **전에** 항상 `validate_config.py`를 실행하세요. 에러가 하나라도 있으면
실행을 멈추므로, 잘못 설정된 역할이 실행 전체를 조용히 망치는 일이 생기지 않습니다:

- **에러 (실행 차단):** `runner`/`grader`/`proposer` 블록 또는 `model` 필드 누락 ·
  `grader.temperature ≠ 0` · `proposer.model == grader.model` ·
  `bootstrapper.model == grader.model`(부트스트래퍼가 있을 때). 모델 id는 대소문자와
  공백을 무시하고 비교하므로, `"Sonnet"`과 `"sonnet"`처럼 표기만 바꿔서 자가 채점 실행을
  통과시킬 수는 없습니다.
- **경고 (주의하며 진행):** `runner.temperature == 0` (분산이 없어 `eps`가 하한까지 붕괴) ·
  `k_calib < 5` · `grader.version_id` 누락 · `budget` 블록 누락.

```bash
printf '%s' '{"config_path":"./run-config.json"}' | python3 skills/agent-coach/scripts/validate_config.py
```

(위 예시처럼 저장소 루트에서 실행하세요 — 경로는 이 `docs/` 페이지가 아니라 프로젝트 루트
기준입니다.)

---

## 더 보기

- [`golden-set.ko.md`](./golden-set.ko.md) — 이 설정이 돌리는 시험지; 성패를 가장 크게
  좌우하는 부분.
- [`running.ko.md`](./running.ko.md) — 실행의 처음부터 끝까지: 검증 → 베이스라인 → 루프 →
  묶음 커밋/되돌리기, 그리고 콜드 스타트와 재개.
- [`../../skills/agent-coach/references/data-formats.md`](../../skills/agent-coach/references/data-formats.md)
  — 기준이 되는 `run-config.json` 스키마, 필드별 설명.
- [`../../skills/agent-coach/references/safety-invariants.md`](../../skills/agent-coach/references/safety-invariants.md)
  — S1–S7, 특히 S5(역할 분리)와 S7(Runner 분산으로 잰 노이즈, 채점자 temperature 0).
