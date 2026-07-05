# Stage 2B 하이브리드 백엔드(CLI/API) 구현·검증 — 2026-07-05

> 배경: CLI 방식은 temperature 미제어(04 §4 위반)·CLI 하네스 프롬프트 오염·Consistency
> 지표 교란 문제가 있어, 본실험(E1/E2)은 API 방식이 적합하다고 판단 (비교 분석은 대화 기록).
> 사용자 승인 하에 "가장 적합한 방법"으로 하이브리드 구현.

## 1. 구현

- `state["llm_backend"]` / env `DQ_LLM_BACKEND` / CLI 플래그 `--llm-backend {cli,api}` (기본 cli)
- **cli**: Claude CLI + Pro OAuth (무료) — 개발·스모크용. 기존 경로 유지
- **api**: Anthropic SDK 스트리밍 호출 — `temperature=0`, `max_tokens=32000`,
  시스템 프롬프트 캐시 브레이크포인트, max_tokens 잘림 시 명시적 실패
- **프롬프트 내용은 두 백엔드 동일** (공정성): CLI는 system+user 단일 블롭(stdin),
  API는 system/user 역할 분리 — 바이트 내용은 같음
- 로그에 `llm_backend`·`token_usage.stage2b.backend` 기록, temperature는 api일 때만 0으로 기록

## 2. 검증 (동일 표본: 주입 S1 앞 120행, GT 114셀, A3)

| 백엔드 | 결과 |
|---|---|
| cli | **정상** — F1 0.358, 모호 10건→1호출, detector=claude-sonnet-4-6, backend 필드 기록 확인 (bench-result 004회차) |
| api | 코드 경로 정상(인증·요청 도달) but **400: 크레딧 잔액 부족** — 계정에 API 크레딧 없음. 실 호출 검증은 충전 후 가능 (005·006회차) |

## 3. 검증 중 발견·수정한 결함

**partial 상태 도입**: 2B가 실패해도 run이 "ok"로 기록되던 문제 — A3가 조용히 A1로
강등된 채 정상 데이터로 집계될 뻔함 (API 크레딧 오류가 노출해준 결함).
→ `stage_errors` 존재 시 status="partial"로 표기, 분석에서 정상 run과 분리 (04 §8 결측 처리와 정합).

## 4. 동결에 대한 함의

- E1 본실험은 `--llm-backend api`로 실행 권장 → temperature=0 요건 충족, 잔여 이슈였던
  "2B temperature 미제어" 해소 (단, **API 크레딧 충전이 선행 조건**)
- 크레딧 미충전 시 대안: CLI 백엔드로 동결하고 temperature 미제어를 계획서 §4 각주로
  한계 명시 (Consistency 해석에 CLI 하네스 변동 교란 가능성 부기)
- 예상 API 비용: E1 전체 정가 ~$400-600 (A2가 최대 항목), 시스템 캐싱으로 일부 절감

## 5. 산출물

- 코드: `agents/stage2b_claude_agent.py` (백엔드 라우팅), `orchestrator.py`·`main.py`·
  `run_experiments.py` (--llm-backend), `schemas.py` (TokenUsage.backend)
- 검증 표본: `runs/injected/S1_sample120_r10_s1(.json/_ground_truth.json)`
- 실행 기록: bench-result 004(cli)·005/006(api, partial)
