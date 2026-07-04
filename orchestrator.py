"""
DQ Multi-Agent Orchestrator — LCEL 파이프라인 정의

기본 경로(A5): Stage 1 → 2A → 2B → (3A ‖ 3B) → 4

구성(--config, 04 문서 §4):
  A1: Profiler + 2A                 (LLM 없음)
  A2: Profiler + 2B 전 레코드        (2A 우회 — 공정성 프로토콜)
  A3: Profiler + 2A + 2B(선택 호출)
  A4: A3 + 3A Validator
  A5: A4 + 3B HC (전체)

실패 정책 (05 문서 §2.1): 스테이지 예외는 state["stage_errors"]에 기록 후
후속 스테이지 진행 (부분 결과 보존). Stage 1 실패만 치명(fatal)으로 중단.
"""
from dotenv import load_dotenv
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

load_dotenv()

VALID_CONFIGS = ("A1", "A2", "A3", "A4", "A5")

_SKIP_3A_RESULT = {
    "issues":        [],
    "overall_score": None,
    "summary":       "OpenAI 검증 건너뜀",
}


def _safe_stage(fn, stage_name: str):
    """스테이지 예외를 stage_errors로 기록하고 상태를 그대로 통과시키는 래퍼"""
    def wrapped(state: dict) -> dict:
        try:
            return fn(state)
        except Exception as e:
            print(f"[Orchestrator] {stage_name} 실패 — 기록 후 계속: {e}")
            errors = list(state.get("stage_errors", []))
            errors.append({"stage": stage_name, "error": str(e), "fatal": False})
            return {**state, "stage_errors": errors}
    return RunnableLambda(wrapped)


def _safe_parallel(fn, stage_name: str, default: dict):
    """RunnablePassthrough.assign 내부용 — 예외 시 기본값 반환 (+오류 마커)"""
    def wrapped(state: dict) -> dict:
        try:
            return fn(state)
        except Exception as e:
            print(f"[Orchestrator] {stage_name} 실패 — 기본값으로 계속: {e}")
            return {**default, "stage_error": {"stage": stage_name, "error": str(e), "fatal": False}}
    return RunnableLambda(wrapped)


def _collect_parallel_meta(state: dict) -> dict:
    """3A/3B 병렬 실행의 오류 마커 → stage_errors, usage → token_usage로 승격"""
    errors = list(state.get("stage_errors", []))
    token_usage = dict(state.get("token_usage", {}))
    for key in ("stage3a", "stage3b"):
        sub = state.get(key) or {}
        if sub.get("stage_error"):
            errors.append(sub["stage_error"])
        if sub.get("usage"):
            token_usage[key] = sub["usage"]
    return {**state, "stage_errors": errors, "token_usage": token_usage}


def _route_all_to_2b(state: dict) -> dict:
    """A2: 2A를 우회하고 전 레코드를 2B로 라우팅 (원본 그대로 전달)"""
    all_records = [r for batch in state["data"] for r in batch]
    print(f"[Orchestrator] A2 모드 — 2A 우회, 전 레코드 {len(all_records)}건을 2B로 라우팅")
    return {
        **state,
        "original_records":  all_records,
        "preprocessed_data": list(all_records),
        "changelog":         [],
        "interpretations":   [],
        "ambiguous_indices": list(range(len(all_records))),
    }


def build_pipeline(config: str = "A5", skip_openai: bool = False):
    from agents.stage1_duckdb_agent      import stage1_duckdb_agent
    from agents.stage2a_deterministic    import stage2a_deterministic
    from agents.stage2b_claude_agent     import stage2b_claude_agent
    from agents.stage3b_numerical_agent  import stage3b_numerical_agent
    from agents.stage4_report_agent      import stage4_report_agent

    if config not in VALID_CONFIGS:
        raise ValueError(f"config는 {VALID_CONFIGS} 중 하나여야 합니다: {config}")

    use_2a_route = config != "A2"          # A2만 2A 우회
    use_2b       = config != "A1"
    use_3a       = config in ("A4", "A5") and not skip_openai
    use_3b       = config == "A5"

    # Stage 1은 fatal — 래핑하지 않음 (입력 없이는 어떤 부분 결과도 무의미)
    # stage1은 자신의 출력만 반환하므로 실험 제어 키(config, run_meta)를 여기서 보존
    def _stage1_carry(inputs: dict) -> dict:
        out   = stage1_duckdb_agent.func(inputs)
        carry = {k: inputs[k] for k in ("config", "run_meta") if k in inputs}
        return {**out, **carry}

    chain = RunnableLambda(_stage1_carry)

    if use_2a_route:
        chain = chain | _safe_stage(stage2a_deterministic.func, "stage2a")
    else:
        chain = chain | RunnableLambda(_route_all_to_2b)

    if use_2b:
        chain = chain | _safe_stage(stage2b_claude_agent.func, "stage2b")

    if use_3a or use_3b:
        if use_3a:
            from agents.stage3a_openai_judge import stage3a_openai_judge
            stage3a = _safe_parallel(stage3a_openai_judge.func, "stage3a", dict(_SKIP_3A_RESULT))
        else:
            stage3a = RunnableLambda(lambda _: dict(_SKIP_3A_RESULT))
        assigns = {"stage3a": stage3a}
        if use_3b:
            assigns["stage3b"] = _safe_parallel(
                stage3b_numerical_agent.func, "stage3b", {"summary": {}}
            )
        chain = chain | RunnablePassthrough.assign(**assigns) | RunnableLambda(_collect_parallel_meta)

    return chain | _safe_stage(stage4_report_agent.func, "stage4")


def run(
    file_path: str,
    batch_size: int = 500,
    skip_openai: bool = False,
    config: str = "A5",
    run_meta: dict = None,
) -> dict:
    pipeline = build_pipeline(config=config, skip_openai=skip_openai)
    initial = {
        "file_path":  file_path,
        "batch_size": batch_size,
        "config":     config,
    }
    if run_meta:
        initial["run_meta"] = run_meta
    return pipeline.invoke(initial)
