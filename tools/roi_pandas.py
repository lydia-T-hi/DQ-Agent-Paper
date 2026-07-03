"""
ROI 측정 도구 — pandas 기반 Before / After 자동 비교

원본 파일과 파이프라인 보고서(report JSON)를 비교해
데이터 품질 개선 지표와 추정 ROI를 자동으로 산출합니다.

Usage:
  python tools/roi_pandas.py <원본파일> <보고서파일>
  python tools/roi_pandas.py <원본파일> <보고서파일> --hourly-rate 30000
  python tools/roi_pandas.py <원본파일> <보고서파일> --export roi_result.xlsx
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import datetime

import pandas as pd


class _Tee:
    """stdout을 터미널과 파일에 동시에 출력. 파일에는 ANSI 코드를 제거."""
    def __init__(self, term, file_):
        self._term = term
        self._file = file_
    def write(self, data):
        try:
            self._term.write(data)
        except UnicodeEncodeError:
            enc = getattr(self._term, "encoding", "utf-8") or "utf-8"
            self._term.write(data.encode(enc, errors="replace").decode(enc))
        self._file.write(re.sub(r"\033\[[0-9;]*m", "", data))
    def flush(self):
        self._term.flush()
        self._file.flush()
    def isatty(self):
        return self._term.isatty()

# ── 기본 가정값 ─────────────────────────────────────────────────────────────
_DEFAULT_HOURLY_RATE    = 30_000   # 원/시간 (수동 검토자 인건비)
_MANUAL_MINUTES_PER_100 = 120      # 100건당 수동 검토 시간(분) 기본 가정


# ── 데이터 로딩 ──────────────────────────────────────────────────────────────
def _load_original(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".jsonl":
        with open(path, encoding="utf-8") as f:
            records = [json.loads(l) for l in f if l.strip()]
        return pd.DataFrame(records)
    if ext == ".json":
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, list):
            return pd.DataFrame(raw)
        for v in raw.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return pd.DataFrame(v)
    if ext == ".csv":
        return pd.read_csv(path, encoding="utf-8")
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if ext == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"지원하지 않는 형식: {ext}")


def _load_report(path: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    with open(path, encoding="utf-8") as f:
        report = json.load(f)

    processed   = pd.DataFrame(report.get("preprocessed_data", []))
    changelog   = pd.DataFrame(report.get("changelog", []))
    meta        = {
        "dq_score":      report.get("scores", {}).get("weighted_final"),
        "grade":         report.get("grade") or report.get("metadata", {}).get("grade"),
        "pipeline_id":   report.get("metadata", {}).get("pipeline_id"),
        "total_records": report.get("metadata", {}).get("total_records"),
        "elapsed_sec":   report.get("elapsed_sec"),
        "violations":    report.get("rule_violations", []),
    }
    return processed, changelog, meta


def _nan_to_none(df: pd.DataFrame) -> pd.DataFrame:
    return df.where(pd.notnull(df), other=None)


# ── 지표 계산 ────────────────────────────────────────────────────────────────
def _null_comparison(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    """필드별 NULL 비율 Before / After 비교."""
    rows = []
    for col in before.columns:
        if col not in after.columns:
            continue
        b_null = before[col].isna().sum()
        a_null = after[col].isna().sum() if col in after.columns else None
        n      = len(before)
        b_pct  = round(b_null / n * 100, 1)
        a_pct  = round(a_null / n * 100, 1) if a_null is not None else None
        rows.append({
            "필드":          col,
            "before_null":   b_null,
            "after_null":    a_null,
            "before_null%":  b_pct,
            "after_null%":   a_pct,
            "null_감소":     b_null - (a_null or 0),
            "개선여부":      "✓" if (a_null is not None and a_null < b_null) else
                            ("→" if a_null == b_null else "↑"),
        })
    return pd.DataFrame(rows).sort_values("null_감소", ascending=False)


def _stats_comparison(before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
    """수치 필드 통계 Before / After 비교 (평균·표준편차·최솟값·최댓값)."""
    rows = []
    for col in before.select_dtypes(include="number").columns:
        if col not in after.columns:
            continue
        b = before[col].dropna()
        a = after[col].dropna()
        if b.empty:
            continue
        rows.append({
            "필드":        col,
            "before_mean": round(float(b.mean()), 2),
            "after_mean":  round(float(a.mean()), 2) if not a.empty else None,
            "before_std":  round(float(b.std()), 2),
            "after_std":   round(float(a.std()), 2) if not a.empty else None,
            "before_min":  float(b.min()),
            "after_min":   float(a.min()) if not a.empty else None,
            "before_max":  float(b.max()),
            "after_max":   float(a.max()) if not a.empty else None,
            "이상치제거":  int(len(b) - len(a)) if len(b) != len(a) else 0,
        })
    return pd.DataFrame(rows)


def _changelog_summary(cl: pd.DataFrame) -> pd.DataFrame:
    """액션 유형별 변경 분포."""
    if cl.empty:
        return pd.DataFrame()
    grp = (
        cl[cl["action"] != "keep"]
        .groupby(["action", "field"])
        .size()
        .reset_index(name="건수")
        .sort_values("건수", ascending=False)
    )
    return grp


def _field_error_rate(before: pd.DataFrame, cl: pd.DataFrame) -> pd.DataFrame:
    """필드별 오류 비율 (변경된 건수 / 전체 레코드)."""
    if cl.empty:
        return pd.DataFrame()
    n = len(before)
    grp = (
        cl[cl["action"] != "keep"]
        .groupby("field")
        .size()
        .reset_index(name="변경건수")
    )
    grp["오류율(%)"] = (grp["변경건수"] / n * 100).round(1)
    grp["정상율(%)"] = (100 - grp["오류율(%)"]).round(1)
    return grp.sort_values("오류율(%)", ascending=False)


def _stage_contribution(cl: pd.DataFrame) -> pd.DataFrame:
    """Stage 2A(결정론적) vs 2B(Claude) 기여도."""
    if cl.empty or "stage" not in cl.columns:
        return pd.DataFrame()
    grp = (
        cl[cl["action"] != "keep"]
        .groupby("stage")
        .size()
        .reset_index(name="처리건수")
    )
    total = grp["처리건수"].sum()
    grp["기여율(%)"] = (grp["처리건수"] / total * 100).round(1)
    grp["stage"] = grp["stage"].map({"2a": "2A-결정론적", "2b": "2B-Claude"})
    return grp


def _completeness_score(df: pd.DataFrame) -> float:
    """데이터 완전성 점수 (전체 셀 중 비NULL 비율)."""
    total = df.size
    filled = df.notna().sum().sum()
    return round(filled / total * 100, 2) if total else 0.0


def _roi_estimate(
    n_records: int,
    elapsed_sec: float | None,
    changelog_count: int,
    hourly_rate: int,
) -> dict:
    """시간·비용 기반 ROI 추정."""
    # 수동 검토 시간 추정 (기본: 100건당 120분)
    manual_min  = (n_records / 100) * _MANUAL_MINUTES_PER_100
    manual_cost = manual_min / 60 * hourly_rate

    # Agent 처리 시간
    agent_min   = round((elapsed_sec or 0) / 60, 2)

    # Claude Pro 구독 일할 비용 (월 22달러 ≒ 30,000원 / 30일 / 평균 10회/일)
    claude_daily_cost = 30_000 / 30
    agent_cost        = round(claude_daily_cost / 10, 0)

    time_saved  = round(manual_min - agent_min, 1)
    cost_saved  = round(manual_cost - agent_cost, 0)
    roi_pct     = round((cost_saved / agent_cost * 100) if agent_cost else 0, 1)

    return {
        "레코드수":        n_records,
        "수동_예상시간(분)": manual_min,
        "Agent_처리시간(분)": agent_min,
        "절감_시간(분)":   time_saved,
        "수동_추정비용(원)": int(manual_cost),
        "Agent_비용(원)":  int(agent_cost),
        "절감_비용(원)":   int(cost_saved),
        "ROI(%)":         roi_pct,
        "자동처리_건수":   changelog_count,
        "처리_속도배율":   round(manual_min / agent_min, 1) if agent_min else "∞",
    }


# ── 출력 ─────────────────────────────────────────────────────────────────────
def _sep(title: str = ""):
    w = 70
    if title:
        pad = (w - len(title) - 2) // 2
        print("─" * pad + f" {title} " + "─" * (w - pad - len(title) - 2))
    else:
        print("─" * w)


def _print_df(df: pd.DataFrame, title: str):
    _sep(title)
    if df.empty:
        print("  (데이터 없음)")
    else:
        print(df.to_string(index=False))
    print()


def _print_dict(d: dict, title: str):
    _sep(title)
    for k, v in d.items():
        print(f"  {k:<22} : {v:>15}")
    print()


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="pandas 기반 Before/After ROI 비교",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("original", help="원본 파일 (JSON/JSONL/CSV/Parquet/XLSX)")
    ap.add_argument("report",   help="파이프라인 보고서 (report/*.json)")
    ap.add_argument(
        "--hourly-rate", type=int, default=_DEFAULT_HOURLY_RATE, metavar="N",
        help=f"수동 검토자 시간당 인건비 원 (기본: {_DEFAULT_HOURLY_RATE:,})"
    )
    ap.add_argument(
        "--export", metavar="FILE",
        help="결과를 Excel 파일로 내보내기 (예: roi_result.xlsx)"
    )
    ap.add_argument(
        "--save-report", metavar="DIR", default=None,
        help="결과 텍스트를 지정 디렉터리에 저장 (예: report/)"
    )
    args = ap.parse_args()

    _file_handle = None
    _out_path    = None
    if args.save_report:
        os.makedirs(args.save_report, exist_ok=True)
        stem      = os.path.splitext(os.path.basename(args.report))[0]
        _out_path = os.path.join(args.save_report, f"{stem}_dq_cost.txt")
        _file_handle = open(_out_path, "w", encoding="utf-8")
        sys.stdout = _Tee(sys.__stdout__, _file_handle)

    print()
    print("=" * 70)
    print("  DQ Agent ROI 분석 — pandas Before / After 비교")
    print("=" * 70)
    print(f"  원본   : {args.original}")
    print(f"  보고서 : {args.report}")
    print(f"  인건비 : {args.hourly_rate:,}원/시간")
    print()

    # 데이터 로드
    df_before            = _load_original(args.original)
    df_after, cl, meta   = _load_report(args.report)

    n = len(df_before)

    # ── 1. 완전성 점수 ─────────────────────────────────────────────────────
    comp_before = _completeness_score(df_before)
    comp_after  = _completeness_score(df_after)

    _sep("데이터 완전성 (Completeness)")
    print(f"  Before  : {comp_before:>6.2f}%")
    print(f"  After   : {comp_after:>6.2f}%")
    delta = round(comp_after - comp_before, 2)
    sign  = "+" if delta >= 0 else ""
    print(f"  개선폭  : {sign}{delta}%p")
    if meta.get("dq_score"):
        print(f"  DQ 점수 : {meta['dq_score']}/100  [{meta.get('grade','?')}등급]")
    print()

    # ── 2. NULL 비율 비교 ─────────────────────────────────────────────────
    null_df = _null_comparison(df_before, df_after)
    _print_df(null_df[null_df["null_감소"] != 0], "필드별 NULL 변화")

    # ── 3. 수치 통계 비교 ────────────────────────────────────────────────
    stats_df = _stats_comparison(df_before, df_after)
    if not stats_df.empty:
        _print_df(stats_df, "수치 필드 통계 변화 (mean / std / min / max)")

    # ── 4. 필드별 오류율 ─────────────────────────────────────────────────
    err_df = _field_error_rate(df_before, cl)
    _print_df(err_df, "필드별 오류율 (변경 건수 / 전체 레코드)")

    # ── 5. 액션 유형 분포 ────────────────────────────────────────────────
    cl_sum = _changelog_summary(cl)
    _print_df(cl_sum, "액션 유형별 변경 분포 (normalize / fill / flag)")

    # ── 6. Stage 기여도 ──────────────────────────────────────────────────
    stage_df = _stage_contribution(cl)
    _print_df(stage_df, "Stage 2A(결정론적) vs 2B(Claude) 기여도")

    # ── 7. ROI 추정 ───────────────────────────────────────────────────────
    cl_count = len(cl[cl["action"] != "keep"]) if not cl.empty else 0
    roi      = _roi_estimate(n, meta.get("elapsed_sec"), cl_count, args.hourly_rate)
    _print_dict(roi, "ROI 추정 (수동 검토 대비)")

    # ── 8. 규칙 위반 요약 ────────────────────────────────────────────────
    if meta.get("violations"):
        viol_df = pd.DataFrame(meta["violations"])[["field", "rule", "severity", "count", "detail"]]
        _print_df(viol_df, "Stage 1 탐지 위반 목록")

    # ── Excel 내보내기 ────────────────────────────────────────────────────
    if args.export:
        summary = pd.DataFrame([{
            "측정일시":        datetime.now().strftime("%Y-%m-%d %H:%M"),
            "원본파일":        args.original,
            "레코드수":        n,
            "완전성_before(%)": comp_before,
            "완전성_after(%)":  comp_after,
            "완전성_개선폭":    delta,
            "DQ점수":          meta.get("dq_score"),
            "등급":            meta.get("grade"),
            **roi,
        }])
        with pd.ExcelWriter(args.export, engine="openpyxl") as writer:
            summary.to_excel(writer,   sheet_name="ROI요약",      index=False)
            null_df.to_excel(writer,   sheet_name="NULL비율비교",  index=False)
            if not stats_df.empty:
                stats_df.to_excel(writer, sheet_name="통계비교",  index=False)
            if not err_df.empty:
                err_df.to_excel(writer, sheet_name="필드오류율",  index=False)
            if not cl_sum.empty:
                cl_sum.to_excel(writer, sheet_name="액션분포",    index=False)
            if not cl.empty:
                cl.to_excel(writer,     sheet_name="전체Changelog", index=False)
        print(f"  Excel 저장 완료: {args.export}")

    print("=" * 70)
    print()

    if _file_handle:
        sys.stdout = sys.__stdout__
        _file_handle.close()
        print(f"  결과 저장: {_out_path}")


if __name__ == "__main__":
    main()
