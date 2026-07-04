"""
Stage 2A: 결정론적 정규화 (LLM 불필요, 밀리초 처리)

LLM 없이 Python 규칙으로 처리 가능한 DQ 이슈를 즉시 수정합니다.
  - 이름: 소문자 → Title Case
  - 이메일: 형식 오류 → null
  - 날짜: 미래 날짜 → null
  - 나이: 범위 오류 → null / null이면 birth_date에서 계산
  - 금액: 음수 → null
  - 국가코드: 명백히 잘못된 코드 → null

처리 후에도 남는 모호 레코드는 ambiguous_indices에 기록되어 Stage 2B(Claude)로 전달됩니다.

ambiguous 판정 기준 (05 문서 §2.3):
  1. 강건 통계 이상치 — 중앙값/MAD 기반 수정 Z-score > 3.5 (Iglewicz & Hoaglin).
     평균/표준편차 대신 중앙값/MAD를 쓰는 이유: 극단 오염값이 평균·표준편차를
     부풀려 자기 자신의 Z-score를 낮추는 마스킹(masking)을 방지 (오염 데이터 전제)
  2. 교차필드 충돌 — 선행일(가입 등) > 후행일(최근구매 등) 날짜쌍 모순
"""
import math
import re
import statistics
from datetime import date, datetime

from langchain_core.runnables import RunnableLambda

# ISO 3166-1 alpha-2 중 명백히 잘못된/더미 코드 집합
_INVALID_COUNTRY_CODES = {"ZZ", "XX", "AA", "QQ", "00", "NA", "NN", "TT"}


# ── 유틸 ──────────────────────────────────────────────────────────────────────
def _is_null(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def _action_type(orig, new_val) -> str:
    if _is_null(orig) and not _is_null(new_val):
        return "fill"
    if not _is_null(orig) and _is_null(new_val):
        return "flag"
    return "normalize"


def _entry(idx, field, orig, new_val, reason) -> dict:
    return {
        "record_index": idx,
        "field":        field,
        "action":       _action_type(orig, new_val),
        "original":     orig,
        "new_value":    None if _is_null(new_val) else new_val,
        "reason":       reason,
        "stage":        "2a",
    }


# ── 필드별 처리 함수 ────────────────────────────────────────────────────────
def _proc_name(value):
    if not isinstance(value, str) or not value.strip():
        return value, None
    if value == value.lower():
        return value.title(), "소문자 이름 → Title Case 정규화"
    return value, None


def _proc_email(value):
    if _is_null(value):
        return None, None
    s = str(value).strip()
    if "@" not in s or len(s) < 5 or s.startswith("@") or s.endswith("@"):
        return None, f"이메일 형식 오류 ('{s}') → null"
    return value, None


def _proc_date(value):
    if _is_null(value):
        return None, None
    try:
        d = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
        if d > date.today():
            return None, f"미래 날짜 ({value}) → null"
    except Exception:
        pass
    return value, None


def _fill_age_from_birth(record: dict):
    birth_field = next(
        (f for f in record if any(k in f.lower() for k in ("birth", "dob", "born"))),
        None,
    )
    if not birth_field or _is_null(record.get(birth_field)):
        return None, None
    try:
        bd = datetime.strptime(str(record[birth_field])[:10], "%Y-%m-%d").date()
        today = date.today()
        if bd > today:
            return None, None
        age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        if 0 <= age <= 150:
            return float(age), f"{birth_field}({record[birth_field]}) 기준 나이 {age}세 계산"
    except Exception:
        pass
    return None, None


def _proc_age(value, record: dict):
    if _is_null(value):
        filled, reason = _fill_age_from_birth(record)
        return filled, reason
    try:
        age = float(value)
        if age < 0 or age > 150:
            return None, f"나이 범위 오류 ({value}, 유효: 0~150) → null"
    except Exception:
        pass
    return value, None


def _proc_amount(value):
    if _is_null(value):
        return None, None
    try:
        if float(value) < 0:
            return None, f"음수 금액 ({value}) → null"
    except Exception:
        pass
    return value, None


def _proc_country(value):
    if _is_null(value):
        return None, None
    s = str(value).strip().upper()
    if not s.isalpha() or len(s) != 2 or s in _INVALID_COUNTRY_CODES:
        return None, f"유효하지 않은 국가코드 ('{value}') → null"
    return value, None


# ── 레코드 처리 ──────────────────────────────────────────────────────────────
def _process_record(idx: int, record: dict, profile: dict) -> tuple:
    """단일 레코드 결정론적 처리.
    반환: (new_record, changelog_entries, is_ambiguous)
    """
    new_rec = dict(record)
    entries = []

    for field, value in record.items():
        flow    = field.lower()
        new_val = value
        reason  = None

        if "name" in flow and not any(k in flow for k in ("username", "domain", "file")):
            new_val, reason = _proc_name(value)

        elif any(k in flow for k in ("email", "mail")):
            new_val, reason = _proc_email(value)

        elif any(k in flow for k in ("date", "birth", "dob", "born")):
            new_val, reason = _proc_date(value)

        elif "age" in flow:
            new_val, reason = _proc_age(value, record)

        elif any(k in flow for k in ("salary", "price", "amount", "cost", "pay", "fee", "wage")):
            new_val, reason = _proc_amount(value)

        elif any(k in flow for k in ("country", "nation", "region")):
            new_val, reason = _proc_country(value)

        if reason is not None:
            new_rec[field] = None if _is_null(new_val) else new_val
            entries.append(_entry(idx, field, value, new_val, reason))

    return new_rec, entries


# ── 모호성 판정 (05 §2.3) ────────────────────────────────────────────────────
_MAD_Z_THRESHOLD = 3.5          # Iglewicz & Hoaglin (1993) 권장 임계값
_DATE_RE         = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _numeric_field_stats(records: list) -> dict:
    """처리 후 값 기준 필드별 (median, MAD).
    평균/표준편차가 아닌 강건 통계를 쓰는 이유: 오염 극단값의 자기 마스킹 방지."""
    cols: dict = {}
    for rec in records:
        for f, v in rec.items():
            if isinstance(v, bool) or _is_null(v) or not isinstance(v, (int, float)):
                continue
            cols.setdefault(f, []).append(float(v))

    stats = {}
    for f, vals in cols.items():
        if len(vals) < 8:               # 표본이 너무 적으면 통계 판정 생략
            continue
        med = statistics.median(vals)
        mad = statistics.median(abs(x - med) for x in vals)
        if mad > 0:                     # MAD=0(과반 동일값) 필드는 판정 제외
            stats[f] = (med, mad)
    return stats


def _find_date_pair(records: list):
    """(선행일, 후행일) 날짜 컬럼쌍 휴리스틱 — 없으면 None"""
    if not records:
        return None
    sample = records[: min(50, len(records))]
    date_cols = [
        c for c in records[0].keys()
        if any(isinstance(r.get(c), str) and _DATE_RE.match(r[c]) for r in sample)
    ]
    starts = [c for c in date_cols if any(k in c.lower() for k in ("signup", "join", "start", "가입"))]
    ends   = [c for c in date_cols if any(k in c.lower() for k in ("last", "end", "purchase", "구매", "최근"))]
    return (starts[0], ends[0]) if starts and ends else None


def _is_ambiguous(rec: dict, stats: dict, date_pair) -> bool:
    for f, (med, mad) in stats.items():
        v = rec.get(f)
        if _is_null(v) or isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if 0.6745 * abs(float(v) - med) / mad > _MAD_Z_THRESHOLD:
            return True

    if date_pair:
        sv, ev = rec.get(date_pair[0]), rec.get(date_pair[1])
        if (isinstance(sv, str) and isinstance(ev, str)
                and _DATE_RE.match(sv) and _DATE_RE.match(ev) and sv > ev):
            return True
    return False


# ── 스테이지 실행 ─────────────────────────────────────────────────────────────
def _run(state: dict) -> dict:
    print("[Stage2A-Det] 결정론적 정규화 시작")

    all_records     = [r for batch in state["data"] for r in batch]
    profile         = state["profile"]

    processed       = []
    changelog: list = []

    for i, record in enumerate(all_records):
        new_rec, entries = _process_record(i, record, profile)
        processed.append(new_rec)
        changelog.extend(entries)

    # 모호성 판정은 처리 후 전체 분포 기준으로 일괄 수행 (강건 통계 + 교차필드)
    stats     = _numeric_field_stats(processed)
    date_pair = _find_date_pair(processed)
    ambiguous_idx = [
        i for i, rec in enumerate(processed) if _is_ambiguous(rec, stats, date_pair)
    ]

    print(
        f"[Stage2A-Det] 완료 — 변경 {len(changelog)}건 / "
        f"이상치(2B 대상) {len(ambiguous_idx)}건"
    )

    return {
        **state,
        "original_records":  all_records,
        "preprocessed_data": processed,
        "changelog":         changelog,
        "interpretations":   [],
        "ambiguous_indices": ambiguous_idx,
    }


stage2a_deterministic = RunnableLambda(_run)
