# 전체 에이전트 아키텍처 명세 — v1

> 작성일: 2026-07-04 | 상위 문서: 00_thesis-design_v4, 04_experiment-plan_v1
> 범위: 파이프라인 에이전트 7종 + 실험 지원 컴포넌트 3종의 역할·계약·구현 지침

---

## 1. 전체 구조

```mermaid
graph LR
  I[입력 데이터] --> P[Profiler<br/>stage1 DuckDB]
  P --> D1[Detector-D<br/>stage2a 결정론]
  D1 -->|ambiguous_indices| D2[Detector-LLM<br/>stage2b Claude]
  D2 --> V[Validator<br/>stage3a GPT Judge]
  D2 --> H[HC<br/>stage3b 통계 검증]
  V --> R[Reporter<br/>stage4 합의]
  H --> R
  D1 --> R
  R --> O[DQ 리포트]

  subgraph 실험 지원 - 파이프라인 외부
    E[ErrorInjector] -.ground truth.-> M[Evaluator]
    C[CostMeter] -.token_usage.-> M
    X[ExperimentRunner] -.--config A1-A5.-> P
  end
```

원칙: **측정 대상(에이전트 7종)과 측정 장치(지원 3종)를 코드 수준에서 분리** —
지원 컴포넌트는 파이프라인 상태를 읽기만 하고 판단에 개입하지 않는다.

## 2. 파이프라인 에이전트 명세

### 2.1 Orchestrator (`orchestrator.py`)
- 역할: LCEL 체인 조립, `--config`에 따른 스테이지 온오프, 상태 계약 검증
- 입력: 원본 테이블 경로, config ∈ {A1..A5} / 출력: 최종 `PipelineState`
- **v1 변경점**: config 분기 로직 신설 — A2는 2A를 우회하고 전 행을 2B로 라우팅,
  A1/A3는 기존 경로, A4는 3B 제외, A5는 전체
- 실패 정책: 스테이지 예외는 상태에 `stage_errors[]`로 기록 후 후속 진행(부분 결과 보존)

### 2.2 Profiler (stage1, LLM 없음)
- 역할: DuckDB 프로파일링(행/열/타입/분포/유일성) + R1~R8 규칙 위반 후보 산출
- 출력 키: `profile`, `rule_violations[]` (row, col, rule_id)
- 규칙-오류유형 대응은 04 문서 §3.1 표를 단일 진실로 참조

### 2.3 Detector-D (stage2a, LLM 없음)
- 역할: 확정적 정규화(공백·대소문자·포맷 통일) + **ambiguous_indices 산출**
- ambiguous 판정 기준(명문화 필요 — 논문 3장 기술 대상):
  규칙 위반이되 자동 수정 불가(센티널 의심값, 범위 경계값, 교차필드 충돌)인 셀
- 출력 키: `normalized_data`, `ambiguous_indices[]`, `deterministic_flags[]`

### 2.4 Detector-LLM (stage2b, Claude)
- 역할: ambiguous 셀 한정 해석 판단 — 센티널/정상 극단값/오탈자/불일치 분류
- 프롬프트: few-shot k=3, 배치 20행/호출, JSON 강제 출력 스키마
  `{row, col, verdict, corrected_value|null, confidence, reason}`
- **A2 모드**: 동일 프롬프트·동일 k·동일 배치로 전 행 처리 (공정성 프로토콜)
- 토큰 계측 지점 ①

### 2.5 Validator (stage3a, GPT — 이종 모델 Judge)
- 역할: 2B 판단의 교차검증 — 각 verdict에 agree/disagree + 사유
- 이종 모델 사용 근거: 자기선호 편향 회피 (논문 3장 인용: LLM-as-a-Judge)
- 출력: `validation[]` (판단 단위 agree 여부) / 토큰 계측 지점 ②

### 2.6 HallucinationChecker (stage3b, LLM 없음)
- 역할: 2B가 제시한 corrected_value의 분포 정합 검증 (열 분포 대비 z-score·범위·타입)
- 논문 용어: "분포 기반 이상 수정 탐지" (환각 일반 아님 — v3 C6 용어 정밀화 준수)
- 출력: `hc_flags[]` (수정값이 분포 이탈인 판단 목록)

### 2.7 Reporter (stage4)
- 역할: 3소스(결정론 플래그, 2B+3A 검증 결과, 3B 플래그) 합의 → 셀 단위 최종 판정
  + DQ 점수/등급
- 합의 규칙(사전 고정, 민감도 분석 대상): 기본 다수결, 동률 시 결정론 우선
- 출력: `final_flags[]`, `dq_score`, `report`

## 3. 실험 지원 컴포넌트

### 3.1 ErrorInjector (`tools/inject_errors.py`) — 신규
- 04 문서 §3 프로토콜 구현: 유형 5종 × 오류율 × 시드 → 오염 데이터 + ground truth JSON
- CLI: `python tools/inject_errors.py --input S1.csv --rate 0.1 --seed 2 --out runs/`

### 3.2 CostMeter (횡단 관심사) — 신규
- 2B·3A 호출 래퍼에서 usage(입출력 토큰) 수집 → `PipelineState.token_usage`
- USD 환산은 분석 단계에서 후처리(단가표 별도 파일 `pricing.json`, 일자 기록)
- 원칙: 계측 실패 시 실행 자체를 실패 처리 (비용 결측 데이터 금지)

### 3.3 ExperimentRunner (`run_experiments.py`) — 신규
- 04 문서 §1 매트릭스 순회: config × dataset × rate × seed → 실행·로그 저장(§6 스키마)
- Evaluator 내장: ground truth 대비 P/R/F1 산출, 유형별 분해

## 4. 상태 계약 확장 (`schemas.py`)

기존 `PipelineState`에 추가:

```python
config: Literal["A1","A2","A3","A4","A5"]
run_meta: RunMeta            # run_id, dataset, error_rate, seed, model versions
token_usage: dict[str, TokenUsage]   # stage별 {input, output}
stage_errors: list[StageError]       # 스테이지 예외 기록
```

계약 원칙: 모든 스테이지는 자신이 소비·생산하는 키만 접근 (테스트로 강제).

## 5. 구현 순서 (04 문서 일정과 정합)

1. schemas 확장 + CostMeter (토큰 계측) — **최우선, 이것 없이는 모든 실험 무효**
2. Orchestrator config 분기 (--config A1..A5)
3. ErrorInjector + S1 생성 스크립트
4. ExperimentRunner + Evaluator
5. E0 파일럿으로 전체 검증 → 이후 프롬프트·합의 규칙 동결(freeze) 선언

## 6. 동결 정책

E1 시작 시점에 프롬프트·규칙·합의 로직·모델 버전을 커밋 해시로 동결하고
paper-hist에 선언 기록. 이후 변경 시 해당 실험 전체 재실행 (04 §8 준수).
