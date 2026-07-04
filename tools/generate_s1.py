#!/usr/bin/env python3
"""
S1 데이터셋 생성기 — 국내 도메인 합성 고객 데이터 (주실험용)
04_experiment-plan_v1_1.md §2.1 스펙 구현.

- 규모: 1,000행 × 12열
- 생성: Faker(ko_KR) + 규칙 기반 교차필드 제약
  - 가입일 <= 최근구매일
  - 등급-구매액 정합 (등급을 먼저 정하고 그 구간 안에서 구매액 산출)
- 오염(오류 주입) 이전 원본(clean) 데이터 — tools/inject_errors.py 입력으로 사용

Usage:
  python tools/generate_s1.py [--n 1000] [--seed 42] [--out data/S1_customer_1000.json]
"""
import argparse
import json
import os
import random
from datetime import date, timedelta

from faker import Faker

_TODAY = date(2026, 7, 4)

# 등급 -> 구매액(KRW) 구간 및 표본 비중 (등급-구매액 정합 제약)
_GRADE_BANDS = [
    ("Bronze", 0,         500_000,   0.40),
    ("Silver", 500_000,   2_000_000, 0.35),
    ("Gold",   2_000_000, 5_000_000, 0.18),
    ("VIP",    5_000_000, 10_000_000, 0.07),
]


def _weighted_grade(rng: random.Random) -> tuple:
    r = rng.random()
    acc = 0.0
    for grade, lo, hi, w in _GRADE_BANDS:
        acc += w
        if r <= acc:
            return grade, lo, hi
    return _GRADE_BANDS[-1][:3]


def _random_date(rng: random.Random, start: date, end: date) -> date:
    span = (end - start).days
    if span <= 0:
        return start
    return start + timedelta(days=rng.randint(0, span))


def generate_records(n: int, seed: int) -> list:
    fake = Faker("ko_KR")
    fake.seed_instance(seed)
    rng = random.Random(seed)

    records = []
    for i in range(1, n + 1):
        grade, lo, hi = _weighted_grade(rng)
        purchase_amount = rng.randint(lo, max(lo, hi - 1))

        signup_date = _random_date(rng, _TODAY - timedelta(days=5 * 365), _TODAY - timedelta(days=1))
        last_purchase_date = _random_date(rng, signup_date, _TODAY)  # 가입일 <= 최근구매일 보장

        records.append({
            "customer_id":       f"CUST-{i:05d}",
            "name":              fake.name(),
            "age":               rng.randint(19, 75),
            "gender":            rng.choice(["Male", "Female"]),
            "email":             fake.email(),
            "phone":             fake.phone_number(),
            "postal_code":       fake.postcode(),
            "signup_date":       signup_date.isoformat(),
            "last_purchase_date": last_purchase_date.isoformat(),
            "purchase_amount_krw": purchase_amount,
            "membership_level":  grade,
            "is_churned":        rng.random() < 0.15,
        })
    return records


def main():
    parser = argparse.ArgumentParser(description="S1 합성 고객 데이터 생성 (04 §2.1)")
    parser.add_argument("--n",    type=int, default=1000, help="행 수 (기본 1000)")
    parser.add_argument("--seed", type=int, default=42,   help="재현성 고정 시드 (기본 42)")
    parser.add_argument("--out",  default=os.path.join("data", "S1_customer_1000.json"))
    args = parser.parse_args()

    records = generate_records(args.n, args.seed)

    payload = {
        "dataset_name": "S1_synthetic_customer",
        "description": (
            "04_experiment-plan_v1_1.md §2.1 기준 합성 국내 "
            "고객 데이터 (오염 주입 이전 원본)"
        ),
        "generator": "tools/generate_s1.py",
        "seed": args.seed,
        "record_count": len(records),
        "records": records,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[generate_s1] {len(records)}건 생성 완료 -> {args.out} (seed={args.seed})")


if __name__ == "__main__":
    main()
