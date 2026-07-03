"""
Before/After 비교 표 + 시간 비교 표 출력
run_compare.sh 에서 호출됩니다.

Usage:
  python tools/compare_table.py <원본파일> <보고서파일> \
      --agent-sec <float> --pandas-sec <float>
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class _Tee:
    """stdout을 터미널과 파일에 동시에 출력. 파일에는 ANSI 코드를 제거."""
    def __init__(self, term, file_):
        self._term = term
        self._file = file_
    def write(self, data):
        self._term.write(data)
        self._file.write(re.sub(r"\033\[[0-9;]*m", "", data))
    def flush(self):
        self._term.flush()
        self._file.flush()
    def isatty(self):
        return self._term.isatty()

import pandas as pd
from tabulate import tabulate

# ── ANSI ─────────────────────────────────────────────────────────────────────
BOLD  = "\033[1m"
CYAN  = "\033[96m"
GREEN = "\033[92m"
YELLOW= "\033[93m"
RED   = "\033[91m"
DIM   = "\033[2m"
RESET = "\033[0m"

IS_TTY = sys.stdout.isatty()

def c(text, code):
    return f"{code}{text}{RESET}" if IS_TTY else text

def sep(title="", width=80):
    if title:
        pad = (width - len(title) - 2) // 2
        print(c("─" * pad + f" {title} " + "─" * (width - pad - len(title) - 2), CYAN))
    else:
        print(c("─" * width, DIM))


# ── 로딩 ─────────────────────────────────────────────────────────────────────
def load_original(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".jsonl":
        with open(path, encoding="utf-8") as f:
            return pd.DataFrame([json.loads(l) for l in f if l.strip()])
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return pd.DataFrame(raw)
    for v in raw.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return pd.DataFrame(v)
    return pd.DataFrame()


def load_report(path):
    with open(path, encoding="utf-8") as f:
        r = json.load(f)
    processed = pd.DataFrame(r.get("preprocessed_data", []))
    changelog = pd.DataFrame(r.get("changelog", []))
    meta = {
        "total":      r.get("metadata", {}).get("total_records", 0),
        "dq_score":   r.get("scores", {}).get("weighted_final"),
        "grade":      r.get("grade"),
        "violations": r.get("rule_violations", []),
        "cl_count":   r.get("stage2_changelog_count", 0),
    }
    return processed, changelog, meta


def fix_nan(val):
    if isinstance(val, float) and math.isnan(val):
        return None
    return val


# ── Before/After 비교 표 ──────────────────────────────────────────────────────
def print_before_after(df_before, df_after, changelog, max_rows=40):
    sep("Before / After 변경 내역")

    if changelog.empty:
        print("  (changelog 없음 — 보고서를 재생성하세요)\n")
        return

    cl = changelog[changelog["action"] != "keep"].copy()
    if cl.empty:
        print("  (변경 없음)\n")
        return

    rows = []
    for _, entry in cl.iterrows():
        idx    = entry.get("record_index")
        field  = entry.get("field", "")
        action = entry.get("action", "")
        orig   = entry.get("original")
        new    = entry.get("new_value")
        reason = str(entry.get("reason", ""))[:45]
        stage  = entry.get("stage", "")

        # Before: 원본 파일 값 (있으면 우선)
        if idx is not None and idx < len(df_before) and field in df_before.columns:
            before_val = fix_nan(df_before.iloc[int(idx)][field])
        else:
            before_val = fix_nan(orig)

        after_val = None if (new is None or (isinstance(new, float) and math.isnan(new))) else new

        # 액션 색상
        if IS_TTY:
            action_str = {
                "normalize": c("normalize", CYAN),
                "fill":      c("fill",      GREEN),
                "flag":      c("flag",      YELLOW),
            }.get(action, action)
        else:
            action_str = action

        rows.append({
            "#":      idx,
            "필드":   field,
            "Before": str(before_val)[:28] if before_val is not None else c("(null)", DIM),
            "After":  str(after_val)[:28]  if after_val  is not None else c("null",   RED),
            "Action": action_str,
            "Stage":  stage,
            "이유":   reason,
        })

    # 최대 행 제한
    total = len(rows)
    shown = rows[:max_rows]

    print(tabulate(shown, headers="keys", tablefmt="simple", numalign="left"))
    if total > max_rows:
        print(c(f"\n  ... {total - max_rows}건 추가 생략 (총 {total}건)", DIM))

    # 액션 요약
    print()
    summary = cl.groupby("action").size().reset_index(name="건수")
    print(c("  [ 액션 요약 ]", BOLD))
    for _, row in summary.iterrows():
        bar = "█" * int(row["건수"])
        print(f"    {row['action']:<10} {row['건수']:>3}건  {c(bar, CYAN)}")
    print()


# ── Stage별 규칙 위반 표 ───────────────────────────────────────────────────
def print_violations(violations):
    sep("Stage 1 탐지 위반")
    if not violations:
        print("  (위반 없음)\n")
        return
    rows = []
    for v in violations:
        sev = v.get("severity", "")
        sev_str = {
            "critical": c("critical", RED),
            "warning":  c("warning",  YELLOW),
            "info":     c("info",     CYAN),
        }.get(sev, sev) if IS_TTY else sev
        rows.append({
            "필드":     v.get("field"),
            "규칙":     v.get("rule"),
            "severity": sev_str,
            "건수":     v.get("count"),
            "상세":     str(v.get("detail", ""))[:48],
        })
    print(tabulate(rows, headers="keys", tablefmt="simple"))
    print()


# ── 시간 비교 표 ────────────────────────────────────────────────────────────
def print_time_comparison(agent_sec, pandas_sec, meta, cl_count):
    sep("실행 시간 비교")

    agent_min  = agent_sec  / 60
    pandas_min = pandas_sec / 60
    total_min  = (agent_sec + pandas_sec) / 60

    rows = [
        ["DQ Agent (전체)",          f"{agent_sec:.1f}초",  f"{agent_min:.2f}분",
         f"{meta.get('total', 0)}건 처리  /  DQ {meta.get('dq_score','?')}/100  {meta.get('grade','?')}등급"],
        ["  └ Stage 1 (DuckDB 규칙)", "~1초 미만",           "-",
         f"위반 {len(meta.get('violations', []))}건 탐지"],
        ["  └ Stage 2A (결정론적)",   "~0.1초 미만",         "-",
         f"변경 {cl_count}건 (LLM 0회)"],
        ["  └ Stage 2B (Claude CLI)", "대부분의 시간",        "-",
         "이상치 레코드만 선택 호출"],
        ["  └ Stage 3B (수치검증)",   "~수초",               "-",
         "환각 탐지 + 드리프트"],
        ["pandas ROI 분석",           f"{pandas_sec:.1f}초", f"{pandas_min:.2f}분",
         "before/after 통계 + Excel 저장"],
        [c("합계", BOLD) if IS_TTY else "합계",
         c(f"{agent_sec + pandas_sec:.1f}초", BOLD) if IS_TTY else f"{agent_sec + pandas_sec:.1f}초",
         c(f"{total_min:.2f}분", BOLD) if IS_TTY else f"{total_min:.2f}분",
         ""],
    ]

    print(tabulate(
        rows,
        headers=["항목", "소요시간", "(분)", "비고"],
        tablefmt="simple",
        colalign=("left", "right", "right", "left"),
    ))
    print()

    # 속도 배율
    manual_min = (meta.get("total", 50) / 100) * 120
    ratio      = manual_min / (agent_min + pandas_min) if (agent_min + pandas_min) > 0 else 0

    sep("수동 검토 대비 속도")
    stats = [
        ["수동 검토 예상 시간",   f"{manual_min:.0f}분",   f"{meta.get('total',0)}건 × 1.2분/건"],
        ["Agent + 분석 합계",     f"{total_min:.2f}분",    ""],
        [c("속도 배율", BOLD) if IS_TTY else "속도 배율",
         c(f"{ratio:.0f}x",   BOLD) if IS_TTY else f"{ratio:.0f}x",
         c(f"수동 대비 {ratio:.0f}배 빠름", GREEN) if IS_TTY else f"수동 대비 {ratio:.0f}배 빠름"],
    ]
    print(tabulate(stats, headers=["항목", "시간", "비고"], tablefmt="simple"))
    print()


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("original")
    ap.add_argument("report")
    ap.add_argument("--agent-sec",   type=float, default=0)
    ap.add_argument("--pandas-sec",  type=float, default=0)
    ap.add_argument("--max-rows",    type=int,   default=40)
    ap.add_argument("--save-report", metavar="DIR", default=None,
                    help="결과 텍스트를 지정 디렉터리에 저장 (예: report/)")
    args = ap.parse_args()

    _file_handle = None
    if args.save_report:
        os.makedirs(args.save_report, exist_ok=True)
        stem     = os.path.splitext(os.path.basename(args.report))[0]
        out_path = os.path.join(args.save_report, f"{stem}_dq_result.txt")
        _file_handle = open(out_path, "w", encoding="utf-8")
        sys.stdout = _Tee(sys.__stdout__, _file_handle)

    df_before             = load_original(args.original)
    df_after, changelog, meta = load_report(args.report)

    cl_count = len(changelog[changelog["action"] != "keep"]) if not changelog.empty else 0

    print()
    print_violations(meta["violations"])
    print_before_after(df_before, df_after, changelog, args.max_rows)
    print_time_comparison(args.agent_sec, args.pandas_sec, meta, cl_count)

    if _file_handle:
        sys.stdout = sys.__stdout__
        _file_handle.close()
        print(f"  결과 저장: {out_path}")


if __name__ == "__main__":
    main()
