"""
Stage 2B: Claude — 모호성 판단 전용 (통계적 이상치 해석)

Stage 2A(결정론적)가 처리한 후에도 Z-score > 3 이상치가 남은 레코드만 처리합니다.
  - 이상치가 센티넬 값인지 / 실제 오류인지 / 정상 극단값인지 판단
  - 변경은 최소화: 불확실하면 flag + interpretation으로 표시
  - ambiguous_indices가 비어 있으면 Claude 호출 없이 즉시 종료

병렬 구조:
  - 20행/호출 배치(공정성 프로토콜 고정)를 최대 _MAX_WORKERS개 동시 실행
  - 병합은 청크 순서 기준 → 완료 순서와 무관하게 결과 결정론적
  - 호출별 usage를 합산해 state["token_usage"]["stage2b"]에 기록 (계측 실패 = 실행 실패)
"""
import json
import math
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.runnables import RunnableLambda

_SYSTEM_INSTRUCTIONS = """\
당신은 데이터 품질 감사 전문가입니다.
Stage 2A(결정론적 처리)가 이미 명백한 오류(이메일 형식, 음수 금액, 미래 날짜, 나이 범위 등)를 처리했습니다.
여기서는 자동 처리로 판단하기 어려운 **통계적 이상치와 모호한 패턴**만 검토합니다.

판단 기준:
- Z-score > 3 값이 센티넬 값인지 (예: 9999999999 = 최대값 더미)
- 정상 극단값인지 (실제로 발생 가능한 값)
- 동일 레코드 내 다른 필드와 논리적으로 불일치하는지

원칙:
- 확실한 경우만 수정하고, 불확실하면 원본 유지 + flag + interpretation
- 레코드를 추가하거나 삭제하지 마세요
- changelog에는 실제 변경된 경우만 기록하세요

반드시 아래 JSON 구조로만 응답하세요 (마크다운 없이 순수 JSON):

{
  "preprocessed_data": [ ...레코드 리스트 (원본 개수 유지)... ],
  "changelog": [
    {
      "record_index": <정수>,
      "field": "<필드명>",
      "action": "normalize|fill|flag|keep",
      "original": <원본값>,
      "new_value": <변환후값 또는 null>,
      "reason": "<한 줄 이유>",
      "stage": "2b"
    }
  ],
  "interpretations": [
    {
      "rule": "<rule 이름>",
      "field": "<필드명>",
      "interpretation": "<이 값이 의미하는 것>",
      "recommendation": "fix|flag|ignore"
    }
  ]
}
"""

_CHUNK_SIZE  = 20   # 공정성 프로토콜 고정값 (05 문서 §2.4) — config와 무관하게 동일 배치 유지
_MAX_WORKERS = 4    # 병렬 워커 수 — 자유 변수 (wall-clock에만 영향, 토큰 비용 불변)
_TIMEOUT     = 600
_MAX_RETRY   = 1

_ZERO_USAGE = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0, "calls": 0}


# ── Claude CLI 호출 ────────────────────────────────────────────────────────────
def _call_claude_once(prompt: str) -> tuple:
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="dq2b_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with open(tmp_path, "rb") as stdin_file:
            result = subprocess.run(
                ["claude", "--print", "--output-format", "json"],
                stdin=stdin_file,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=_TIMEOUT,
                env=env,
            )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if result.returncode != 0:
        detail = result.stderr or result.stdout or "(출력 없음)"
        raise RuntimeError(f"Claude CLI 오류 (exit={result.returncode}):\n{detail}")

    try:
        cli_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        # 비용 결측 데이터 금지 원칙: usage를 읽을 수 없으면 실행 실패 처리
        raise RuntimeError(
            "Claude CLI 응답이 JSON이 아님 — 토큰 계측 불가:\n" + result.stdout[:500]
        )
    if cli_data.get("is_error"):
        raise RuntimeError(f"Claude CLI 오류: {cli_data.get('result')}")

    usage_raw = cli_data.get("usage")
    if not usage_raw:
        raise RuntimeError("Claude CLI 응답에 usage 필드 없음 — 토큰 계측 불가")
    usage = {
        "input":          usage_raw.get("input_tokens", 0),
        "output":         usage_raw.get("output_tokens", 0),
        "cache_creation": usage_raw.get("cache_creation_input_tokens", 0),
        "cache_read":     usage_raw.get("cache_read_input_tokens", 0),
    }

    text = cli_data.get("result", "").strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    return json.loads(text), usage


def _call_claude_cli(prompt: str) -> tuple:
    for attempt in range(_MAX_RETRY + 1):
        try:
            return _call_claude_once(prompt)
        except subprocess.TimeoutExpired:
            if attempt < _MAX_RETRY:
                print(f"[Stage2B-Claude] 타임아웃({_TIMEOUT}s), 재시도... ({attempt+1}/{_MAX_RETRY})")
            else:
                raise RuntimeError(f"Claude CLI 타임아웃: {_TIMEOUT}초 × {_MAX_RETRY+1}회 초과")


# ── 프롬프트 구성 ──────────────────────────────────────────────────────────────
def _profile_summary(profile: dict, fields: set) -> str:
    lines = []
    for field, p in profile.items():
        if field not in fields:
            continue
        base = f"  {field}: null={p['null_pct']}%"
        if "avg" in p:
            base += f", range=[{p['min']}, {p['max']}] avg={p['avg']} stddev={p.get('stddev')}"
        lines.append(base)
    return "\n".join(lines) or "  (해당 필드 프로파일 없음)"


def _build_prompt(profile: dict, violations: list, records: list) -> str:
    # 이상치 필드만 프로파일에 포함 (프롬프트 크기 절감)
    outlier_fields = set()
    for rec in records:
        for field, value in rec.items():
            p = profile.get(field, {})
            if "avg" in p and p.get("stddev") and p["stddev"] > 0:
                try:
                    if abs(float(value) - p["avg"]) / p["stddev"] > 3:
                        outlier_fields.add(field)
                except Exception:
                    pass

    viol_text = "\n".join(
        f"  [{v['severity'].upper()}] {v['field']}.{v['rule']}: {v['detail']}"
        for v in violations
    ) or "  없음"

    return (
        _SYSTEM_INSTRUCTIONS
        + "\n\n---\n\n"
        + "## 이상치 필드 프로파일\n"
        + _profile_summary(profile, outlier_fields)
        + "\n\n## 관련 규칙 위반\n"
        + viol_text
        + f"\n\n## 검토 레코드 ({len(records)}건) — Stage 2A 처리 완료 상태\n"
        + json.dumps(records, ensure_ascii=False, indent=2, default=str)
        + "\n\n위 레코드의 이상치를 검토하고 결과를 JSON으로 반환하세요."
    )


# ── 청크 처리 (병렬) ──────────────────────────────────────────────────────────
def _process_chunk(args: tuple) -> tuple:
    chunk, orig_indices, profile, violations, label = args
    prompt = _build_prompt(profile, violations, chunk)
    result, usage = _call_claude_cli(prompt)

    preprocessed = result.get("preprocessed_data", chunk)

    changelog = []
    for entry in result.get("changelog", []):
        entry   = dict(entry)
        entry["stage"] = "2b"
        rec_idx = entry.get("record_index")
        if rec_idx is not None and rec_idx < len(orig_indices):
            entry["record_index"] = orig_indices[rec_idx]
        changelog.append(entry)

    return preprocessed, changelog, result.get("interpretations", []), usage, label


# ── 스테이지 실행 ─────────────────────────────────────────────────────────────
def _record_usage(state: dict, usage: dict) -> dict:
    token_usage = dict(state.get("token_usage", {}))
    token_usage["stage2b"] = usage
    return token_usage


def _run(state: dict) -> dict:
    ambiguous_idx = state.get("ambiguous_indices", [])

    if not ambiguous_idx:
        print("[Stage2B-Claude] 이상치 레코드 없음 — Claude 호출 생략")
        return {**state, "token_usage": _record_usage(state, dict(_ZERO_USAGE))}

    print(f"[Stage2B-Claude] 모호성 판단 시작 — {len(ambiguous_idx)}건 대상")

    preprocessed    = list(state["preprocessed_data"])   # 2A 결과 복사
    changelog_2b    = []
    interpretations = list(state.get("interpretations", []))

    to_process  = [preprocessed[i] for i in ambiguous_idx]
    chunks_args = []
    chunk_size  = _CHUNK_SIZE
    n_chunks    = math.ceil(len(to_process) / chunk_size)

    for ci in range(n_chunks):
        start     = ci * chunk_size
        chunk     = to_process[start : start + chunk_size]
        orig_idx  = ambiguous_idx[start : start + len(chunk)]
        label     = f"{ci+1}/{n_chunks}"
        chunks_args.append((chunk, orig_idx, state["profile"], state["rule_violations"], label))

    workers = min(_MAX_WORKERS, n_chunks)
    done    = 0
    print(f"[Stage2B-Claude] 병렬 처리 (최대 {workers}개 동시 실행, 배치 {chunk_size}행/호출)")

    # 완료 순서와 무관하게 청크 순서대로 병합해야 결과가 결정론적이다 (실험 재현성)
    results = [None] * n_chunks

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_process_chunk, arg): ci
            for ci, arg in enumerate(chunks_args)
        }
        for future in as_completed(future_map):
            ci          = future_map[future]
            results[ci] = future.result()
            done       += 1
            print(f"[Stage2B-Claude] 청크 {results[ci][-1]} 완료 ({done}/{n_chunks})")

    usage_total = dict(_ZERO_USAGE)
    seen        = {(x["rule"], x["field"]) for x in interpretations}

    for ci, (chunk_preprocessed, changelog, interps, usage, _label) in enumerate(results):
        orig_indices = chunks_args[ci][1]
        for j, rec in enumerate(chunk_preprocessed):
            if j < len(orig_indices):
                preprocessed[orig_indices[j]] = rec

        changelog_2b.extend(changelog)

        for interp in interps:
            key = (interp.get("rule"), interp.get("field"))
            if key not in seen:
                interpretations.append(interp)
                seen.add(key)

        for k in ("input", "output", "cache_creation", "cache_read"):
            usage_total[k] += usage.get(k, 0)
        usage_total["calls"] += 1

    changelog_2b.sort(key=lambda e: (e.get("record_index") or 0, e.get("field") or ""))

    total_cl = len(state.get("changelog", [])) + len(changelog_2b)
    print(
        f"[Stage2B-Claude] 완료 — 추가 변경 {len(changelog_2b)}건 / "
        f"해석 {len(interpretations)}건 (누적 changelog {total_cl}건)"
    )
    print(
        f"[Stage2B-Claude] 토큰 사용량 — 입력 {usage_total['input']:,} / "
        f"출력 {usage_total['output']:,} / 호출 {usage_total['calls']}회"
    )

    return {
        **state,
        "preprocessed_data": preprocessed,
        "changelog":         state.get("changelog", []) + changelog_2b,
        "interpretations":   interpretations,
        "token_usage":       _record_usage(state, usage_total),
    }


stage2b_claude_agent = RunnableLambda(_run)
