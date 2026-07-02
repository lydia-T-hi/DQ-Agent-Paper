# DQAgent — Data Quality Multi-Agent Pipeline

LangChain LCEL 기반의 데이터 품질(DQ) 자동 검사 멀티에이전트 파이프라인입니다.  
DuckDB 통계 분석, 결정론적 정규화, Claude LLM 판단, OpenAI 교차검증을 조합해 데이터 품질 보고서를 자동 생성합니다.

---

## 파이프라인 아키텍처

```
입력 파일 (JSON / JSONL / CSV / Parquet / XLSX)
         │
         ▼
┌─────────────────────────────────────────────┐
│  Stage 1 — DuckDB 프로파일링 + 규칙 검증    │
│  · 필드별 통계 프로파일 생성                 │
│  · R1~R8 규칙 위반 탐지                     │
└──────────────────────┬──────────────────────┘
                       │ profile, rule_violations, data
                       ▼
┌─────────────────────────────────────────────┐
│  Stage 2A — 결정론적 정규화 (LLM 없음)      │
│  · 이름 Title Case, 이메일/날짜/나이/금액   │
│  · 국가코드 정규화, birth_date → age 계산   │
│  · Z-score > 3 이상치 → ambiguous_indices   │
└──────────────────────┬──────────────────────┘
                       │ ambiguous_indices
                       ▼
┌─────────────────────────────────────────────┐
│  Stage 2B — Claude CLI (이상치 해석 전용)   │
│  · ambiguous_indices 레코드만 처리          │
│  · 센티넬값 / 극단값 / 불일치 판단         │
│  · 비어 있으면 즉시 통과 (호출 0회)        │
└──────────────────────┬──────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌─────────────────┐       ┌─────────────────────┐
│  Stage 3A       │       │  Stage 3B            │
│  OpenAI 판사    │       │  수치 검증           │
│  (선택, 병렬)   │       │  환각 탐지 / 드리프트│
└────────┬────────┘       └──────────┬──────────┘
         └─────────────┬─────────────┘
                       ▼
┌─────────────────────────────────────────────┐
│  Stage 4 — 합의 보고서                      │
│  · 3개 소스 교차검증 합의                   │
│  · DQ 점수 산출 (0~100) + 등급 (A~F)        │
│  · JSON 보고서 저장                         │
└─────────────────────────────────────────────┘
```

---

## 에이전트 역할

### Stage 1 — DuckDB 프로파일러
**파일:** `agents/stage1_duckdb_agent.py`

DuckDB SQL로 입력 데이터의 통계 프로파일을 생성하고 8가지 규칙으로 위반을 탐지합니다.

| Rule | 대상 필드 | 내용 |
|------|-----------|------|
| R1 | 전체 | NULL 비율 > 30% |
| R2 | email | @ 없음, 길이 < 5 |
| R3 | date / birth | 미래 날짜 |
| R4 | age | 0 미만 또는 150 초과 |
| R5 | salary / amount / price | 음수 금액 |
| R6 | *_id | 중복 ID |
| R7 | 수치형 전체 | Z-score > 3 통계적 이상치 |
| R8 | birth_date + age | 교차필드 불일치 (2년 이상 차이) |

---

### Stage 2A — 결정론적 정규화
**파일:** `agents/stage2a_deterministic.py`

LLM 없이 Python 규칙으로 명백한 오류를 밀리초 안에 처리합니다.

| 필드 유형 | 처리 내용 |
|-----------|-----------|
| name | 소문자 → Title Case |
| email | 형식 오류 → null |
| date | 미래 날짜 → null |
| age | 범위 오류 → null / null이면 birth_date로 계산 |
| 금액 | 음수 → null |
| country | 2자리 알파 아닌 코드, ZZ/XX 등 → null |

처리 후 Z-score > 3 이상치가 남은 레코드를 `ambiguous_indices`에 기록 → Stage 2B로 전달

---

### Stage 2B — Claude LLM 모호성 판단
**파일:** `agents/stage2b_claude_agent.py`

`ambiguous_indices`에 해당하는 레코드만 Claude CLI로 전달해 이상치를 해석합니다.

- 이상치가 **센티넬값인지 / 정상 극단값인지 / 필드 간 불일치인지** 판단
- `ambiguous_indices`가 비어 있으면 **Claude 호출 없이 즉시 통과** (핵심 최적화)
- 병렬 청크 처리 (`ThreadPoolExecutor`, 최대 2 워커)
- Claude Pro OAuth 사용 (API 크레딧 소모 없음)

---

### Stage 3A — OpenAI 판사 _(선택)_
**파일:** `agents/stage3a_openai_judge.py`

처리된 데이터 샘플을 OpenAI에 전달해 LLM 관점의 DQ 평가를 수행합니다.  
`--skip-openai` 플래그로 건너뛸 수 있습니다.

---

### Stage 3B — 수치 검증
**파일:** `agents/stage3b_numerical_agent.py`

Stage 2B 결과를 DuckDB로 재검증합니다.

- **환각 탐지**: LLM이 생성한 값이 실제 분포 범위를 벗어나면 hallucination으로 표시
- **드리프트 탐지**: 처리 전후 통계 분포 변화 측정
- **수치 위반 재검증**: Stage 1 규칙을 처리 후 데이터에 재적용

---

### Stage 4 — 합의 보고서
**파일:** `agents/stage4_report_agent.py`

3개 소스(DuckDB / OpenAI / 수치검증)의 판단을 합산해 최종 DQ 점수와 등급을 산출합니다.

**합의 로직:**
```
DuckDB critical 단독    → critical  (결정론적 증거 최우선)
2개 이상 소스 플래그   → critical
1개 소스 + critical    → critical
1개 소스 + warning     → warning
이상 없음              → pass
```

**DQ 등급:**
| 점수 | 등급 | 상태 |
|------|------|------|
| 90 ~ 100 | A | 우수 |
| 80 ~ 89  | B | 양호 |
| 70 ~ 79  | C | 주의 |
| 60 ~ 69  | D | 위험 |
| ~ 59     | F | 불량 |

---

## 파일 구조

```
DQAgent/
├── main.py                        # CLI 진입점
├── orchestrator.py                # LCEL 파이프라인 체인 정의
├── schemas.py                     # 스테이지 간 상태 계약 (TypedDict)
├── requirements.txt               # 패키지 목록
├── .env.example                   # 환경변수 예시
├── CLAUDE.md                      # Claude Code 컨텍스트 문서
├── run_compare.sh                 # 실행 + Before/After 비교 + ROI 분석 통합 스크립트
│
├── agents/
│   ├── stage1_duckdb_agent.py     # DuckDB 프로파일링 + 규칙 검증
│   ├── stage2a_deterministic.py   # 결정론적 정규화
│   ├── stage2b_claude_agent.py    # Claude LLM 이상치 판단
│   ├── stage3a_openai_judge.py    # OpenAI 교차검증 (선택)
│   ├── stage3b_numerical_agent.py # 수치 재검증 + 환각 탐지
│   └── stage4_report_agent.py     # 합의 보고서 생성
│
├── tools/
│   ├── compare.py                 # 원본 ↔ 처리본 변경 비교 (ANSI 색상)
│   ├── compare_duckdb.py          # DuckDB SQL 기반 비교 분석
│   ├── compare_table.py           # Before/After 표 + 시간 비교 출력
│   ├── roi_pandas.py              # pandas 기반 ROI 분석 + Excel 저장
│   └── make_ppt.py                # 소개 PPT 자동 생성
│
├── tests/
│   ├── test_stage1.py
│   ├── test_stage2a.py
│   ├── test_stage3a.py
│   ├── test_stage3b.py
│   └── test_stage4.py
│
└── .claude/
    ├── settings.json              # Claude Code 훅 설정
    ├── commands/                  # Claude Code 커스텀 슬래시 커맨드
    │   ├── dq-run.md              # /dq-run  — 파이프라인 실행
    │   ├── dq-result.md           # /dq-result — Before/After 결과 표
    │   └── dq-cost.md             # /dq-cost — ROI/비용 분석
    └── hooks/                     # Claude Code 자동화 훅 (bash)
        ├── check_env.sh           # 세션 시작 시 환경 점검
        ├── check_syntax.sh        # Python 파일 편집 후 문법 검사
        ├── guard_api_key.sh       # API 키 노출 방지
        └── notify_report.sh       # 파이프라인 완료 알림
```

---

## 설치

```bash
git clone https://github.com/lydia-T-hi/DQAgent.git
cd DQAgent
pip install -r requirements.txt
```

**환경변수 설정:**
```bash
cp .env.example .env
# .env 파일을 열어 OPENAI_API_KEY 입력 (--skip-openai 사용 시 불필요)
```

> **Claude CLI 설치 필요** (Stage 2B용):  
> Claude Pro 구독 후 [claude.ai/code](https://claude.ai/code) 에서 CLI 설치

---

## 실행 방법

### Python 직접 실행

```bash
python main.py data.json
python main.py data.json --batch-size 100 --skip-openai
```

**옵션:**
| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--batch-size N` | 500 | 배치 크기 |
| `--skip-openai` | False | Stage 3A OpenAI 판단 건너뜀 |

### 실행 + 비교 + ROI 한 번에 (run_compare.sh)

```bash
chmod +x run_compare.sh
./run_compare.sh data.json
./run_compare.sh data.json --batch-size 200
```

실행 후 다음을 자동으로 출력합니다:
- Stage 1 위반 탐지 표
- Before / After 변경 내역 표
- pandas ROI 분석 (Excel 저장 포함)
- Agent 소요시간 vs 수동 검토 속도 비교

### Claude Code 커스텀 커맨드

Claude Code 채팅창에서 슬래시 커맨드로 실행할 수 있습니다.

| 커맨드 | 설명 |
|--------|------|
| `/dq-run [파일]` | 파이프라인 실행. 파일 미지정 시 최근 파일 자동 탐지 |
| `/dq-result` | 최신 보고서 Before/After 표 + Critical 위반 목록 출력 |
| `/dq-cost [--hourly-rate N]` | ROI 분석. 인건비 기본값 30,000원/시간 |

---

## 개별 스테이지 테스트

```bash
# Stage 1 (프로파일링 + 규칙 검증)
python tests/test_stage1.py sample_input.jsonl

# Stage 2A (결정론적 정규화) — Stage 1 먼저 실행 필요
python tests/test_stage2a.py

# Stage 3B, 4
python tests/test_stage3b.py
python tests/test_stage4.py
```

---

## 결과 비교 도구

```bash
# ANSI 컬러 변경 내역 비교
python tools/compare.py sample_input.json report/output_report.json

# DuckDB SQL 분석 (8가지 프리셋 쿼리)
python tools/compare_duckdb.py sample_input.json report/output_report.json --all

# Before/After 표 + 시간 비교
python tools/compare_table.py sample_input.json report/output_report.json

# pandas ROI 분석 + Excel 저장
python tools/roi_pandas.py sample_input.json report/output_report.json --hourly-rate 30000 --export roi_result.xlsx
```

---

## Claude Code 훅

`.claude/hooks/` 의 bash 스크립트가 Claude Code 이벤트에 자동 실행됩니다.

| 이벤트 | 파일 | 동작 |
|--------|------|------|
| `SessionStart` | `check_env.sh` | Claude CLI 설치 확인, report/ 디렉토리 생성, ANTHROPIC_API_KEY 경고 |
| `PreToolUse (Bash)` | `guard_api_key.sh` | 명령어에 API 키 직접 포함 시 실행 전 차단 |
| `PostToolUse (Write\|Edit)` | `check_syntax.sh` | .py 파일 수정 후 문법 오류 즉시 알림 |
| `PostToolUse (Bash)` | `notify_report.sh` | main.py 완료 시 최신 보고서 경로 자동 주입 |

훅 수동 테스트:
```bash
bash .claude/hooks/check_env.sh
echo '{"tool_input":{"file_path":"agents/stage1_duckdb_agent.py"}}' | bash .claude/hooks/check_syntax.sh
echo '{"tool_input":{"command":"python main.py data.json"},"tool_response":{"exit_code":0}}' | bash .claude/hooks/notify_report.sh
```

---

## 실행 결과 예시

```
================================================================
  DQ Multi-Agent Pipeline
  파일     : customer_data.json
  배치크기 : 100
  OpenAI   : 건너뜀 (--skip-openai)
================================================================

[Stage1] 완료 — 위반 6건 (C:4 W:0 I:2)
[Stage2A-Det] 완료 — 변경 58건 / 이상치(2B 대상) 2건
[Stage2B-Claude] 모호성 판단 시작 — 2건 대상
[Stage2B-Claude] 완료 — 추가 변경 3건 / 해석 4건
[Stage3B-Numerical] 완료 — 환각 0건, 수치위반 2건
[Stage4-Report] 완료 — 최종 DQ 점수: 94/100 (A등급)

================================================================
  소요 시간    : 110.7초
  최종 DQ 점수 : 94/100  [A등급 — 우수]
  Critical     : 6개 필드
  Warning      : 0개 필드
  보고서       : report/customer_data_report_20260702.json
================================================================
```

---

## 지원 입력 형식

| 형식 | 확장자 |
|------|--------|
| JSON | `.json` |
| JSON Lines | `.jsonl` |
| CSV | `.csv` |
| Parquet | `.parquet` |
| Excel | `.xlsx` |

중첩 JSON (records 키 아래 배열) 자동 언래핑 지원

---

## 기술 스택

| 구성요소 | 용도 |
|----------|------|
| LangChain LCEL | 파이프라인 체인 (`\|` 연산자, 병렬 실행) |
| DuckDB | 통계 프로파일링, 규칙 검증, 비교 분석 |
| Claude CLI (OAuth) | 이상치 해석 LLM (API 크레딧 소모 없음) |
| OpenAI API | 교차검증 판사 (선택) |
| pandas | 데이터 변환 및 ROI 분석 |
| tabulate | 터미널 표 출력 |
| python-pptx | 소개 PPT 자동 생성 |
| TypedDict schemas | 스테이지 간 상태 계약 |
