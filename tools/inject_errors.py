#!/usr/bin/env python3
"""
ErrorInjector — 04_experiment-plan_v1_1.md §3 오류 주입 프로토콜 구현

유형 5종 × 오류율 × 시드 → 오염 데이터 + ground truth JSON.

  T1 결측:     값 → 센티널 4종(null/""/"N/A"/"-") 균등 순환      (R1, R2)
  T2 형식:     패턴 파괴 (전화 하이픈 제거, 날짜 포맷 교란 등)     (R3, R4)
  T3 범위:     극단값·불가능값 치환 (999 / -1 / 10^12)            (R5, R6)
  T4 중복:     행 복제 + 키 변형 (ID 접미사) — 말미에 추가        (R7)
  T5 교차필드: 날짜쌍 제약 위반 (가입일 > 최근구매일)              (R8)

주입 규칙 (§3.2):
  - 오류율 ρ: 셀 기준 (총 셀 수 × ρ), 유형별 균등 배분 (각 ρ/5)
  - 동일 셀 이중 오염 금지
  - 유형에 적합한 컬럼이 없으면 해당 유형은 건너뛰고 메타데이터에 기록
  - ground truth: {row, col, type, original, corrupted} — row는 0-based 레코드 인덱스,
    T4 복제행은 말미에 추가되므로 기존 행 인덱스는 불변

Usage:
  python tools/inject_errors.py --input data/S1_customer_1000.json --rate 0.1 --seed 2 --out runs/injected/
"""
import argparse
import json
import os
import random
import re

_SENTINELS = [None, "", "N/A", "-"]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load_records(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for val in raw.values():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return [dict(r) for r in val]
    raise ValueError("지원하지 않는 JSON 구조 (records 리스트 필요)")


def _classify_columns(records: list) -> dict:
    """샘플 기반 컬럼 분류 — 유형별 적합 컬럼 결정"""
    cols = list(records[0].keys())
    sample = records[: min(50, len(records))]

    def col_values(c):
        return [r.get(c) for r in sample if r.get(c) is not None]

    numeric, dates, formatted = [], [], []
    for c in cols:
        vals = col_values(c)
        if not vals:
            continue
        clow = c.lower()
        if all(isinstance(v, bool) for v in vals):
            continue
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            numeric.append(c)
        elif all(isinstance(v, str) and _DATE_RE.match(v) for v in vals):
            dates.append(c)
        elif any(k in clow for k in ("email", "phone", "tel", "postal", "zip", "우편", "전화")):
            formatted.append(c)

    key_col = next((c for c in cols if "id" in c.lower() or c.lower().endswith("_no")), cols[0])

    # 교차필드 날짜쌍: (선행일, 후행일) — 이름 휴리스틱
    pair = None
    starts = [c for c in dates if any(k in c.lower() for k in ("signup", "join", "start", "가입"))]
    ends   = [c for c in dates if any(k in c.lower() for k in ("last", "end", "purchase", "구매", "최근"))]
    if starts and ends:
        pair = (starts[0], ends[0])

    return {
        "all": cols, "numeric": numeric, "dates": dates,
        "formatted": formatted + dates,          # T2는 날짜 포맷 교란도 포함
        "key": key_col, "date_pair": pair,
    }


def _corrupt_format(value, col: str, rng: random.Random):
    s = str(value)
    if _DATE_RE.match(s):
        y, m, d = s.split("-")
        return rng.choice([f"{d}/{m}/{y}", f"{y}.{m}.{d}", f"{y}{m}{d}"])
    if "@" in s:
        return s.replace("@", rng.choice(["#", " at ", ""]))
    if "-" in s:
        return s.replace("-", "")
    return s + rng.choice(["!", "  ", "_x"])


def _corrupt_range(value, rng: random.Random):
    if isinstance(value, (int, float)) and abs(value) < 1000:
        return rng.choice([999, -1])
    return rng.choice([10 ** 12, -1, 0])


def inject(records: list, rate: float, seed: int) -> tuple:
    """오염된 레코드 리스트와 ground truth 리스트를 반환 (원본은 변경하지 않음)"""
    rng      = random.Random(seed)
    out      = [dict(r) for r in records]
    info     = _classify_columns(records)
    n_rows   = len(records)
    n_cols   = len(info["all"])
    budget   = round(rate * n_rows * n_cols)
    per_type = budget // 5

    ground_truth, used, skipped = [], set(), []

    def pick_cell(eligible_cols):
        """이중 오염 방지하며 (row, col) 선택 — 실패 시 None"""
        for _ in range(200):
            r = rng.randrange(n_rows)
            c = rng.choice(eligible_cols)
            if (r, c) not in used and out[r].get(c) is not None:
                used.add((r, c))
                return r, c
        return None

    # T1 결측 — 모든 컬럼
    for i in range(per_type):
        cell = pick_cell(info["all"])
        if not cell:
            break
        r, c = cell
        corrupted = _SENTINELS[i % 4]
        ground_truth.append({"row": r, "col": c, "type": "T1_missing",
                             "original": out[r][c], "corrupted": corrupted})
        out[r][c] = corrupted

    # T2 형식 — 형식 보유 컬럼
    if info["formatted"]:
        for _ in range(per_type):
            cell = pick_cell(info["formatted"])
            if not cell:
                break
            r, c = cell
            corrupted = _corrupt_format(out[r][c], c, rng)
            ground_truth.append({"row": r, "col": c, "type": "T2_format",
                                 "original": out[r][c], "corrupted": corrupted})
            out[r][c] = corrupted
    else:
        skipped.append("T2_format")

    # T3 범위 — 수치 컬럼
    if info["numeric"]:
        for _ in range(per_type):
            cell = pick_cell(info["numeric"])
            if not cell:
                break
            r, c = cell
            corrupted = _corrupt_range(out[r][c], rng)
            ground_truth.append({"row": r, "col": c, "type": "T3_range",
                                 "original": out[r][c], "corrupted": corrupted})
            out[r][c] = corrupted
    else:
        skipped.append("T3_range")

    # T4 중복 — 행 복제 + 키 변형, 말미 추가 (기존 인덱스 불변)
    key = info["key"]
    for _ in range(per_type):
        src = rng.randrange(n_rows)
        dup = dict(out[src])
        orig_key = dup.get(key)
        dup[key] = f"{orig_key}{rng.choice(['-1', '_D', 'X'])}" if orig_key else orig_key
        out.append(dup)
        ground_truth.append({"row": len(out) - 1, "col": key, "type": "T4_duplicate",
                             "original": orig_key, "corrupted": dup[key]})

    # T5 교차필드 — 날짜쌍 제약 위반 (선행일을 후행일 이후로)
    if info["date_pair"]:
        c_start, c_end = info["date_pair"]
        for _ in range(per_type):
            cell = pick_cell([c_start])
            if not cell:
                break
            r, _ = cell
            end_val = out[r].get(c_end)
            if not (isinstance(end_val, str) and _DATE_RE.match(end_val)):
                continue
            y = int(end_val[:4]) + 1
            corrupted = f"{y}{end_val[4:]}"
            ground_truth.append({"row": r, "col": c_start, "type": "T5_crossfield",
                                 "original": out[r][c_start], "corrupted": corrupted})
            out[r][c_start] = corrupted
    else:
        skipped.append("T5_crossfield")

    meta = {
        "rate": rate, "seed": seed, "budget_cells": budget, "per_type": per_type,
        "injected": len(ground_truth), "skipped_types": skipped,
        "rows_before": n_rows, "rows_after": len(out),
    }
    return out, ground_truth, meta


def main():
    parser = argparse.ArgumentParser(description="오류 주입 (04 §3)")
    parser.add_argument("--input", required=True)
    parser.add_argument("--rate",  type=float, required=True, help="셀 기준 오류율 (예: 0.1)")
    parser.add_argument("--seed",  type=int, required=True)
    parser.add_argument("--out",   default="runs/injected/")
    args = parser.parse_args()

    records = _load_records(args.input)
    corrupted, ground_truth, meta = inject(records, args.rate, args.seed)

    base     = os.path.splitext(os.path.basename(args.input))[0]
    tag      = f"{base}_r{int(args.rate * 100)}_s{args.seed}"
    os.makedirs(args.out, exist_ok=True)
    data_path = os.path.join(args.out, f"{tag}.json")
    gt_path   = os.path.join(args.out, f"{tag}_ground_truth.json")

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump({"dataset_name": tag, "injection_meta": meta, "records": corrupted},
                  f, ensure_ascii=False, indent=2)
    with open(gt_path, "w", encoding="utf-8") as f:
        json.dump({"source": args.input, **meta, "ground_truth": ground_truth},
                  f, ensure_ascii=False, indent=2)

    print(f"[inject_errors] {meta['injected']}건 주입 (예산 {meta['budget_cells']}셀, "
          f"유형당 {meta['per_type']}) -> {data_path}")
    if meta["skipped_types"]:
        print(f"[inject_errors] 건너뛴 유형: {meta['skipped_types']}")
    print(f"[inject_errors] ground truth -> {gt_path}")


if __name__ == "__main__":
    main()
