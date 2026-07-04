#!/usr/bin/env python3
"""
S2 임시 후보 데이터셋 생성 — 2025년 이후 원천 기반 정형 셋 (주실험, 임시)
04_experiment-plan_v1_1.md §2.2: "후보... 실험 착수 전 최종 선정" — 원천이 아직 미확정이므로
여기서는 국토교통부 "아파트매매 실거래자료"(data.go.kr 공개, 부동산 실거래) 스타일 스키마를
임시로 차용하고 값은 전부 합성(재생성)한다.

선정 기준 충족 확인: 수치+범주 혼합(O), 10열 이상(12열), S1(고객/CRM)과 다른 도메인(O)

**주의**: 이 파일은 PLACEHOLDER 입니다. 04 §2.2 "실험 착수 전 최종 선정" 절차에 따라
실제 2025~2026 공개 원천이 정해지면 스키마를 그 원천에 맞게 교체해야 합니다.

Usage:
  python tools/generate_s2_candidate.py [--n 1000] [--seed 42]
"""
import argparse
import json
import os
import random

_DISTRICTS = [
    "강남구", "서초구", "송파구", "강동구", "마포구", "영등포구",
    "성동구", "광진구", "노원구", "은평구", "종로구", "중구",
]
_ROAD_SUFFIX = ["로", "길", "대로"]
_DONG_SUFFIX = ["동"]
_DEAL_TYPES  = ["매매", "전세", "월세"]


def _apt_name(rng: random.Random) -> str:
    stems = ["힐스테이트", "래미안", "푸르지오", "자이", "더샵", "아이파크", "e편한세상", "롯데캐슬"]
    return f"{rng.choice(stems)}{rng.randint(1, 9)}단지"


def generate_records(n: int, seed: int) -> list:
    rng = random.Random(seed)
    records = []
    for i in range(1, n + 1):
        district   = rng.choice(_DISTRICTS)
        dong       = f"{rng.choice(['역삼', '삼성', '방배', '잠실', '독산', '망원', '행당'])}동"
        area_m2    = round(rng.uniform(39.6, 134.9), 2)
        floor      = rng.randint(1, 25)
        built_year = rng.randint(1988, 2025)
        year_month = f"{rng.choice([2025, 2026])}{rng.randint(1, 12):02d}"
        day        = rng.randint(1, 28)

        # 거래금액(만원): 면적·층·구 인기도에 대략 비례 (수치-범주 정합)
        district_premium = 1.0 + (_DISTRICTS.index(district) < 4) * 0.8
        base_price = area_m2 * rng.uniform(700, 1100) * district_premium
        price_manwon = int(base_price * (1 + floor * 0.005))

        records.append({
            "시군구":       f"서울특별시 {district}",
            "법정동":       dong,
            "단지명":       _apt_name(rng),
            "전용면적_m2":  area_m2,
            "계약년월":     year_month,
            "계약일":       day,
            "거래금액_만원": price_manwon,
            "층":           floor,
            "건축년도":     built_year,
            "도로명":       f"{dong[:-1]}{rng.choice(_ROAD_SUFFIX)} {rng.randint(1, 200)}",
            "거래유형":     rng.choices(_DEAL_TYPES, weights=[0.6, 0.3, 0.1])[0],
            "해제여부":     rng.random() < 0.03,
        })
    return records


def main():
    parser = argparse.ArgumentParser(description="S2 임시 후보(부동산 실거래 스타일) 생성")
    parser.add_argument("--n",    type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out",  default=os.path.join("data", "S2_candidate", "S2_realestate_candidate.json"))
    args = parser.parse_args()

    records = generate_records(args.n, args.seed)
    payload = {
        "dataset_name": "S2_candidate_realestate",
        "status": "tentative_placeholder",
        "description": (
            "04_experiment-plan_v1_1.md §2.2 임시 후보 — 국토교통부 아파트매매 실거래자료 "
            "스타일 스키마 차용, 값은 전부 합성. 실제 원천 확정 시 교체 필요."
        ),
        "generator": "tools/generate_s2_candidate.py",
        "seed": args.seed,
        "record_count": len(records),
        "records": records,
    }

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[generate_s2_candidate] {len(records)}건 생성 완료 -> {args.out} (seed={args.seed}) [PLACEHOLDER]")


if __name__ == "__main__":
    main()
