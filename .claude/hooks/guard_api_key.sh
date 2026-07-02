#!/usr/bin/env bash
# PreToolUse Hook (Bash): ANTHROPIC_API_KEY 노출 방지
export PYTHONIOENCODING=utf-8

INPUT=$(cat)

# 명령어 추출
CMD=$(printf '%s' "$INPUT" | python -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('tool_input', {}).get('command', ''))
" 2>/dev/null || echo "")

# 위험 패턴 검사
if echo "$CMD" | grep -qE "ANTHROPIC_API_KEY=sk-|ANTHROPIC_API_KEY =|--api-key sk-ant"; then
    python -c "
import json
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'ask',
        'permissionDecisionReason': (
            'ANTHROPIC_API_KEY가 명령어에 직접 포함되어 있습니다.\n'
            '이 프로젝트는 Claude CLI OAuth를 사용합니다.\n'
            '키를 명령어에 포함하면 크레딧이 소모될 수 있습니다.\n'
            '의도한 명령이 맞다면 허용(Allow)을 선택하세요.'
        )
    }
}, ensure_ascii=False))
"
else
    echo '{}'
fi
