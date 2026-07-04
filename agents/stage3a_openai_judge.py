"""
Stage 3A: OpenAI — 의미 기반 DQ Judge (이종 모델 교차검증)
Claude(2B)와 독립적 관점으로 데이터 품질을 판단합니다.
RunnableParallel에서 호출되므로 state를 받아 자신의 판단 결과만 반환합니다.

계측·입력 정책:
  - 토큰 계측 지점 ② (CostMeter): usage_metadata를 반환 dict의 "usage"로 전달,
    orchestrator가 state["token_usage"]["stage3a"]로 승격. 계측 실패 = 실행 실패.
  - 대용량 입력 샘플링: 전 레코드를 보내면 컨텍스트 초과 → changelog가 손댄
    레코드 우선 + 앞에서부터 채워 최대 _MAX_RECORDS건 (결정론적 — 무작위 없음)
"""
import json
import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI

load_dotenv()

_MODEL       = "gpt-4o"   # 04 문서 §4 모델 고정 (Validator)
_MAX_RECORDS = 80         # 샘플 상한 — 프롬프트 크기·비용 통제 (결정론적 선택)

_SYSTEM = """\
당신은 데이터 품질 검사 전문가입니다.
전처리된 데이터와 원본 통계 프로파일을 바탕으로 독립적인 DQ 판단을 수행합니다.

반드시 아래 JSON 형식으로만 응답하세요:
{
  "issues": [
    {
      "record_index": <정수 또는 null (전체 적용)>,
      "field": <필드명 또는 null>,
      "severity": "critical|warning|info",
      "issue_type": <문제 유형 예: "semantic_inconsistency", "domain_violation", "data_accuracy">,
      "description": <문제 설명>,
      "confidence": <0.0 ~ 1.0>
    }
  ],
  "overall_score": <0 ~ 100 정수, DQ 종합 점수>,
  "summary": <전반적인 데이터 품질 평가 한 문단>
}
"""

_HUMAN_TMPL = """\
## 원본 통계 프로파일
{profile_summary}

## 전처리된 데이터 표본 ({sampled}건 / 전체 {total}건 — 변경 이력 레코드 우선 표본)
{preprocessed_json}

## 규칙 기반 위반 참고 (DuckDB Stage 1 결과)
{violations_summary}

위 데이터의 의미 기반 품질을 독립적으로 판단하고 JSON으로 반환하세요.
record_index는 각 레코드의 "_idx" 값을 사용하세요.
"""


def _profile_summary(profile: dict) -> str:
    lines = []
    for field, p in profile.items():
        base = f"  {field}: null={p['null_pct']}%, distinct={p['distinct_count']}"
        if "avg" in p:
            base += f", range=[{p['min']}, {p['max']}]"
        lines.append(base)
    return "\n".join(lines)


def _violations_summary(violations: list) -> str:
    if not violations:
        return "  없음"
    return "\n".join(
        f"  [{v['severity'].upper()}] {v['field']}.{v['rule']}: {v['detail']}"
        for v in violations
    )


def _select_records(state: dict) -> list:
    """changelog가 손댄 레코드 우선 + 앞에서부터 순차 보충 (결정론적, 상한 _MAX_RECORDS)"""
    preprocessed = state.get("preprocessed_data", [])
    changed_idx = []
    seen = set()
    for entry in state.get("changelog", []):
        i = entry.get("record_index")
        if i is not None and i not in seen and 0 <= i < len(preprocessed):
            seen.add(i)
            changed_idx.append(i)

    selected = changed_idx[:_MAX_RECORDS]
    if len(selected) < _MAX_RECORDS:
        for i in range(len(preprocessed)):
            if i not in seen:
                selected.append(i)
                if len(selected) >= _MAX_RECORDS:
                    break

    # 원본 인덱스를 보존해 판단 결과의 record_index가 전역 인덱스가 되도록 함
    return [{"_idx": i, **preprocessed[i]} for i in sorted(selected)]


def _run(state: dict) -> dict:
    preprocessed = state.get("preprocessed_data", [])
    sampled = _select_records(state)
    print(f"[Stage3A-OpenAI] DQ 판단 시작 — 표본 {len(sampled)}건 / 전체 {len(preprocessed)}건")

    llm = ChatOpenAI(
        model=_MODEL,
        temperature=0,
        api_key=os.environ.get("OPENAI_API_KEY"),
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    human = _HUMAN_TMPL.format(
        profile_summary=_profile_summary(state["profile"]),
        preprocessed_json=json.dumps(sampled, ensure_ascii=False, indent=1, default=str),
        violations_summary=_violations_summary(state.get("rule_violations", [])),
        sampled=len(sampled),
        total=len(preprocessed),
    )

    msg = llm.invoke([SystemMessage(content=_SYSTEM), HumanMessage(content=human)])

    um = getattr(msg, "usage_metadata", None)
    if not um:
        # 비용 결측 데이터 금지 원칙 (05 §3.2)
        raise RuntimeError("Stage3A usage_metadata 없음 — 토큰 계측 불가로 실행 실패 처리")
    usage = {
        "input":  um.get("input_tokens", 0),
        "output": um.get("output_tokens", 0),
        "calls":  1,
        "model":  _MODEL,
    }

    result = json.loads(msg.content)
    issues = result.get("issues", [])
    score  = result.get("overall_score", 0)
    crit   = sum(1 for i in issues if i.get("severity") == "critical")
    warn   = sum(1 for i in issues if i.get("severity") == "warning")
    print(f"[Stage3A-OpenAI] 완료 — 이슈 {len(issues)}건 (C:{crit} W:{warn}), 점수 {score}, "
          f"토큰 {usage['input']:,}/{usage['output']:,}")

    return {
        "issues":        issues,
        "overall_score": score,
        "summary":       result.get("summary", ""),
        "sampled_records": len(sampled),
        "usage":         usage,
    }


stage3a_openai_judge = RunnableLambda(_run)
