# 출처 (Provenance)

- 데이터셋: Flights (Raha 표준 벤치마크)
- 원천 저장소: https://github.com/BigDaMa/raha (Apache-2.0)
- 경로: `datasets/flights/{clean,dirty}.csv`
- 확보 커밋: `7be1334b8c7bbdac3f47ef514fb3e1e8c5fc181c` (2025-06-05)
- 확보 방법: 위 저장소 sparse-checkout, 파일 그대로 복사 (수정 없음)
- 규모: 2,376행 (헤더 제외)

04_experiment-plan_v1_1.md §2.3: "ground truth 라벨 제공분 사용, 오염 가능성 명시 단서 부착
(F1 상한 추정치)". 이 데이터는 실제 오류(합성 아님)이며 T1~T5 유형으로 분류되어 있지 않으므로,
E2 결과의 F1은 상한 추정치로만 해석한다.

`ground_truth.json`은 `tools/prepare_e2_ground_truth.py`로 clean/dirty를 셀 단위 diff하여 생성.
