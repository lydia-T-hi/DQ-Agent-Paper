#!/usr/bin/env bash
# PostToolUse Hook (Bash): 파이프라인 완료 알림
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INPUT=$(cat)

# 명령어 및 종료 코드 추출
CMD=$(printf '%s' "$INPUT" | python -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('command', ''))
" 2>/dev/null || echo "")

EXIT_CODE=$(printf '%s' "$INPUT" | python -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('tool_response', {}).get('exit_code', 0))
" 2>/dev/null || echo "0")

# main.py 실행 명령이 아니거나 실패 시 무시
if [[ "$CMD" != *"main.py"* ]] || [ "$EXIT_CODE" != "0" ]; then
    echo '{}'
    exit 0
fi

# 최신 보고서 파일 탐색 (hooks는 프로젝트 루트에서 실행됨 → 상대경로 사용)
LATEST=$(python -c "
import glob, os
files = sorted(glob.glob('report/*.json'), key=os.path.getmtime, reverse=True)
if files:
    print(files[0].replace('\\\\', '/'))
" 2>/dev/null || echo "")

if [ -n "$LATEST" ]; then
    printf '%s' "$LATEST" | python -c "
import json, sys
latest = sys.stdin.read().strip()
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PostToolUse',
        'additionalContext': f'최신 보고서: {latest}'
    }
}, ensure_ascii=False))
"
else
    echo '{}'
fi
