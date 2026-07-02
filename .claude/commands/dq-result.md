가장 최근 DQ 파이프라인 보고서를 읽어 Before / After 변경 내역과 탐지 결과를 표로 출력합니다.

## 실행 규칙

인자($ARGUMENTS)를 파싱합니다:
- 보고서 파일 경로가 명시되면 해당 파일을 사용합니다.
- 지정되지 않으면 `report/` 디렉토리에서 가장 최근에 수정된 JSON 파일을 자동으로 찾습니다.
- 원본 파일 경로가 명시되지 않으면 보고서의 `metadata.source_file` 필드를 사용합니다.

## 실행 순서

1. Bash 도구로 최신 보고서 경로를 확인합니다:
   ```
   python -c "import glob, os; files=sorted(glob.glob('report/*.json'), key=os.path.getmtime, reverse=True); print(files[0] if files else '')"
   ```

2. 보고서가 없으면 "/dq-run 을 먼저 실행하세요." 를 안내하고 종료합니다.

3. Bash 도구로 compare_table.py 를 실행합니다:
   ```
   python tools/compare_table.py <원본파일> <보고서파일> --agent-sec 0 --pandas-sec 0 --max-rows 60
   ```

4. 출력 결과를 그대로 표시한 뒤, 아래 항목을 추가로 요약합니다:
   - DQ 점수 / 등급
   - 총 변경 건수 (normalize / fill / flag 각각)
   - Stage 2A vs Stage 2B 기여도
   - Critical 위반 목록 (필드명, 규칙, 건수)

5. "비용 분석은 `/dq-cost` 를 실행하세요." 를 안내합니다.
