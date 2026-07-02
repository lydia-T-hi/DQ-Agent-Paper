#!/usr/bin/env bash
# SessionStart Hook: 실행 환경 사전 점검
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

MSGS=()

# Claude CLI 설치 확인
if ! command -v claude &>/dev/null; then
    MSGS+=("⚠ Claude CLI가 설치되지 않았습니다. Stage 2B가 실행되지 않습니다.")
fi

# .env 파일 확인
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    MSGS+=("⚠ .env 파일이 없습니다. OpenAI Stage 3A 사용 시 OPENAI_API_KEY가 필요합니다.")
fi

# ANTHROPIC_API_KEY 경고
if [ -n "$ANTHROPIC_API_KEY" ]; then
    MSGS+=("⚠ ANTHROPIC_API_KEY 환경변수 감지 — Stage 2B subprocess에서 자동 제외되지만, 직접 API 호출 시 크레딧을 소모할 수 있습니다.")
fi

# report/ 및 tests/output/ 디렉토리 자동 생성
mkdir -p "$PROJECT_ROOT/report" "$PROJECT_ROOT/tests/output"
if [ ! -d "$PROJECT_ROOT/report" ]; then
    MSGS+=("ℹ report/ 디렉토리를 생성했습니다.")
fi

# JSON 출력
if [ ${#MSGS[@]} -gt 0 ]; then
    printf '%s\n' "${MSGS[@]}" | python -c "
import json, sys
msg = sys.stdin.read().rstrip('\n')
print(json.dumps({'systemMessage': msg}, ensure_ascii=False))
"
else
    echo '{}'
fi
