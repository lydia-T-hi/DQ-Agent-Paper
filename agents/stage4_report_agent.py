"""
Stage 4: Report Agent — 합의 기반 최종 판단
3개 소스(DuckDB규칙, OpenAI판단, Python수치)를 합산해 최종 DQ 보고서를 생성합니다.
"""
import json
import os
from datetime import datetime

from langchain_core.runnables import RunnableLambda

def _severity_score(sev: str) -> int:
    return {"critical": 3, "warning": 2, "info": 1}.get(sev, 0)


def _consensus_label(sources_flagged: int, severities: list, source_types: set) -> str:
    """개선된 합의 로직:
    - DuckDB critical 위반은 단독으로도 critical (규칙 기반 = 결정론적 증거)
    - 2개 이상 소스가 플래그 → critical
    - 단일 소스 warning/info는 소스 유형에 따라 판단
    """
    has_critical = "critical" in severities
    # DuckDB 규칙은 결정론적 → critical이면 즉시 critical
    if has_critical and "duckdb" in source_types:
        return "critical"
    # 다중 소스 합의
    if sources_flagged >= 2:
        return "critical"
    # 단일 소스
    if sources_flagged == 1:
        if has_critical:
            return "critical"
        return "warning"
    return "pass"


def _build_consensus(state: dict) -> list:
    stage3a = state.get("stage3a", {})
    stage3b = state.get("stage3b", {})

    findings = []

    # DuckDB 규칙 위반
    for v in state.get("rule_violations", []):
        findings.append({
            "source":    "duckdb",
            "field":     v["field"],
            "rule":      v["rule"],
            "severity":  v["severity"],
            "count":     v["count"],
            "detail":    v["detail"],
            "examples":  v.get("examples", []),
        })

    # OpenAI 판단
    for issue in stage3a.get("issues", []):
        findings.append({
            "source":    "openai",
            "field":     issue.get("field"),
            "rule":      issue.get("issue_type"),
            "severity":  issue.get("severity"),
            "count":     None,
            "detail":    issue.get("description"),
            "confidence": issue.get("confidence"),
        })

    # Python/DuckDB 수치 검증
    for v in stage3b.get("numerical_violations", []):
        findings.append({
            "source":   "numerical",
            "field":    v["field"],
            "rule":     v["rule"],
            "severity": v["severity"],
            "count":    v["count"],
            "detail":   v["detail"],
        })
    for h in stage3b.get("hallucinations", []):
        findings.append({
            "source":   "numerical",
            "field":    h["field"],
            "rule":     "hallucination",
            "severity": "critical",
            "count":    1,
            "detail":   h["reason"],
        })

    # 필드별 합의 계산
    field_map: dict[str, dict] = {}
    for f in findings:
        key = f.get("field") or "__global__"
        if key not in field_map:
            field_map[key] = {"sources": set(), "severities": [], "findings": []}
        field_map[key]["sources"].add(f["source"])
        field_map[key]["severities"].append(f["severity"])
        field_map[key]["findings"].append(f)

    consensus = []
    for field, info in field_map.items():
        src_cnt = len(info["sources"])
        label   = _consensus_label(src_cnt, info["severities"], info["sources"])
        consensus.append({
            "field":           field,
            "consensus_level": label,
            "sources_flagged": sorted(info["sources"]),
            "source_count":    src_cnt,
            "findings":        info["findings"],
        })

    consensus.sort(key=lambda x: -x["source_count"])
    return consensus


def _load_scoring_config() -> dict:
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "dq_scoring.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _issue_dimension(issue_type: str, cfg: dict) -> str:
    itype = (issue_type or "").lower()
    for keyword, dim in cfg["issue_type_keyword_map"].items():
        if keyword in itype:
            return dim
    return cfg["default_dimension"]


def _compute_scores(state: dict) -> dict:
    """ISO/IEC 25012 차원 기반 DQ 점수 (산식은 config/dq_scoring.json — 동결 대상).

    차원 점수 = 100 x (1 - min(1, 영향레코드수/전체)), 종합 = 차원 가중합.
    구성(A1~A5)과 무관하게 동일 산식 — 소스별 가중 재분배 없음.
    """
    cfg     = _load_scoring_config()
    stage3a = state.get("stage3a", {})
    stage3b = state.get("stage3b", {})
    total   = state.get("total_records", 1) or 1

    affected = {dim: 0 for dim in cfg["dimension_weights"]}

    for v in state.get("rule_violations", []):
        dim = cfg["rule_dimension_map"].get(v["rule"], cfg["default_dimension"])
        affected[dim] += v.get("count") or 0

    for issue in stage3a.get("issues", []):
        affected[_issue_dimension(issue.get("issue_type"), cfg)] += 1

    for v in stage3b.get("numerical_violations", []):
        dim = cfg["rule_dimension_map"].get(v.get("rule"), cfg["default_dimension"])
        affected[dim] += v.get("count") or 1
    affected["accuracy"] += len(stage3b.get("hallucinations", []))

    dimension_scores = {
        dim: max(0.0, round(100 * (1 - min(1.0, cnt / total)), 1))
        for dim, cnt in affected.items()
    }
    weighted = round(sum(
        dimension_scores[dim] * w for dim, w in cfg["dimension_weights"].items()
    ))

    return {
        "dimension_scores": dimension_scores,
        "affected_counts":  affected,
        "openai_judge":     stage3a.get("overall_score"),   # 참고용 (산식 미포함)
        "weighted_final":   weighted,
    }


def _run(state: dict) -> dict:
    print("[Stage4-Report] 합의 보고서 생성 중...")

    source_file = state.get("source_file", "unknown")
    date_str    = datetime.now().strftime("%Y%m%d")
    out_dir     = "report"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{os.path.splitext(source_file)[0]}_report_{date_str}.json")

    consensus = _build_consensus(state)
    scores    = _compute_scores(state)

    stage3a = state.get("stage3a", {})
    stage3b = state.get("stage3b", {})

    critical_items = [c for c in consensus if c["consensus_level"] == "critical"]
    warning_items  = [c for c in consensus if c["consensus_level"] == "warning"]
    pass_count     = sum(1 for c in consensus if c["consensus_level"] == "pass")

    bands = _load_scoring_config()["grade_bands"]
    score_v = scores["weighted_final"]
    grade = "A" if score_v >= bands["A"] else \
            "B" if score_v >= bands["B"] else \
            "C" if score_v >= bands["C"] else "D"

    report = {
        "metadata": {
            "pipeline_id":  state.get("pipeline_id"),
            "source_file":  source_file,
            "generated_at": datetime.now().isoformat(),
            "total_records": state.get("total_records"),
        },
        "grade": grade,
        "scores": scores,
        "consensus_summary": {
            "critical_fields": len(critical_items),
            "warning_fields":  len(warning_items),
            "pass_fields":     pass_count,
            "total_findings":  sum(len(c["findings"]) for c in consensus),
        },
        "consensus": consensus,
        "stage1_rule_summary": state.get("rule_summary", {}),
        "stage2_changelog_count": len(state.get("changelog", [])),
        "stage3a_summary": {
            "overall_score": stage3a.get("overall_score"),
            "issue_count":   len(stage3a.get("issues", [])),
            "summary":       stage3a.get("summary", ""),
        },
        "stage3b_summary":   stage3b.get("summary", {}),
        "rule_violations":   state.get("rule_violations", []),
        "changelog":         state.get("changelog", []),
        "preprocessed_data": state.get("preprocessed_data", []),
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    print(f"[Stage4-Report] 완료 — 최종 DQ 점수: {score_v}/100 ({grade}등급)")
    print(f"[Stage4-Report] 보고서 저장: {out_path}")

    return {
        "output_path": out_path,
        "scores":      scores,
        "grade":       grade,
        "consensus_summary": report["consensus_summary"],
        # 실험 계측·제어 키는 최종 출력까지 보존 (ExperimentRunner가 소비)
        "pipeline_id":  state.get("pipeline_id"),
        "config":       state.get("config"),
        "run_meta":     state.get("run_meta"),
        "token_usage":  state.get("token_usage", {}),
        "stage_errors": state.get("stage_errors", []),
        "total_records": state.get("total_records"),
    }


stage4_report_agent = RunnableLambda(_run)
