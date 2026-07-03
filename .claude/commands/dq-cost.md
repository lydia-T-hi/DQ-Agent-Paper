가장 최근 DQ 파이프라인 보고서를 기준으로 ROI 및 비용 비교를 분석하고 표로 출력합니다.

## 실행 규칙

인자($ARGUMENTS)를 파싱합니다:
- `--hourly-rate N` 이 포함되면 해당 인건비(원/시간)를 사용합니다. 없으면 기본값 30000 을 사용합니다.
- `--export` 가 포함되면 Excel 파일로도 저장합니다.
- 보고서 경로가 명시되지 않으면 `report/` 디렉토리에서 가장 최근 파일을 자동으로 찾습니다.
- 원본 파일 경로가 명시되지 않으면 보고서의 `metadata.source_file` 필드를 사용합니다.

## 실행 순서

1. Bash 도구로 최신 보고서 경로를 확인합니다:
   ```
   python -c "import glob, os; files=sorted(glob.glob('report/*.json'), key=os.path.getmtime, reverse=True); print(files[0] if files else '')"
   ```

2. 보고서가 없으면 "/dq-run 을 먼저 실행하세요." 를 안내하고 종료합니다.

3. 보고서에서 원본 파일명을 읽습니다:
   ```
   python -c "import json; r=json.load(open('<보고서>',encoding='utf-8')); print(r.get('metadata',{}).get('source_file',''))"
   ```

4. Bash 도구로 roi_pandas.py 를 실행합니다:
   ```
   python tools/roi_pandas.py <원본파일> <보고서파일> --hourly-rate <N> --save-report report/
   ```
   `--export` 가 요청된 경우 `--export roi_result.xlsx` 를 추가합니다.

5. 출력 결과를 그대로 표시한 뒤, 아래 항목을 추가로 요약합니다:
   - 수동 검토 예상 시간 vs Agent 처리 시간
   - 절감 비용 (원)
   - ROI (%)
   - 완전성 변화 (Before → After) 및 감소 이유 한 줄 설명
     (잘못된 값을 null로 교체했기 때문에 완전성이 줄어드는 것은 정확성 향상의 결과입니다.)
   - Stage 2A vs 2B 비용 기여도 (2A는 LLM 0회, 2B만 Claude 호출)

6. 인건비를 바꿔 재계산하려면 `/dq-cost --hourly-rate 50000` 형태로 실행하세요. 를 안내합니다.
