"""
파이프라인 스테이지 간 상태 계약 정의 (TypedDict)
스테이지 간 키 이름과 타입을 명시해 무형식 dict 전달의 위험을 줄입니다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from typing import NotRequired, TypedDict
except ImportError:                        # Python < 3.11
    from typing_extensions import NotRequired, TypedDict


class FieldProfile(TypedDict):
    type:           str
    total:          int
    null_count:     int
    null_pct:       float
    distinct_count: int
    top_values:     List[Any]
    min:            NotRequired[Any]
    max:            NotRequired[Any]
    avg:            NotRequired[Optional[float]]
    stddev:         NotRequired[Optional[float]]


class Violation(TypedDict):
    field:     str
    rule:      str
    severity:  str          # critical | warning | info
    count:     int
    detail:    str
    examples:  List[str]


class ChangeEntry(TypedDict):
    record_index: int
    field:        str
    action:       str       # normalize | fill | flag | keep
    original:     Any
    new_value:    Any
    reason:       str
    stage:        str       # "2a" | "2b"


class TokenUsage(TypedDict):
    """LLM 스테이지별 토큰 계측 (CostMeter). USD 환산은 분석 단계에서 후처리."""
    input:          int
    output:         int
    calls:          int
    cache_creation: NotRequired[int]
    cache_read:     NotRequired[int]
    model:          NotRequired[str]     # 실행에 사용된 모델 버전 문자열


class StageError(TypedDict):
    """스테이지 예외 기록 — 예외 발생 시 중단 대신 기록 후 후속 진행 (부분 결과 보존)"""
    stage:   str
    error:   str
    fatal:   bool


class RunMeta(TypedDict):
    """실험 실행 메타데이터 (04 문서 §6 로그 스키마 대응)"""
    run_id:     str
    experiment: NotRequired[str]         # E0 | E1 | E2
    dataset:    NotRequired[str]
    error_rate: NotRequired[Optional[float]]
    seed:       NotRequired[Optional[int]]


class Interpretation(TypedDict):
    rule:           str
    field:          str
    interpretation: str
    recommendation: str     # fix | flag | ignore


class PipelineState(TypedDict):
    # ── Stage 1 ──────────────────────────────────────────
    pipeline_id:     str
    source_file:     str
    total_records:   int
    batch_count:     int
    batch_size:      int
    profile:         dict        # field → FieldProfile
    rule_violations: List[Violation]
    rule_summary:    dict
    data:            List[List[dict]]

    # ── Stage 2A / 2B ────────────────────────────────────
    original_records:  NotRequired[List[dict]]
    preprocessed_data: NotRequired[List[dict]]
    changelog:         NotRequired[List[ChangeEntry]]
    interpretations:   NotRequired[List[Interpretation]]
    ambiguous_indices: NotRequired[List[int]]   # 2A → 2B 전달

    # ── Stage 3 ──────────────────────────────────────────
    stage3a: NotRequired[dict]
    stage3b: NotRequired[dict]

    # ── 계측 (CostMeter) ─────────────────────────────────
    token_usage: NotRequired[Dict[str, TokenUsage]]   # stage명 → 사용량

    # ── 실험 제어 (04/05 문서 §4) ────────────────────────
    config:       NotRequired[str]                    # "A1".."A5" (기본 A5)
    run_meta:     NotRequired[RunMeta]
    stage_errors: NotRequired[List[StageError]]
