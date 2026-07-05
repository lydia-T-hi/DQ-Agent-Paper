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

백엔드 (state["llm_backend"] 또는 env DQ_LLM_BACKEND, 기본 cli):
  - cli: Claude CLI subprocess + Pro OAuth (무료) — 개발·스모크용.
         temperature 미제어, CLI 하네스 프롬프트가 앞에 붙음
  - api: Anthropic SDK 직접 호출 (실비) — 본실험(E1/E2)용.
         temperature=0, 프롬프트 전문 통제, 시스템 프롬프트 캐싱.
         프롬프트 내용은 두 백엔드 동일 (system/user 역할 분리만 다름)
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

판단 예시 (few-shot):

예시 1 — 센티널 값 (수정):
입력 레코드: {"customer_id": "C-101", "purchase_amount": 9999999999}
프로파일: purchase_amount avg=52000 stddev=48000
판단: 9999999999는 avg 대비 비현실적 극단값이며 9가 반복되는 전형적 센티널 → null 처리
changelog: {"record_index": 0, "field": "purchase_amount", "action": "flag",
  "original": 9999999999, "new_value": null, "reason": "센티널 의심값(9 반복, z-score 극단)", "stage": "2b"}

예시 2 — 정상 극단값 (유지):
입력 레코드: {"customer_id": "C-202", "purchase_amount": 480000}
프로파일: purchase_amount avg=52000 stddev=48000
판단: z-score > 3이지만 실제 발생 가능한 고액 구매 → 원본 유지, changelog에 keep 기록
changelog: {"record_index": 1, "field": "purchase_amount", "action": "keep",
  "original": 480000, "new_value": 480000, "reason": "정상 극단값으로 판단(발생 가능 범위)", "stage": "2b"}

예시 3 — 교차필드 불일치 (플래그):
입력 레코드: {"signup_date": "2027-01-15", "last_purchase_date": "2025-11-02"}
판단: 가입일이 최근구매일보다 미래 → 논리 모순이나 어느 쪽이 오류인지 단정 불가 → flag만
changelog: {"record_index": 2, "field": "signup_date", "action": "flag",
  "original": "2027-01-15", "new_value": null, "reason": "가입일 > 최근구매일 교차필드 모순", "stage": "2b"}

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
_MODEL       = "claude-sonnet-4-6"   # 04 문서 §4 모델 고정 — 변경 시 실험 전체 재실행 (§8)
_MAX_TOKENS  = 32000                 # 청크당 응답 상한 (레코드 에코 스키마 기준 여유치)

_ZERO_USAGE = {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0, "calls": 0}


def _get_backend(state: dict) -> str:
    backend = state.get("llm_backend") or os.environ.get("DQ_LLM_BACKEND", "cli")
    if backend not in ("cli", "api"):
        raise ValueError(f"지원하지 않는 llm_backend: {backend} (cli | api)")
    return backend


# ── 응답 파싱 공통 ─────────────────────────────────────────────────────────────
def _parse_response_text(text: str) -> dict:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    return json.loads(text)


# ── API 백엔드 (Anthropic SDK — 본실험용) ─────────────────────────────────────
_api_client = None


def _call_claude_api_once(user_prompt: str) -> tuple:
    global _api_client
    import anthropic
    if _api_client is None:
        _api_client = anthropic.Anthropic()   # ANTHROPIC_API_KEY 사용 (api 백엔드만)

    # 시스템 프롬프트에 캐시 브레이크포인트 — 청크 간 반복분 비용 절감
    with _api_client.messages.stream(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=0,                        # 04 문서 §4 요건 (CLI로는 미제어)
        system=[{
            "type": "text",
            "text": _SYSTEM_INSTRUCTIONS,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        msg = stream.get_final_message()

    if msg.stop_reason == "max_tokens":
        raise RuntimeError(f"응답이 max_tokens({_MAX_TOKENS})에서 잘림 — 청크 축소 필요")

    u = msg.usage
    usage = {
        "input":          u.input_tokens,
        "output":         u.output_tokens,
        "cache_creation": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read":     getattr(u, "cache_read_input_tokens", 0) or 0,
        "model":          msg.model,
    }
    text = "".join(b.text for b in msg.content if b.type == "text")
    return _parse_response_text(text), usage


# ── CLI 백엔드 (Claude CLI + OAuth — 개발/스모크용) ───────────────────────────
def _call_claude_once(prompt: str) -> tuple:
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="dq2b_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with open(tmp_path, "rb") as stdin_file:
            result = subprocess.run(
                ["claude", "--print", "--model", _MODEL, "--output-format", "json"],
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
    model_usage = cli_data.get("modelUsage")
    if isinstance(model_usage, dict) and model_usage:
        usage["model"] = next(iter(model_usage))

    return _parse_response_text(cli_data.get("result", "")), usage


def _call_llm(user_prompt: str, backend: str) -> tuple:
    """백엔드 라우팅 + 재시도. CLI는 시스템 프롬프트를 본문에 결합해 전달 (stdin 단일 블롭)."""
    for attempt in range(_MAX_RETRY + 1):
        try:
            if backend == "api":
                return _call_claude_api_once(user_prompt)
            return _call_claude_once(_SYSTEM_INSTRUCTIONS + "\n\n---\n\n" + user_prompt)
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

    # 반환값은 user 파트만 — CLI는 _call_llm에서 시스템 프롬프트를 앞에 결합,
    # API는 system 역할로 분리 전달 (내용은 두 백엔드 동일)
    return (
        "## 이상치 필드 프로파일\n"
        + _profile_summary(profile, outlier_fields)
        + "\n\n## 관련 규칙 위반\n"
        + viol_text
        + f"\n\n## 검토 레코드 ({len(records)}건) — Stage 2A 처리 완료 상태\n"
        + json.dumps(records, ensure_ascii=False, indent=2, default=str)
        + "\n\n위 레코드의 이상치를 검토하고 결과를 JSON으로 반환하세요."
    )


# ── 청크 처리 (병렬) ──────────────────────────────────────────────────────────
def _process_chunk(args: tuple) -> tuple:
    chunk, orig_indices, profile, violations, label, backend = args
    prompt = _build_prompt(profile, violations, chunk)
    result, usage = _call_llm(prompt, backend)

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

    backend = _get_backend(state)
    print(f"[Stage2B-Claude] 모호성 판단 시작 — {len(ambiguous_idx)}건 대상 (백엔드: {backend})")

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
        chunks_args.append((chunk, orig_idx, state["profile"], state["rule_violations"], label, backend))

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
        if usage.get("model") and "model" not in usage_total:
            usage_total["model"] = usage["model"]
    usage_total["backend"] = backend

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
