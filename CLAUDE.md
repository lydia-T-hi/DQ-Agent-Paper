# DQ Multi-Agent Pipeline — CLAUDE.md

## 프로젝트 개요

데이터 품질(DQ) 자동 검사 멀티에이전트 파이프라인.
LangChain LCEL 체인으로 DuckDB → 결정론적 처리 → Claude LLM → 수치검증 → 보고서 순으로 실행됩니다.

---

## 실행

```bash
python main.py <파일> [--batch-size N] [--skip-openai]

# 예시
python main.py customer_data_quality_test_50.json --batch-size 100 --skip-openai
```

**지원 입력 형식:** JSON, JSONL, CSV, Parquet, XLSX

---

## 파이프라인 아키텍처

```
Stage 1 (DuckDB)          → 프로파일링 + 규칙 위반 탐지 (R1~R8)
Stage 2A (결정론적)        → LLM 없이 명백한 오류 즉시 수정
Stage 2B (Claude CLI)     → ambiguous_indices의 이상치 레코드만 처리
Stage 3A (OpenAI, 선택)   → ┐ 병렬 실행
Stage 3B (수치검증)        → ┘
Stage 4  (보고서)          → 3개 소스 합의 → DQ 점수 + 등급
```

---

## 핵심 파일

| 파일 | 역할 |
|---|---|
| `orchestrator.py` | LCEL 체인 정의 (파이프라인 진입점) |
| `schemas.py` | 스테이지 간 상태 계약 (TypedDict) |
| `agents/stage1_duckdb_agent.py` | DuckDB 프로파일링 + R1~R8 규칙 |
| `agents/stage2a_deterministic.py` | 결정론적 정규화 |
| `agents/stage2b_claude_agent.py` | Claude CLI 모호성 판단 |
| `agents/stage3b_numerical_agent.py` | 환각 탐지 + 수치 재검증 |
| `agents/stage4_report_agent.py` | 합의 보고서 생성 |
| `tools/compare.py` | 원본 ↔ 처리본 변경 비교 |
| `tools/compare_duckdb.py` | DuckDB SQL 비교 분석 |

---

## 스테이지 간 상태 계약

`schemas.py`의 `PipelineState` TypedDict가 각 스테이지 입출력 키를 정의합니다.

**2A → 2B 라우팅 키:** `ambiguous_indices: List[int]`
- 비어 있으면 Stage 2B는 즉시 통과 (Claude 호출 0회)
- 통계적 이상치(Z-score > 3)가 처리 후에도 남은 레코드 인덱스

**Stage 2 Changelog 구조:**
```python
{
  "record_index": int,
  "field": str,
  "action": "normalize|fill|flag|keep",
  "original": Any,
  "new_value": Any,
  "reason": str,
  "stage": "2a" | "2b"
}
```

---

## CRITICAL: Claude CLI 환경 설정

Stage 2B는 Claude CLI를 subprocess로 호출합니다.

```python
# ANTHROPIC_API_KEY를 반드시 제외해야 합니다.
# 포함되면 OAuth 대신 API 크레딧을 소모합니다.
env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
```

- **올바른 인증:** Claude Pro OAuth (무료)
- **잘못된 인증:** `.env`의 `ANTHROPIC_API_KEY` → 크레딧 소모
- 프롬프트는 반드시 tempfile을 통해 binary stdin으로 전달 (Git Bash 인코딩 오류 방지)

---

## 환경 변수 (.env)

```
OPENAI_API_KEY=sk-...    # Stage 3A 활성화 시 필요 (--skip-openai 시 불필요)
# ANTHROPIC_API_KEY는 설정하지 않는 것을 권장 (Claude CLI가 OAuth 사용)
```

---

## 규칙 추가 방법 (Stage 1)

`agents/stage1_duckdb_agent.py`의 `_run_rules()` 함수에 규칙을 추가합니다.

```python
# R9 예시: 전화번호 형식 검증
if any(k in clow for k in ("phone", "tel", "mobile")):
    def r9():
        cnt = conn.execute(f"""
            SELECT COUNT(*) FROM {expr}
            WHERE {safe} IS NOT NULL
            AND NOT REGEXP_MATCHES(CAST({safe} AS VARCHAR), '^[0-9\\-\\+\\s\\.\\(\\)]+$')
        """).fetchone()[0]
        if cnt:
            add("invalid_phone", "warning", cnt, f"전화번호 형식 오류 {cnt}건")
    safe_exec(r9)
```

---

## 결정론적 처리 확장 (Stage 2A)

`agents/stage2a_deterministic.py`에 필드 처리 함수를 추가합니다.

```python
# _process_record() 내부의 if/elif 체인에 추가
elif any(k in flow for k in ("phone", "tel", "mobile")):
    new_val, reason = _proc_phone(value)
```

---

## 테스트

```bash
# 개별 스테이지 테스트 (stage1_output.json이 있어야 함)
python tests/test_stage1.py sample_input.jsonl
python tests/test_stage2a.py          # stage1_output.json 사용
python tests/test_stage3b.py
python tests/test_stage4.py

# 비교 도구
python tools/compare.py <원본.json> <report.json>
python tools/compare_duckdb.py <원본.json> <report.json> --all
```

테스트 중간 출력은 `tests/output/` 에 저장됩니다.

---

## 개발 원칙

- **스테이지 분리 유지:** 결정론적으로 처리 가능한 것은 2A에서 처리, 2B(Claude)는 이상치 해석 전용
- **상태 계약 준수:** 새 키 추가 시 `schemas.py`의 `PipelineState`도 함께 업데이트
- **Stage 4 합의 로직:** DuckDB critical은 단독으로도 critical (결정론적 증거 우선)
- **프롬프트 수정 시:** `_SYSTEM_INSTRUCTIONS` 상단에 응답 JSON 구조를 명시해야 파싱 실패를 방지

---

## 산출물

| 위치 | 내용 |
|---|---|
| `report/` | 최종 DQ 보고서 JSON (날짜별 파일명) |
| `tests/output/` | 스테이지별 중간 출력 (테스트용) |
| `runs/` | 실험 실행 로그 (1실행 1파일, 04 문서 §6 스키마 — 정본) |
| `bench-result/` | **실험회차별 기록** — `{회차:03d}_{날짜}/` 폴더에 summary.md·json + 로그 사본 + **시각화 PNG**(metrics, cost_latency). `run_experiments.py`가 실행마다 자동 생성·**자동 커밋+push(paper 리모트)** (러너 1회 실행 = 1회차, `--no-commit`으로 생략 가능). 실험은 반드시 러너를 통해 실행할 것 |

**커밋 규칙**: 실험 기록은 러너가 자동 커밋. 그 외 중요한 변경(에이전트 코드, 계약,
프롬프트, paper-hist 기록)도 작업 단위가 끝나면 커밋 + `paper` 리모트 push.
