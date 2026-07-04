#!/usr/bin/env python3
"""
bench-result 회차 시각화 — summary.json을 읽어 PNG 차트 생성

차트 규칙 (dataviz 스킬 검증 팔레트 준수):
  - metrics.png:  구성별 F1/Precision/Recall 그룹 막대 (범주 3계열, 고정 색 순서)
  - cost_latency.png: USD·지연 각각 별도 축의 나란한 막대 (이중축 금지 → 소형 다중)
  - 직접 값 라벨 병기 (aqua/yellow 계열의 대비 완화 규칙), 격자·축은 배경으로

Usage:
  python tools/plot_bench.py bench-result/001_2026-07-05/
  (run_experiments.py가 회차 기록 시 자동 호출)
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# dataviz 검증 팔레트 (light mode) — 순서 고정, 순환 금지
_C_BLUE, _C_AQUA, _C_YELLOW = "#2a78d6", "#1baf7a", "#eda100"
_INK, _MUTED = "#1a1a1a", "#767676"


def _style_ax(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#d0d0d0")
    ax.tick_params(colors=_MUTED, labelsize=8)
    ax.yaxis.grid(True, color="#e8e8e8", linewidth=0.6, zorder=0)
    ax.set_axisbelow(True)


def _bar_labels(ax, bars, fmt="{:.3f}"):
    for b in bars:
        h = b.get_height()
        if h is None:
            continue
        ax.annotate(fmt.format(h), (b.get_x() + b.get_width() / 2, h),
                    textcoords="offset points", xytext=(0, 2),
                    ha="center", fontsize=7, color=_INK)


def _short_label(run: dict) -> str:
    # run_id 대신 config(+seed/rep)로 축 라벨 축약
    seed = run.get("run_id", "").split("-s")[-1] if "-s" in run.get("run_id", "") else ""
    return f"{run['config']}" + (f"\ns{seed}" if seed else "")


def plot_round(round_dir: str) -> list:
    with open(os.path.join(round_dir, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    runs = [r for r in summary["runs"] if r.get("status") == "ok"]
    if not runs:
        return []

    labels  = [_short_label(r) for r in runs]
    x       = range(len(runs))
    created = []

    # ── metrics.png: F1/P/R 그룹 막대 ─────────────────────────────
    if any(r.get("f1") is not None for r in runs):
        fig, ax = plt.subplots(figsize=(max(5, 1.6 * len(runs)), 3.2), dpi=150)
        w = 0.26
        series = [
            ("F1",        [r.get("f1") or 0 for r in runs],        _C_BLUE),
            ("Precision", [r.get("precision") or 0 for r in runs], _C_AQUA),
            ("Recall",    [r.get("recall") or 0 for r in runs],    _C_YELLOW),
        ]
        for k, (name, vals, color) in enumerate(series):
            bars = ax.bar([i + (k - 1) * w for i in x], vals, width=w * 0.92,
                          color=color, label=name, zorder=3)
            _bar_labels(ax, bars)
        _style_ax(ax)
        ax.set_xticks(list(x), labels)
        ax.set_ylim(0, min(1.0, max(v for _, vals, _ in series for v in vals) * 1.3 + 0.05))
        ax.set_title(f"Round {summary['round']:03d} — Detection metrics by config "
                     f"({summary['date']})", fontsize=9, color=_INK, loc="left")
        ax.legend(frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(1.0, 1.0))
        fig.tight_layout()
        p = os.path.join(round_dir, "metrics.png")
        fig.savefig(p, bbox_inches="tight")
        plt.close(fig)
        created.append(p)

    # ── cost_latency.png: 소형 다중 (이중축 금지) ─────────────────
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(max(6, 2.4 * len(runs)), 2.8), dpi=150)
    bars = ax1.bar(x, [r.get("usd") or 0 for r in runs], width=0.5, color=_C_BLUE, zorder=3)
    _bar_labels(ax1, bars, fmt="{:.3f}")
    ax1.set_title("Cost (USD, list-price equivalent)", fontsize=9, color=_INK, loc="left")
    ax1.set_xticks(list(x), labels)

    bars = ax2.bar(x, [r.get("latency_s") or 0 for r in runs], width=0.5, color=_C_BLUE, zorder=3)
    _bar_labels(ax2, bars, fmt="{:.0f}")
    ax2.set_title("Latency (s)", fontsize=9, color=_INK, loc="left")
    ax2.set_xticks(list(x), labels)

    for ax in (ax1, ax2):
        _style_ax(ax)
    fig.tight_layout()
    p = os.path.join(round_dir, "cost_latency.png")
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    created.append(p)

    return created


def main():
    if len(sys.argv) != 2:
        print("Usage: python tools/plot_bench.py <bench-result/round_dir>")
        sys.exit(1)
    created = plot_round(sys.argv[1])
    for p in created:
        print(f"[plot_bench] 생성: {p}")


if __name__ == "__main__":
    main()
