#!/usr/bin/env bash
# E1 주실험 드라이버 — S1 주입 배치 10종 × A1~A5 (동결: 539b18d6)
# 배치별로 러너 1회 호출 = bench-result 1회차 (자동 커밋). 순차 실행.
set -u
cd "$(dirname "$0")"

BATCHES=(
  "0.10 1" "0.10 2" "0.10 3" "0.10 4" "0.10 5"
  "0.20 1" "0.20 2" "0.20 3" "0.20 4" "0.20 5"
)

for b in "${BATCHES[@]}"; do
  rate="${b% *}"; seed="${b#* }"
  tag="r$(python -c "print(int(${rate}*100))")_s${seed}"
  data="runs/injected/S1_customer_1000_${tag}.json"
  gt="runs/injected/S1_customer_1000_${tag}_ground_truth.json"
  echo "=== E1 배치 ${tag} 시작 $(date +%H:%M:%S) ==="
  python run_experiments.py --experiment E1 \
    --dataset "$data" --ground-truth "$gt" \
    --configs A1,A2,A3,A4,A5 --reps 1 \
    --error-rate "$rate" --seed "$seed" \
    --llm-backend api \
    || echo "!!! 배치 ${tag} 러너 비정상 종료 — 다음 배치 계속"
done
echo "=== E1 전체 완료 $(date +%H:%M:%S) ==="
