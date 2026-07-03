#!/usr/bin/env bash
# PreToolUse Hook (Bash): main.py 실행 시 입력 파일 경로 보안 검사
# - 경로 순회(..) 탐지
# - SQL 인젝션 위험 문자(' ; | & ` $) 탐지
export PYTHONIOENCODING=utf-8

INPUT=$(cat)

CMD=$(printf '%s' "$INPUT" | python -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('command', ''))
" 2>/dev/null || echo "")

# main.py 실행이 아니면 통과
if [[ "$CMD" != *"main.py"* ]]; then
    echo '{}'
    exit 0
fi

# 파일 인수 추출 (main.py 다음 첫 번째 토큰)
FILE_ARG=$(printf '%s' "$CMD" | python -c "
import sys, re
cmd = sys.stdin.read()
m = re.search(r'main\.py\s+([^\s]+)', cmd)
print(m.group(1) if m else '')
" 2>/dev/null || echo "")

if [ -z "$FILE_ARG" ]; then
    echo '{}'
    exit 0
fi

# 보안 검사: Python으로 위험 패턴 탐지
RESULT=$(printf '%s' "$FILE_ARG" | python -c "
import sys, re, json

path = sys.stdin.read().strip()
errors = []

if '..' in path:
    errors.append('경로 순회 패턴(..) 감지 — 디렉토리 탈출 위험')

if re.search(r\"[';|&\x60\$]\", path):
    errors.append(\"위험 문자 감지 (' ; | & \x60 \$) — DuckDB SQL 인젝션 위험\")

if errors:
    reason = '\n'.join(f'  • {e}' for e in errors)
    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'ask',
            'permissionDecisionReason': (
                f'[보안] 입력 파일 경로 이상 감지\n'
                f'파일: {path}\n'
                f'{reason}\n'
                f'의도한 경로가 맞다면 허용(Allow)을 선택하세요.'
            )
        }
    }, ensure_ascii=False))
else:
    print('{}')
" 2>/dev/null || echo '{}')

printf '%s' "$RESULT"
