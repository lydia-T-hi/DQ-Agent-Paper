# 계획 개정: Detector 모델 변경 (claude-sonnet-4-6 → gemini-2.5-flash) — 2026-07-05

> 04 문서 §4 "모델 고정" 개정. **동결 선언 전 변경이므로 §8 재실행 조항 위반 아님.**

## 사유

- Anthropic API 크레딧 결제 불가 (사용자 확인) → api 백엔드로 E1 실행 불가
- 사용자 지시: "다른 api로 변경해서 진행" → 후보 비교 후 Gemini 채택 (비교표는 대화 기록,
  요지: 이종 검증 유지·변경 범위 최소·무료 티어로 결제 문제 원천 해소)

## 개정 내용 (04 §4 대응)

| 항목 | 개정 전 | 개정 후 |
|---|---|---|
| Detector (2B, 본실험 api) | claude-sonnet-4-6 (Anthropic API) | **gemini-2.5-flash** (Google, temperature=0, thinking_budget=0, JSON 강제) |
| Detector (2B, 개발 cli) | claude-sonnet-4-6 (CLI OAuth) | 변동 없음 (개발 전용 — 논문 수치에 미사용) |
| Validator (3A) | gpt-4o | 변동 없음 |
| 이종 검증 구도 | Claude ↔ GPT | **Gemini ↔ GPT** (자기선호 회피 논리 동일 유지) |

## 논문 서술 유의

- 3장: 이종 모델 검증의 근거(Panickssery)는 벤더 조합과 무관 — Gemini↔GPT로 서술
- 스모크 비교치(sonnet 기준 F1)는 파일럿 참고용 — **E1 기준선은 Gemini로 재확립** 필요
- thinking_budget=0 명시 (비용 계측 순수성 — CLI thinking 포함 문제의 재발 방지)
- 무료 티어 사용 시에도 비용 지표는 공시 단가 환산액으로 계상 (pricing.json 원칙 유지)

## 구현 상태

- 코드: stage2b api 백엔드 = google-genai SDK (usage_metadata 계측 실패 시 실행 실패,
  429 백오프 재시도), pricing.json에 gemini-2.5-flash($0.30/$2.50) 등록
- ~~검증 대기~~ → **검증 완료 (2026-07-05, 키 설정 직후)**

## 검증 결과 (프로브 → 표본 → 전체 S1, 모두 통과)

| 실행 (A3, ρ10 s1) | F1 | P | R | USD/run | 지연 |
|---|---|---|---|---|---|
| 표본 120행 — sonnet(CLI) 참고 | .3566 | .2965 | .4474 | — | 143s |
| 표본 120행 — **gemini(API)** | **.3649** | .3041 | .4561 | $0.004 | 11s |
| 전체 S1 — sonnet(CLI) 참고 | .2648 | .2221 | .3280 | $1.49* | 360s |
| 전체 S1 — **gemini(API)** | **.2902** | .2438 | .3584 | **$0.041** | **29s** |

*CLI 수치는 thinking 토큰 포함으로 과대 계상 (참고용). bench-result 009·010회차.

- **F1 오히려 개선** (+0.025), temperature=0·thinking 0 확인, 계측·429 재시도 경로 정상
- 비용: A3 회당 **$0.04** → **E1 전체 재추정 ~$3-5** (당초 $550-650 → 스키마 v3 + Gemini)
- 지연: 회당 29초 → E1 100회가 1~2시간 규모로 단축 (일정 압박 해소)
- **남은 동결 차단 이슈 없음** — 이 커밋 해시로 동결 선언 가능
