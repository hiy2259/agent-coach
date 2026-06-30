# agent-coach: opus vs sonnet 러너 A/B 비교 리포트

**작성:** 2026-06-30 · **타깃:** `usecase/frontend-dev.md` (150줄) · **골든셋:** 18케이스 (train 10 / heldout 8), `split_hash sha256:6c060560…` 양쪽 동일
**상태:** 작성 완료 → `oh-my-claudecode:verifier` 검증 대기 (작성 ≠ 검증 분리)

---

## 0. 한 줄 결론

두 모델 모두 **동일한 정성적 판정**에 도달했다: 이 프롬프트는 **이미 천장 근처**(baseline ~0.92 train)이고, **노이즈를 이기는 추가(MERGE)는 0건**, 양쪽 다 **안전한 제거(SUB_KEEP) 2건**만 채택했다. 가장 값진 결과는 **두 런이 독립적으로 똑같은 한 줄을 제거**했다는 수렴 신호다(Phase-4 "Phase 0/1 복귀 금지" 제약).

---

## 1. 실험 설계 (무엇을 통제했나)

| 요소 | sonnet 런 | opus 런 | 비고 |
|---|---|---|---|
| **runner** (출력 생성) | **sonnet** | **opus** | ← **유일한 독립변수** |
| grader (채점) | opus | opus | 통제 (양쪽 동일) |
| proposer (제안) | sonnet | sonnet | 통제 (anti-self-grading 강제) |
| plumbing (python/IO) | sonnet | sonnet | 통제 (기계적, 측정 무관) |
| 골든셋 / split_hash | 동일 | 동일 | 통제 |
| 루프 파라미터 | k5 / n8 / noProg3 / sub3 | 동일 | 통제 |

→ **runner만 sonnet↔opus로 바꾼 깨끗한 A/B.** grader가 양쪽 opus로 고정이라 결정·델타 비교가 정당하다.

---

## 2. 실행 메타 비교

| 지표 | sonnet | opus | 차이 |
|---|---|---|---|
| 벽시계 시간 | **5.70 h** | **4.70 h** (4h42m) | opus가 ~1h 빠름 ⚠️(아래 §7 주의) |
| 에이전트 수 | 643 | 643 | 동일 (구조가 같음) |
| 총 토큰 | 14.80M | 15.00M | +1.4% |
| 툴 호출 | 502 | 533 | +31 |
| 예산 상한 (config 문서값) | **$30** | $120 | 비대칭이나 **둘 다 미구속** — 워크플로 스크립트가 예산을 강제하지 않음(run-config 문서값일 뿐, 토큰 비교엔 무관) |

> **비용:** 워크플로 결과에 모델별 토큰 분해/USD가 없어 정확한 금액은 청구서로 확인해야 한다. **구조적 관찰:** 가장 많이 호출되는 비싼 컴포넌트인 **grader가 이미 양쪽 opus**였다. opus 런의 증분 비용은 **runner 호출분(전체 토큰의 ~10–15%)에만 opus 단가가 붙은 것**이라, "all-opus"라고 해서 비용이 배수로 뛰지 않는다. (총 토큰이 +1.4%에 그친 이유.)

---

## 3. 측정 결과 비교

| 지표 | sonnet | opus | 해석 |
|---|---|---|---|
| baseline **train** | 0.9179 | **0.9214** | 비슷, 둘 다 천장 근처 |
| baseline **heldout** | 0.8864 | **0.9091** | opus가 더 높음 |
| **eps_train** (개선 문턱) | 0.0484 | 0.0484 | 동일 |
| **eps_heldout** (회귀 가드) | 0.076 | **0.0497** | **opus가 더 좁음 = 출력이 더 일관됨** |
| 정지 사유 | n_turns(8) 소진 | n_turns(8) 소진 | 동일 |

> ⚠️ **절대 점수는 런끼리 직접 비교 금지** — 출력을 만든 모델(runner)이 다르기 때문. 위 표는 "각 런 내부에서의 baseline 위치"를 보는 용도다.

---

## 4. 턴별 결정 (양쪽 8턴)

**sonnet** — 6×DISCARD, 2×SUB_KEEP, 0×MERGE
```
t1 merge       DISCARD   train 0.9179→0.9286  held 0.8864→0.8636
t2 merge       DISCARD   train 0.9179→0.8929  held 0.8864→0.9545
t3 subtraction SUB_KEEP  train 0.9179→0.8929  held 0.8864→0.9318   ← 제거 채택
t4 merge       DISCARD   train 0.9107→0.9286  held 0.8636→0.9091
t5 merge       DISCARD   train 0.9107→0.9464  held 0.8636→0.9091
t6 subtraction SUB_KEEP  train 0.9107→0.9107  held 0.8636→0.8182   ← 제거 채택
t7 merge       DISCARD   train 0.9464→0.9107  held 0.8636→0.9318
t8 merge       DISCARD   train 0.9464→0.9107  held 0.8636→0.9545
```

**opus** — 6×DISCARD, 2×SUB_KEEP, 0×MERGE
```
t1 merge       DISCARD   train 0.9214→0.9107  held 0.9091→0.8636
t2 merge       DISCARD   train 0.9214→0.8929  held 0.9091→0.9091
t3 subtraction SUB_KEEP  train 0.9214→0.9107  held 0.9091→0.9091   ← 제거 채택
t4 merge       DISCARD   train 0.9286→0.9107  held 0.8864→0.8409
t5 merge       DISCARD   train 0.9286→0.9286  held 0.8864→0.8409
t6 subtraction SUB_KEEP  train 0.9286→0.9464  held 0.8864→0.9091   ← 제거 채택
t7 merge       DISCARD   train 0.9107→0.9286  held 0.8409→0.8636
t8 merge       DISCARD   train 0.9107→0.9286  held 0.8409→0.9318
```

**결정 프로파일이 완전히 동일하다**(6/2/0). 추가는 전부 노이즈 미달로 DISCARD — "더 넣을 게 없다"는 정직한 신호.

---

## 5. 채택된 변경 (diff)

### 🟢 수렴 (양쪽 독립적으로 같은 것을 제거) — **가장 높은 신뢰도**
두 런 모두 **Phase-4의 "Phase 0/1로는 돌아가지 않는다 — 재발견 비용 낭비다." 괄호 제약을 제거**했다.
```diff
- 연속 FAIL이면 자력 해결을 고집하지 말고 결정 게이트로 올린다. (Phase 0/1로는
- 돌아가지 않는다 — 재발견 비용 낭비다.)
+ 연속 FAIL이면 자력 해결을 고집하지 말고 결정 게이트로 올린다.
```
→ 서로 다른 runner/grader가 측정한 **두 독립 게이트가 같은 제거를 안전하다고 확인**. 이 실험에서 가장 강한 단일 신호. proposer 논리: 이 제약이 grounding/reuse 미스를 만났을 때 Phase 0 재점검(재접지)을 막아 #1 실패축을 억제한다.

### 🟡 발산 (두 번째 제거는 달랐다)
| | 제거 대상 | 줄 수 | proposer 논리 |
|---|---|---|---|
| **sonnet** | Phase-0 "도메인 용어/glossary" 항목 | −2줄 | 거의 호출 안 되는 항목, 노이즈 내 동등 |
| **opus** | 말미 "## 안티패턴" 섹션 전체 | −6줄 | Phase 0–3 + Phase 4 루브릭이 같은 내용을 이미 강제 → 순수 중복 |

opus의 안티패턴 제거는 측정상 **소폭 상승**(train +0.018, held +0.023)했으나 eps 미달 → 게이트는 "회귀 없는 제거"로 KEEP.

### 최종 산출물 크기
- 원본: **150줄**
- sonnet 최종: **147줄** (−3): 글로서리 + Phase-4 제약
- opus 최종: **143줄** (−7): 안티패턴 섹션 + Phase-4 제약

---

## 6. 핵심 발견

1. **프롬프트는 이미 강하다(saturated).** 두 모델·서로 다른 측정에서 **MERGE 0건**. baseline 0.92 + 천장 1.0 사이 헤드룸(0.08)이 train 노이즈 문턱(0.048)보다 좁아, 추가가 구조적으로 문턱을 못 넘는다. 루프의 정직한 답 = "넣지 말고 조금 덜어내라."
2. **수렴 제거 = 신뢰 1순위.** Phase-4 "복귀 금지" 제약을 양쪽이 독립 제거 → 원본에 반영할 후보 중 가장 안전.
3. **opus가 더 일관된 runner.** held-out baseline 더 높고(0.9091 vs 0.8864) **노이즈 밴드 더 좁음**(eps_h 0.0497 vs 0.076). 같은 프롬프트로 출력 분산이 작다 = 모델 품질 신호(최적화 결정과 독립인 calibration 데이터에서 나옴).
4. **"all-opus"의 비용은 배수가 아니다.** 비싼 grader가 이미 양쪽 opus라, runner만 opus로 올린 증분은 토큰 +1.4%에 그쳤다. 결과물 차이(143 vs 147줄)는 작고, 핵심 차이는 "더 비싼 runner를 썼지만 더 나은 결정은 못 만들었다"는 점.
5. **결과물 동등, 점수 향상 없음.** 두 런 모두 최종 성능 ≈ baseline(제거가 성능을 떨어뜨리지 않음). 산출물 = "동일 측정 성능의 더 작은 프롬프트."

---

## 7. 비교 가능성 + 한계 (정직한 disclosure)

- ✅ grader·골든셋·split_hash·루프 파라미터 양쪽 동일 → **결정·델타·시간·토큰 비교 가능.**
- ⚠️ **절대 점수 across-run 직접비교 X** (runner가 다름). 비교축은 (a) 런 내 델타, (b) 채택 변경 diff, (c) 시간·비용, (d) held-out 거동.
- ⚠️ **벽시계 시간(5.70 vs 4.70h)은 약하게만 해석.** 에이전트 643개 동시 실행이라 API 처리량/큐 변동이 지배적. 토큰은 거의 같으므로 "opus가 1h 빠르다"를 모델 속도 결론으로 과대해석하지 말 것 — 처리량 변동으로 보는 게 안전. (출처: opus 4.70h = 이번 완료 알림 `duration_ms 16,909,350` ÷ 3.6e6; **sonnet 5.70h는 이전 세션 완료 알림에서 기록한 외부값** — 아티팩트에 duration 미저장이라 재계산 불가.)
- ⚠️ **loader 전사(transcription) 아티팩트 (양쪽 발생, 서브-노이즈).** "파일을 verbatim으로 읽어 반환"하는 loader plumbing 에이전트가 4665자 중 ≤2자를 바꿨다(opus: 루브릭 한 줄의 동사 어미 "드러난다" 변형 + 끝 개행 누락 / sonnet: 길이 4666로 +1자). **영향:** 첫 promotion 후 currentPrompt가 실제 파일 바이트에서 재로딩되며 사라짐 → **최종 산출물(disk)은 깨끗** (sonnet은 finalPrompt가 disk와 byte-exact; opus는 result-JSON finalPrompt가 disk와 **끝 개행 1바이트만** 다르고 내용 동일). 측정 노이즈 밴드(±0.05)에 비해 1–2자는 무의미하므로 **어떤 결정·결론도 바꾸지 않는다.** 다만 **스킬 개선 포인트**로 기록: "verbatim 파일 읽기"를 LLM 에이전트에 맡기면 조용히 paraphrase가 새므로, 결정론적 파일 읽기(cat/직접 read)로 바꾸는 게 옳다.

---

## 8. S4 커밋 권고 — ✅ 옵션 A 적용됨 (2026-06-30)

> **✅ 적용:** 옵션 A를 원본 `usecase/frontend-dev.md`에 반영 — Phase-4 `(Phase 0/1로는 돌아가지 않는다 — 재발견 비용 낭비다.)` 괄호 삭제, **150 → 149줄**. 사용자 S4 승인 (측정 2-게이트 수렴 + 내용 중복[앞 문장 "Phase 2로 loop-back"이 이미 함의] 양면 확인).

| 옵션 | 변경 | 신뢰도 | 비고 |
|---|---|---|---|
| **A (권장·✅적용)** | **수렴 제거 1건만** 반영 (Phase-4 "복귀 금지" 제약 삭제, **−1줄**: 괄호가 2줄→1줄로 합쳐짐) | ★★★ 최고 | 두 독립 게이트 확인. 최소 위험·최고 확신 |
| **B** | opus 최종(143줄) 채택 = A + 안티패턴 섹션 제거 | ★★ | 안티패턴은 사람 독자용 "한눈 요약"으로 유용할 수 있음(게이트엔 중복이어도). 가독성 trade-off 판단 필요 |
| **C** | sonnet 최종(147줄) 채택 = A + 글로서리 항목 제거 | ★★ | 글로서리 항목은 도메인 용어 프로젝트엔 유용할 수 있음 |
| D | 변경 없음 | — | "이미 충분히 강하다"는 결과를 그대로 수용 |

> **추천: 옵션 A.** 두 런이 수렴한 단 하나의 변경만 원본에 반영하면 증거가 가장 단단하다. 안티패턴/글로서리 제거는 각 1개 게이트만 확인했고 사람-가독성 가치가 있어, 측정만으로 지우기엔 근거가 약하다.

---

## 9. 자산 위치

- opus 산출물: `loop/frontend-dev-opus/{prompt.current.md(143줄), history.jsonl, failure-log.jsonl}`
- sonnet 산출물: `loop/frontend-dev-sonnet/{prompt.current.md(147줄), history.jsonl, failure-log.jsonl}`
- 원본(불가침): `usecase/frontend-dev.md` · 골든셋: `usecase/golden-set.json`
- 워크플로 결과 JSON: opus `tasks/wwdq9a3ll.output` · sonnet `tasks/w87wj0d5r.output`
