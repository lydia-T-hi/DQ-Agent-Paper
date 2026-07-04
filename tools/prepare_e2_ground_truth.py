#!/usr/bin/env python3
"""
E2 벤치마크(Hospital, Flights) ground truth 생성
04_experiment-plan_v1_1.md §2.3 — Raha 표준 벤치마크(clean.csv vs dirty.csv)에서
셀 단위 오류 위치를 diff하여 ground truth JSON을 만든다.

출처: BigDaMa/raha (Apache-2.0) datasets/{hospital,flights}
  https://github.com/BigDaMa/raha/tree/master/datasets
주의: 실제 오류(합성 아님) — 유형(T1~T5) 라벨 없음, F1은 "상한 추정치"로만 사용 (§2.3, §5 참고)

Usage:
  python tools/prepare_e2_ground_truth.py data/E2_hospital
  python tools/prepare_e2_ground_truth.py data/E2_flights
"""
import argparse
import csv
import json
import os


def load_csv(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return list(csv.reader(f))


def build_ground_truth(clean_rows: list, dirty_rows: list) -> list:
    header = dirty_rows[0]
    ground_truth = []
    for r in range(1, min(len(clean_rows), len(dirty_rows))):
        clean_row, dirty_row = clean_rows[r], dirty_rows[r]
        for c in range(min(len(clean_row), len(dirty_row))):
            if clean_row[c] != dirty_row[c]:
                ground_truth.append({
                    "row":       r - 1,          # 0-based, 헤더 제외
                    "col":       header[c],
                    "type":      "unknown",       # 실제 오류 — T1~T5 유형 미분류
                    "original":  clean_row[c],
                    "corrupted": dirty_row[c],
                })
    return ground_truth


def main():
    parser = argparse.ArgumentParser(description="E2 clean/dirty diff -> ground truth JSON")
    parser.add_argument("dataset_dir", help="clean.csv, dirty.csv가 있는 디렉토리 (예: data/E2_hospital)")
    args = parser.parse_args()

    clean_path = os.path.join(args.dataset_dir, "clean.csv")
    dirty_path = os.path.join(args.dataset_dir, "dirty.csv")
    out_path   = os.path.join(args.dataset_dir, "ground_truth.json")

    clean_rows = load_csv(clean_path)
    dirty_rows = load_csv(dirty_path)
    gt = build_ground_truth(clean_rows, dirty_rows)

    payload = {
        "source": "BigDaMa/raha (Apache-2.0), datasets/" + os.path.basename(args.dataset_dir.rstrip("/\\")).replace("E2_", ""),
        "note": "실제 오류 — 합성 아님. 유형(T1~T5) 미분류. F1은 상한 추정치로 해석 (04 §2.3, §5)",
        "total_rows": len(dirty_rows) - 1,
        "error_cells": len(gt),
        "ground_truth": gt,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[prepare_e2_ground_truth] {args.dataset_dir}: 오류 셀 {len(gt)}건 -> {out_path}")


if __name__ == "__main__":
    main()
