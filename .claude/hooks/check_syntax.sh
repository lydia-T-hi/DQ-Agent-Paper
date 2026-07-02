#!/usr/bin/env bash
# PostToolUse Hook (Write|Edit): Python 문법 검사
export PYTHONIOENCODING=utf-8

INPUT=$(cat)

# stdin JSON에서 file_path 추출
FILE=$(printf '%s' "$INPUT" | python -c "
import json, sys
d = json.load(sys.stdin)
path = d.get('tool_input', {}).get('file_path', '') or d.get('tool_response', {}).get('filePath', '')
print(path)
" 2>/dev/null || echo "")

# .py 파일이 아니면 통과
if [[ "$FILE" != *.py ]]; then
    echo '{}'
    exit 0
fi

# 파일이 존재하지 않으면 통과
if [ ! -f "$FILE" ]; then
    echo '{}'
    exit 0
fi

# 문법 검사
ERR=$(python -m py_compile "$FILE" 2>&1)
if [ $? -ne 0 ]; then
    printf '[문법 오류] %s\n%s' "$FILE" "$ERR" | python -c "
import json, sys
print(json.dumps({'systemMessage': sys.stdin.read()}, ensure_ascii=False))
"
else
    echo '{}'
fi
