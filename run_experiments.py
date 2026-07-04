#!/usr/bin/env python3
"""
ExperimentRunner — 실험 매트릭스 실행 + 04 문서 §6 스키마 로그 저장

각 실행마다 runs/{run_id}.json 로그를 남긴다 (1실행 1파일).
ground truth가 있으면 셀 단위 P/R/F1을 산출하고, 없으면(E0) null로 기록한다.

Usage:
  # E0 파일럿: 구성별 반복 실행
  python run_experiments.py --experiment E0 --dataset data/customer_data_50.json \
      --configs A1,A3,A5 --reps 3

  # 단일 실행 (E1, ground truth 지정)
  python run_experiments.py --experiment E1 --dataset runs/injected/S1_r10_s1.json \
      --configs A3 --reps 1 --error-rate 0.10 --seed 1 \
      --ground-truth runs/injected/S1_r10_s1_ground_truth.json

중단·예외 규칙 (04 §8): 실행 실패 시 동일 조건 1회 재시도, 재실패 시
결측(failed)으로 기록하고 다음 실행으로 진행 (silent retry 금지 — 로그에 남김).
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

RUNS_DIR     = "runs"
BENCH_DIR    = "bench-result"
PRICING_PATH = os.path.join("config", "pricing.json")


def _next_round() -> int:
    """bench-result/ 폴더를 스캔해 다음 실험회차 번호 결정 (러너 1회 실행 = 1회차)"""
    if not os.path.isdir(BENCH_DIR):
        return 1
    rounds = []
    for name in os.listdir(BENCH_DIR):
        m = __import__("re").match(r"^(\d+)_", name)
        if m:
            rounds.append(int(m.group(1)))
    return max(rounds, default=0) + 1


def _record_bench_result(args, logs: list) -> str:
    """실험회차·날짜 폴더에 실행 요약(summary.md/json) + 개별 로그 사본 저장"""
    import shutil

    round_no = _next_round()
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir  = os.path.join(BENCH_DIR, f"{round_no:03d}_{date_str}")
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    for log in logs:
        m = log.get("metrics", {})
        usd = (log.get("usd_cost") or {}).get("total")
        rows.append({
            "run_id": log["run_id"], "config": log["config"], "status": log["status"],
            "f1": m.get("f1"), "precision": m.get("precision"), "recall": m.get("recall"),
            "latency_s": m.get("latency_s"), "usd": usd,
        })
        src = os.path.join(RUNS_DIR, f"{log['run_id']}.json")
        if os.path.exists(src):
            shutil.copy2(src, out_dir)

    summary = {
        "round":      round_no,
        "date":       date_str,
        "recorded_at": datetime.now().isoformat(),
        "experiment": args.experiment,
        "dataset":    args.dataset,
        "configs":    args.configs,
        "reps":       args.reps,
        "error_rate": args.error_rate,
        "seed":       args.seed,
        "runs":       rows,
    }
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    md = [
        f"# 실험 {round_no:03d}회차 — {date_str}",
        "",
        f"- 실험: {args.experiment} / 데이터: `{args.dataset}` / 구성: {args.configs} / 반복: {args.reps}",
        f"- 오류율: {args.error_rate} / 시드: {args.seed}",
        "",
        "| run_id | config | status | F1 | P | R | 지연(s) | USD |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append(f"| {r['run_id']} | {r['config']} | {r['status']} | {r['f1']} | "
                  f"{r['precision']} | {r['recall']} | {r['latency_s']} | {r['usd']} |")
    # 시각화 — 회차 폴더에 PNG 생성 (실패해도 실험 기록 자체는 유효)
    charts = []
    try:
        from tools.plot_bench import plot_round
        charts = plot_round(out_dir)
    except Exception as e:
        print(f"[Runner] 시각화 생략 (오류): {e}")

    if charts:
        md.append("")
        md.append("## 시각화")
        md.append("")
        for p in charts:
            name = os.path.basename(p)
            md.append(f"![{name}]({name})")
    md.append("")
    md.append("원본 로그: `runs/` (정본), 이 폴더의 JSON은 사본")
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    return out_dir


def _auto_commit(round_dir: str, summary_line: str, push: bool = True) -> None:
    """실험 기록 자동 커밋(+push). 실패해도 실험 자체는 유효 — 경고만 남김."""
    import subprocess

    def git(*a):
        return subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8")

    try:
        git("add", round_dir, RUNS_DIR)
        staged = git("diff", "--cached", "--quiet")
        if staged.returncode == 0:
            print("[Runner] 자동 커밋 생략 — 변경 없음")
            return
        msg = (f"exp: {summary_line}\n\n"
               f"자동 커밋 (실험 기록 규칙)\n\n"
               f"Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>")
        r = git("commit", "-m", msg)
        if r.returncode != 0:
            print(f"[Runner] 자동 커밋 실패: {r.stderr.strip()[:200]}")
            return
        print(f"[Runner] 자동 커밋 완료: {round_dir}")
        if push:
            p = git("push", "paper", "main:main")
            if p.returncode != 0:
                print(f"[Runner] push 실패 (커밋은 로컬 보존): {p.stderr.strip()[:200]}")
            else:
                print("[Runner] push 완료 → paper/main")
    except Exception as e:
        print(f"[Runner] 자동 커밋 오류 (무시하고 계속): {e}")


def _compute_usd(token_usage: dict) -> dict:
    """스테이지별 토큰 × config/pricing.json 단가 → USD (04 §5 Cost 보조 지표)"""
    with open(PRICING_PATH, encoding="utf-8") as f:
        pricing = json.load(f)

    by_stage, total = {}, 0.0
    for stage, u in (token_usage or {}).items():
        model = u.get("model") or pricing["stage_default_model"].get(stage)
        rates = pricing["models"].get(model)
        if not rates:
            by_stage[stage] = None      # 단가 미등록 — 결측으로 명시
            continue
        in_rate  = rates["input_per_mtok"] / 1e6
        out_rate = rates["output_per_mtok"] / 1e6
        cost = (
            u.get("input", 0) * in_rate
            + u.get("output", 0) * out_rate
            + u.get("cache_creation", 0) * in_rate * rates["cache_write_multiplier"]
            + u.get("cache_read", 0) * in_rate * rates["cache_read_multiplier"]
        )
        by_stage[stage] = round(cost, 6)
        total += cost

    return {"rate_date": pricing["rate_date"], "total": round(total, 6), "by_stage": by_stage}


def _dataset_tag(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return base.replace("customer_data_50", "cust50")


def _evaluate(report_path: str, ground_truth_path: str) -> dict:
    """셀 단위 P/R/F1 — TP = 주입 오류 셀을 파이프라인이 플래그 (04 §5)

    예측 플래그 = changelog(2A/2B 변경·플래그) + rule_violations 필드의 셀.
    ground truth와 (row, col) 단위로 대조한다.
    """
    with open(ground_truth_path, encoding="utf-8") as f:
        gt = json.load(f)
    gt_cells = {(g["row"], g["col"]) for g in gt["ground_truth"]}

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    pred_cells = set()
    for entry in report.get("changelog", []):
        if entry.get("record_index") is not None and entry.get("field"):
            pred_cells.add((entry["record_index"], entry["field"]))

    tp = len(gt_cells & pred_cells)
    fp = len(pred_cells - gt_cells)
    fn = len(gt_cells - pred_cells)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 4),
        "recall":    round(recall, 4),
        "f1":        round(f1, 4),
        "tp": tp, "fp": fp, "fn": fn,
        "gt_cells": len(gt_cells), "pred_cells": len(pred_cells),
    }


def run_once(
    experiment: str,
    dataset: str,
    config: str,
    rep: int,
    error_rate=None,
    seed=None,
    ground_truth=None,
    batch_size: int = 500,
) -> dict:
    import orchestrator

    tag    = _dataset_tag(dataset)
    rate_s = f"-r{int(error_rate * 100)}" if error_rate else ""
    # 시드가 있어도 rep을 병기 — 동일 시드 반복(Consistency 측정)의 로그 덮어쓰기 방지
    seed_s = f"-s{seed}-rep{rep}" if seed is not None else f"-rep{rep}"
    run_id = f"{experiment}-{tag}{rate_s}-{config}{seed_s}"

    run_meta = {
        "run_id": run_id, "experiment": experiment, "dataset": tag,
        "error_rate": error_rate, "seed": seed if seed is not None else rep,
    }

    log = {
        "run_id":      run_id,
        "experiment":  experiment,
        "dataset":     tag,
        "dataset_path": dataset,
        "error_rate":  error_rate,
        "config":      config,
        "seed":        seed if seed is not None else rep,
        "rep":         rep,
        "models":      {"detector": None, "validator": None},
        "temperature": 0,
        "started_at":  datetime.now().isoformat(),
        "ended_at":    None,
        "token_usage": {},
        "usd_cost":    {"rate_date": None, "total": None},  # 후처리 (pricing.json 예정)
        "predictions": None,
        "metrics":     {"precision": None, "recall": None, "f1": None, "latency_s": None},
        "stage_errors": [],
        "status":      "running",
    }

    t0 = time.time()
    result, attempt_errors = None, []
    for attempt in range(2):                     # 04 §8: 실패 시 동일 조건 1회 재시도
        try:
            result = orchestrator.run(
                file_path=dataset, batch_size=batch_size,
                config=config, run_meta=run_meta,
            )
            break
        except Exception as e:
            attempt_errors.append(f"attempt{attempt + 1}: {e}")
            print(f"[Runner] {run_id} 실행 실패 (시도 {attempt + 1}/2): {e}")

    latency = round(time.time() - t0, 1)
    log["ended_at"] = datetime.now().isoformat()
    log["metrics"]["latency_s"] = latency
    log["retry_log"] = attempt_errors            # silent retry 금지 — 실패 이력 기록

    if result is None:
        log["status"] = "failed"
    else:
        log["status"]       = "ok"
        log["token_usage"]  = result.get("token_usage", {})
        log["stage_errors"] = result.get("stage_errors", [])
        log["predictions"]  = result.get("output_path")
        log["scores"]       = result.get("scores")
        log["grade"]        = result.get("grade")
        log["usd_cost"]     = _compute_usd(result.get("token_usage", {}))
        tu = result.get("token_usage", {})
        log["models"]["detector"]  = (tu.get("stage2b") or {}).get("model")
        log["models"]["validator"] = (tu.get("stage3a") or {}).get("model")

        if ground_truth and result.get("output_path"):
            try:
                log["metrics"].update(_evaluate(result["output_path"], ground_truth))
            except Exception as e:
                log["eval_error"] = str(e)

    os.makedirs(RUNS_DIR, exist_ok=True)
    log_path = os.path.join(RUNS_DIR, f"{run_id}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2, default=str)

    print(f"[Runner] {run_id}: {log['status']} ({latency}s) -> {log_path}")
    return log


def main():
    parser = argparse.ArgumentParser(description="실험 매트릭스 실행 (04 §1/§6)")
    parser.add_argument("--experiment", required=True, help="E0 | E1 | E2")
    parser.add_argument("--dataset",    required=True)
    parser.add_argument("--configs",    required=True, help="쉼표 구분: A1,A3,A5")
    parser.add_argument("--reps",       type=int, default=1)
    parser.add_argument("--rep-start",  type=int, default=1, help="반복 시작 번호 (이어서 실행용)")
    parser.add_argument("--error-rate", type=float, default=None)
    parser.add_argument("--seed",       type=int, default=None)
    parser.add_argument("--ground-truth", default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--no-commit", action="store_true",
                        help="실험 기록 자동 커밋/푸시 생략")
    args = parser.parse_args()

    configs = [c.strip() for c in args.configs.split(",")]
    logs = []
    for config in configs:
        for rep in range(args.rep_start, args.rep_start + args.reps):
            log = run_once(
                experiment=args.experiment, dataset=args.dataset,
                config=config, rep=rep,
                error_rate=args.error_rate, seed=args.seed,
                ground_truth=args.ground_truth, batch_size=args.batch_size,
            )
            logs.append(log)

    bench_dir = _record_bench_result(args, logs)

    if not args.no_commit:
        n_ok = sum(1 for l in logs if l["status"] == "ok")
        _auto_commit(
            bench_dir,
            f"{os.path.basename(bench_dir)} — {args.experiment} {args.configs} "
            f"({n_ok}/{len(logs)} ok)",
        )

    print("\n=== 실행 요약 ===")
    for log in logs:
        print(f"  {log['run_id']}: {log['status']} ({log['metrics']['latency_s']}s)")
    print(f"  회차 기록: {bench_dir}/summary.md")


if __name__ == "__main__":
    main()
