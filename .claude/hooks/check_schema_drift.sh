#!/usr/bin/env bash
# PostToolUse Hook (Write|Edit): schemas.py 변경 시 PipelineState 필수 키 보전 확인
# - 스테이지 간 계약 키가 삭제되거나 이름이 바뀌면 즉시 경고
export PYTHONIOENCODING=utf-8

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

INPUT=$(cat)

FILE=$(printf '%s' "$INPUT" | python -c "
import json, sys
d = json.load(sys.stdin)
path = d.get('tool_input', {}).get('file_path', '') or d.get('tool_response', {}).get('filePath', '')
print(path)
" 2>/dev/null || echo "")

# schemas.py 수정이 아니면 통과
if [[ "$FILE" != *"schemas.py" ]]; then
    echo '{}'
    exit 0
fi

# PipelineState 필수 키 확인 (cd 후 상대경로로 schemas.py 로드)
cd "$PROJECT_ROOT" && python -c "
import json, sys, importlib.util, os

REQUIRED = {
    'profile':          'Stage 1 → 2B 프로파일 전달',
    'rule_violations':  'Stage 1 → 3A/4 위반 목록',
    'preprocessed_data':'Stage 2A → 2B → 3A 정제 데이터',
    'changelog':        'Stage 2A/2B → 4 변경 이력',
    'ambiguous_indices':'Stage 2A → 2B 라우팅 키',
    'interpretations':  'Stage 2B → 4 해석 결과',
}

try:
    spec = importlib.util.spec_from_file_location('schemas', 'schemas.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    hints = getattr(mod.PipelineState, '__annotations__', {})
except Exception as e:
    print(json.dumps({'systemMessage': f'[스키마 검사 실패] schemas.py 로드 오류: {e}'}, ensure_ascii=False))
    sys.exit(0)

missing = {k: v for k, v in REQUIRED.items() if k not in hints}
if missing:
    lines = '\n'.join(f'  • {k}: {v}' for k, v in missing.items())
    print(json.dumps({
        'systemMessage': (
            '[스키마 경고] PipelineState 필수 키 누락 — 스테이지 간 계약이 깨질 수 있습니다.\n'
            f'{lines}'
        )
    }, ensure_ascii=False))
else:
    present = list(hints.keys())
    print(json.dumps({
        'systemMessage': f'[스키마 검증 통과] PipelineState 필수 키 {len(REQUIRED)}개 모두 존재'
    }, ensure_ascii=False))
" 2>/dev/null || echo '{}'
