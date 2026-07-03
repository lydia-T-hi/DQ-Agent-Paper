#!/usr/bin/env bash
# PostToolUse Hook (Bash): main.py 완료 후 보고서 JSON 구조 검증
# - 필수 키 존재 여부 (metadata, dq_score, dq_grade, summary, changelog, rule_violations)
# - DQ 점수 범위 (0~100)
# - changelog 항목 필수 필드 (record_index, field, action, stage)
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INPUT=$(cat)

CMD=$(printf '%s' "$INPUT" | python -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('command', ''))
" 2>/dev/null || echo "")

EXIT_CODE=$(printf '%s' "$INPUT" | python -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('tool_response', {}).get('exit_code', -1))
" 2>/dev/null || echo "-1")

# main.py 실행이 아니거나 실패 시 무시
if [[ "$CMD" != *"main.py"* ]] || [ "$EXIT_CODE" != "0" ]; then
    echo '{}'
    exit 0
fi

# 최신 보고서 탐색 (_dq_result / _dq_cost 파일 제외)
LATEST=$(cd "$PROJECT_ROOT" && python -c "
import glob, os
files = sorted(glob.glob('report/*.json'), key=os.path.getmtime, reverse=True)
files = [f for f in files if '_dq_result' not in f and '_dq_cost' not in f]
print(files[0].replace('\\\\', '/') if files else '')
" 2>/dev/null || echo "")

if [ -z "$LATEST" ]; then
    echo '{}'
    exit 0
fi

# 구조 검증
cd "$PROJECT_ROOT" && python -c "
import json, sys

REQUIRED_KEYS  = ['metadata', 'grade', 'scores', 'consensus_summary', 'changelog', 'rule_violations']
CHANGELOG_KEYS = ['record_index', 'field', 'action', 'stage']

try:
    with open('$LATEST', encoding='utf-8') as f:
        report = json.load(f)
except json.JSONDecodeError as e:
    print(json.dumps({'systemMessage': f'[보고서 검증 오류] JSON 파싱 실패: {e}'}, ensure_ascii=False))
    sys.exit(0)
except Exception as e:
    print(json.dumps({'systemMessage': f'[보고서 검증 오류] 파일 읽기 실패: {e}'}, ensure_ascii=False))
    sys.exit(0)

errors = []

missing_keys = [k for k in REQUIRED_KEYS if k not in report]
if missing_keys:
    errors.append(f'필수 키 누락: {missing_keys}')

scores = report.get('scores', {})
final_score = scores.get('weighted_final') if isinstance(scores, dict) else None
if final_score is not None:
    try:
        if not (0 <= float(final_score) <= 100):
            errors.append(f'DQ 최종 점수 범위 오류: {final_score} (0~100 이어야 함)')
    except (TypeError, ValueError):
        errors.append(f'DQ 점수 타입 오류: {final_score!r}')

changelog = report.get('changelog')
if changelog is not None and not isinstance(changelog, list):
    errors.append('changelog 타입 오류: 배열이어야 함')
elif isinstance(changelog, list):
    for i, entry in enumerate(changelog[:10]):
        missing_cl = [k for k in CHANGELOG_KEYS if k not in entry]
        if missing_cl:
            errors.append(f'changelog[{i}] 누락 키: {missing_cl}')
            break

if errors:
    msg = '[보고서 검증 실패]\n' + '\n'.join(f'  • {e}' for e in errors)
    print(json.dumps({'systemMessage': msg}, ensure_ascii=False))
else:
    grade  = report.get('grade', '?')
    score  = final_score if final_score is not None else '?'
    n_cl   = len(report.get('changelog', []))
    n_viol = len(report.get('rule_violations', []))
    print(json.dumps({
        'systemMessage': f'[보고서 검증 통과] 점수={score} 등급={grade} | changelog={n_cl}건 위반={n_viol}건'
    }, ensure_ascii=False))
" 2>/dev/null || echo '{}'
