# TODO — DQ 멀티에이전트 논문 (갱신: 2026-07-05 2차 세션)

> 이번 세션 기록: `paper-hist/2026-07-05_ruleset-v2-freeze-prep.md` (규칙 개정 v2 + 스모크)
> 이전 기록: `paper-hist/2026-07-05_E0-pilot-log.md` (E0 파일럿)

## ✅ 완료 (2차 세션)

- [x] **Detector 모델 고정**: 2B CLI `--model claude-sonnet-4-6` (04 §4 그대로, 로그로 검증)
- [x] **few-shot k=3** 2B 프롬프트 적용 → `prompts/stage2b_system_v2_fewshot.txt` (부록 A)
- [x] **DQ 점수 룰 v2**: ISO 25012 차원 기반, config 무관 동일 산식 → `config/dq_scoring.json`
- [x] **비용 산정 룰**: `config/pricing.json`(실행일 단가) + 러너 USD 자동 산출
- [x] **3A 토큰 계측(지점 ②)** + 입력 샘플링 상한 80건 (컨텍스트 초과 방지)
- [x] **2A 모호성 판정 교체**: 평균/표준편차 → 중앙값/MAD 수정 Z(3.5) + 교차필드.
      (극단값 자기 마스킹으로 ambiguous=0 → H1 검정 불능이던 치명 결함 해소)
- [x] F1 예측 정의 확정(전체 개입) / 2B 스키마 현행 동결 — 사용자 결정
- [x] 스모크: 주입 S1 A1(F1 .247) / A3(F1 .268, $2.06) / A5(백그라운드) + Hospital A1(F1 .048)
- [x] run_id에 rep 병기 (Consistency 반복 로그 덮어쓰기 방지)

## 🔴 P0 — E1 동결 선언 전 마지막 확인

- [ ] **API 크레딧 충전** (사용자): 스키마 v3로 E1 예산이 **~$50-90**로 재추정됨
      ($100 충전 권장). 충전 후 BKVapi 재실행으로 API 경로 E2E 검증 → 동결 선언
- [ ] **비용 지표는 API 실측으로**: CLI 출력 토큰은 thinking 포함이라 과대 계상
      (paper-hist/2026-07-05_schema-v3-slim.md §3) — E1 본실험은 반드시 api 백엔드
- [x] ~~A5 스모크 로그 확인~~ — 3A usage 승격·USD 합산 검증 완료
- [x] ~~2B temperature 미제어~~ — API 백엔드로 해소 (크레딧 충전 조건부),
      하이브리드 구현·검증: paper-hist/2026-07-05_llm-backend-hybrid.md
- [ ] **동결 선언**: 프롬프트·dq_scoring.json·pricing.json·합의 로직·모델 버전을
      커밋 해시로 paper-hist에 기록 (05 §6) — **커밋 필요 (이번 세션 변경분 미커밋)**
- [ ] E1 실행 시간 산정: A3 ~9.3분/회 관측 → 50회 매트릭스 예상 소요·일정 검토.
      **A2(전 행→2B)는 1,000행 = 50호출 ≈ 30분+/회** — E1 매트릭스에서 A2 비중 확인
- [ ] gpt-4o 단가 공시 재확인 (pricing.json에 "재확인 필요" 표기됨)

## 🟡 P1 — E1 주실험 (7/13~17 S1 전반 50회)

- [ ] 주입 매트릭스: S1 × ρ{10,20}% × 시드{1..5} = 10배치 생성 (s1·s2 r10은 생성됨)
- [ ] E1 S1 50회 (A1~A5 × 10배치) — 야간 배치 실행 스크립트 검토
- [ ] Consistency: s=1 배치 고정 5회 재실행
- [ ] 유형별(T1~T5) F1 분해 스크립트
- [ ] S2 원천 최종 선정 → placeholder 교체 (`data/S2_candidate/`는 실험 사용 금지)

## 🟢 P2 — 이후

- [ ] E2 (Hospital/Flights) A1/A3/A5 — A1 기준선 F1 0.048로 낮음: 도메인 규칙 일반화 여부 결정
      (E2는 F1 상한 추정치로만 보고)
- [ ] 외부 베이스라인(Raha 재현) 여부 결정
- [ ] Wilcoxon + Cliff's delta + Holm 분석 스크립트
- [ ] 05 문서 2B 셀 단위 스키마 개편 — **개정판 과제로 이월** (근거 데이터: 출력 토큰이
      비용 지배 — 스모크 A3에서 118K 출력/5호출)
- [ ] 선행연구 원문 인용 확정 (paper-summaries §4 목록)

## 📌 메모 / 주의사항

- **E0 결과(구 산식·구 프롬프트)는 이번 개정으로 무효** — E0은 논문 미포함이라 재실행 불요
- DQ 점수는 여전히 구성 간 비교 금지(탐지 기반 점수) — 비교는 F1/비용만
- 비용 정의 = API 공시 단가 환산액 (2B OAuth 실청구 0이어도 계상) — pricing.json _doc 참조
- `.env`의 ANTHROPIC_API_KEY 제거 검토 (CLAUDE.md 권고)
- report/ 파일명은 날짜 기준 덮어씀 — 정본은 runs/
- 00_thesis-design_v4 문서 저장소에 없음 — 추가 필요
- **이번 세션 변경분 커밋 안 됨** — 동결 선언과 함께 커밋 권장
