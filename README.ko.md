# Loop — 측정 기반 프롬프트 개선

> **프롬프트·스킬·지시문 파일을 *측정*으로 개선하는 [Claude Code](https://docs.claude.com/en/docs/claude-code) 스킬 2종 — 감(感)이 아니라 점수로.**

*다른 언어로 보기: [English](./README.md)*

이 저장소는 **서로를 보완하는 Claude Code 스킬 두 개**를 담습니다([`skills/`](./skills) 아래). 둘 다 **"측정 없는 진화는 없다"**는 한 가지 원칙을 따르며, 서로 이어집니다:

| 스킬 | 하는 일 | 언제 쓰나 |
|---|---|---|
| [**agent-coach**](#agent-coach) | 대상 프롬프트/스킬/지시문 파일을 측정 기반 자기개선 루프로 튜닝: 측정 → 한 가지만 변경 → 측정 → 점수가 정말 오른 경우에만 유지. | 골든셋이 이미 있고, 그에 맞춰 프롬프트를 개선하고 싶을 때. |
| [**golden-set-drafter**](#golden-set-drafter) | agent-coach*를 위한* 골든셋 v1을 초안 작성(회의체 검토 + 실패 실측)하고, held-out 채점표는 **사용자가** 작성해야 열리는 게이트에서 멈춤. | 프롬프트를 개선하고 싶지만 **골든셋이 아직 없을 때**. |

골든셋이 아직 없다면? **golden-set-drafter**를 먼저 돌려 초안을 만든 뒤, 그 산출물을 **agent-coach**에 넘기세요.

---

## agent-coach

대상 프롬프트를 좋은 코치가 선수를 훈련시키듯 다듬습니다: **측정한다 → 딱 한 가지만 바꾼다 → 다시 측정한다 → 점수가 정말로 올랐을 때만 유지한다.** 지배 원칙은 **"측정 없는 진화는 없다"** — 감으로 바꾸지 않으며, 각 변경을 유지할지는 *모델의 의견이 아니라 결정론적 코드*가 판단합니다. `MERGE`는 "모델이 보기에 더 나아 보였다"가 아니라, 학습 케이스에서 측정 노이즈를 이기고 홀드아웃에서 일반화를 유지하고 확인 재실행을 통과한 단 하나의 코드-검증된 변경이며 — 커밋하기 전까지 실제 파일은 그대로입니다.

무엇이 다른가, 요약:

- **코드가 모든 병합을 판단** — 모델의 "더 나아 보임"이 아니라 고정된 부등식.
- **학습 + 홀드아웃 분할**이 일반화를 방어; 과적합은 **HALT**를 유발.
- 향상은 **보정된 측정 노이즈를 이겨야** 하고 *또한* 확인 재실행을 통과해야 함.
- **네 명의 고립된 행위자** — 제안자 ≠ 채점자 ≠ 실행자 ≠ 부트스트래퍼.
- **스테이징 전용** — 커밋 전까지 실제 파일은 한 바이트도 안 바뀜.

### 사용법

자연어로 구동합니다 — 스크립트는 오케스트레이터가 호출합니다. 전형적인 시작:

> "`./prompts/summarizer.md`를 `golden-set.json`의 케이스들에서 점수가 더 잘 나오도록 튜닝해줘(train과 held-out은 이미 표시돼 있어). 단, **무엇이든 바꾸기 전에 먼저 측정**하고, 정말로 도움이 될 때만 유지해 — 과적합은 하지 마. 설정은 `run-config.json`에 있어."

설정을 검증하고, train + held-out에서 **베이스라인**을 측정하고, 게이트 적용 루프(턴당 한 **스테이징** 변경)를 돌린 뒤, 커밋하거나 되돌릴 배치를 건넵니다 — 커밋 전까지 실제 파일은 그대로입니다. 실행을 신뢰하기 전에 결정론적 코어를 먼저 검증하세요:

```bash
python3 skills/agent-coach/scripts/tests/run.py          # 219개 테스트, 표준 라이브러리만
```

📖 **매뉴얼** — [`docs/agent-coach/`](./docs/agent-coach): [좋은 골든셋 만들기](./docs/agent-coach/golden-set.ko.md) · [실행 설정하기](./docs/agent-coach/run-config.ko.md) · [루프 실행하기](./docs/agent-coach/running.ko.md) · [동작 원리 — 설계와 안전장치](./docs/agent-coach/how-it-works.ko.md). 영문: `*.md`.

---

## golden-set-drafter

골든셋이 없을 때 agent-coach **보다 먼저, 그 대신** 실행되는 동반 스킬입니다. 대상 파일(+ 발전 방향 문서)에서 골든셋 v1을 초안 작성합니다: proposer → adversary → arbiter 회의체가 케이스 입력과 train 채점표를 다듬고, 모든 train 케이스를 **실제 대상에 실제 운영 모델로** 돌려 실패 증거를 붙입니다. 하지만 **held-out 채점표는 절대 쓰지 않습니다** — 그건 사용자 몫입니다. 그 공란이 핵심 안전장치입니다: 채점표를 채우기 전에는 agent-coach의 `op=split`이 실행을 거부하므로, 개선 루프가 자신의 held-out 시험을 "미리 공부"할 수 없습니다.

### 사용법

> "`./agents/support-agent.md`를 개선하고 싶은데 골든셋이 아직 없어. 발전 방향은 `./direction.md`에 있어. 골든셋 초안부터 만들어줘."

**초안**(held-out 채점표 전원 공란)을 방출하고 **게이트 앞에서 멈춥니다**. 이후는 사용자의 4단계입니다: held-out 입력 검토, held-out 채점표 전부 직접 작성, `op=split` 명령으로 동결(첫 실행은 실패하는 게 정상 — 그 거부가 게이트), 다 채운 뒤 재실행해 세트 동결. 그다음은 agent-coach가 이어받습니다.

📖 **문서** — [`docs/golden-set-drafter/golden-set-drafter.ko.md`](./docs/golden-set-drafter/golden-set-drafter.ko.md) (영문: [`golden-set-drafter.md`](./docs/golden-set-drafter/golden-set-drafter.md)).

---

## 저장소 구조

```
.
├── README.md · README.ko.md          # 이 랜딩 페이지 (영문 / 한국어)
├── docs/                             # 전체 매뉴얼 — 영어 + 한국어 (*.ko.md)
│   ├── agent-coach/                  #   golden-set · run-config · running · how-it-works
│   └── golden-set-drafter/           #   golden-set-drafter.md — drafter의 문서
├── examples/                         # 복붙 가능한 예시, 스킬당 (ko/ + en/ 미러)
│   ├── agent-coach/
│   └── golden-set-drafter/
├── skills/                           # 두 개의 Claude Code 스킬
│   ├── agent-coach/                  #   SKILL.md · agents/ · scripts/ (219 테스트) · references/ · evals/ · assets/
│   └── golden-set-drafter/           #   SKILL.md · agents/ · scripts/ · references/ · evals/ · assets/
└── loop/                             # 실행별 작업 상태 (아래 참조)
```

실행별 작업 상태는 `loop/<target>/`에 위치하며, 사람이 읽을 수 있고 재개 가능합니다: `golden-set.json`, `prompt.current.md` / `prompt.candidate.md`(스테이징 — 실제 파일이 아님), `history.jsonl`(턴별 점수 추이), `failure-log.jsonl`(버려진/정지된 시도), `state.json`(멱등 재개를 위한 턴 상태 기계).

---

## 요구 사항

- 번들 스크립트를 위한 **Python ≥ 3.8** — **표준 라이브러리만**, 서드파티 패키지 없음.
- **Claude Code** (서브에이전트) — 각 스킬의 행위자를 깨끗한 컨텍스트에서 실행해 진짜로 고립시키기 위해.
