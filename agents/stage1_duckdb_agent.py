"""
Stage 1: DuckDB — 데이터 입력 · 통계 프로파일링 · 규칙 기반 검증
"""
import json
import math
import os
import uuid
from datetime import datetime

import duckdb
import pandas as pd
from langchain_core.runnables import RunnableLambda

_DUCKDB_EXTS = {".csv", ".tsv", ".parquet", ".json", ".jsonl"}
_PANDAS_EXTS = {".xlsx", ".xls"}


def _reader_expr(path: str, ext: str) -> str:
    safe = path.replace("\\", "/").replace("'", "''")
    return {
        ".csv":     f"read_csv_auto('{safe}')",
        ".tsv":     f"read_csv_auto('{safe}', delim='\t')",
        ".parquet": f"read_parquet('{safe}')",
        ".json":    f"read_json_auto('{safe}')",
        ".jsonl":   f"read_json_auto('{safe}')",
    }[ext]


def _build_profile(conn, expr: str) -> tuple[dict, pd.DataFrame]:
    col_info = conn.execute(f"DESCRIBE SELECT * FROM {expr}").df()
    total    = conn.execute(f"SELECT COUNT(*) FROM {expr}").fetchone()[0]

    profile = {}
    for _, row in col_info.iterrows():
        col   = row["column_name"]
        dtype = str(row["column_type"])
        safe  = f'"{col}"'

        non_null, distinct = conn.execute(
            f"SELECT COUNT({safe}), COUNT(DISTINCT {safe}) FROM {expr}"
        ).fetchone()

        null_count = total - non_null
        p = {
            "type":           dtype,
            "total":          total,
            "null_count":     null_count,
            "null_pct":       round(null_count / total * 100, 1) if total else 0,
            "distinct_count": distinct,
        }

        is_num = (
            any(t == dtype.upper() or dtype.upper().startswith(t)
                for t in ["INTEGER", "BIGINT", "HUGEINT", "SMALLINT", "TINYINT",
                           "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL"])
            and "STRUCT" not in dtype.upper()
            and not dtype.endswith("[]")
        )
        if is_num and non_null > 0:
            mn, mx, avg, std = conn.execute(
                f"SELECT MIN({safe}), MAX({safe}), AVG({safe}), STDDEV({safe}) "
                f"FROM {expr} WHERE {safe} IS NOT NULL"
            ).fetchone()
            p.update({
                "min":    mn,
                "max":    mx,
                "avg":    round(float(avg), 2) if avg is not None else None,
                "stddev": round(float(std), 2) if std is not None else None,
            })

        try:
            tops = conn.execute(
                f"SELECT CAST({safe} AS VARCHAR) v, COUNT(*) c "
                f"FROM {expr} WHERE {safe} IS NOT NULL "
                f"GROUP BY {safe} ORDER BY c DESC LIMIT 3"
            ).df()
            p["top_values"] = tops["v"].tolist()
        except Exception:
            p["top_values"] = []

        profile[col] = p

    return profile, col_info


def _run_rules(conn, expr: str, profile: dict, col_info: pd.DataFrame) -> list:
    violations = []

    for _, row in col_info.iterrows():
        col   = row["column_name"]
        dtype = str(row["column_type"])
        clow  = col.lower()
        safe  = f'"{col}"'
        p     = profile[col]
        is_num = (
            any(t == dtype.upper() or dtype.upper().startswith(t)
                for t in ["INTEGER", "BIGINT", "HUGEINT", "SMALLINT", "TINYINT",
                           "FLOAT", "DOUBLE", "DECIMAL", "NUMERIC", "REAL"])
            and "STRUCT" not in dtype.upper()
            and not dtype.endswith("[]")
        )

        def add(rule, severity, count, detail, examples=None):
            violations.append({
                "field": col, "rule": rule, "severity": severity,
                "count": count, "detail": detail,
                "examples": [str(e) for e in (examples or [])],
            })

        def safe_exec(fn):
            try:
                return fn()
            except Exception:
                return None

        # R1: NULL 비율 > 30%
        if p["null_pct"] > 30:
            add("high_null_rate", "warning", p["null_count"],
                f"NULL {p['null_pct']}% (기준 30%)")

        # R2: 이메일 형식 오류
        if any(k in clow for k in ("email", "mail")):
            def r2():
                cnt = conn.execute(
                    f"SELECT COUNT(*) FROM {expr} "
                    f"WHERE {safe} IS NOT NULL AND CAST({safe} AS VARCHAR) != '' "
                    f"AND (POSITION('@' IN CAST({safe} AS VARCHAR)) = 0 "
                    f"     OR LENGTH(CAST({safe} AS VARCHAR)) < 5)"
                ).fetchone()[0]
                if cnt:
                    ex = conn.execute(
                        f"SELECT CAST({safe} AS VARCHAR) FROM {expr} "
                        f"WHERE {safe} IS NOT NULL AND CAST({safe} AS VARCHAR) != '' "
                        f"AND (POSITION('@' IN CAST({safe} AS VARCHAR)) = 0 "
                        f"     OR LENGTH(CAST({safe} AS VARCHAR)) < 5) LIMIT 3"
                    ).df().iloc[:, 0].tolist()
                    add("invalid_email", "critical", cnt, f"이메일 형식 오류 {cnt}건", ex)
            safe_exec(r2)

        # R3: 미래 날짜
        if any(k in clow for k in ("date", "birth", "dob", "born")):
            def r3():
                cnt = conn.execute(
                    f"SELECT COUNT(*) FROM {expr} "
                    f"WHERE {safe} IS NOT NULL "
                    f"AND TRY_CAST(CAST({safe} AS VARCHAR) AS DATE) > CURRENT_DATE"
                ).fetchone()[0]
                if cnt:
                    ex = conn.execute(
                        f"SELECT CAST({safe} AS VARCHAR) FROM {expr} "
                        f"WHERE {safe} IS NOT NULL "
                        f"AND TRY_CAST(CAST({safe} AS VARCHAR) AS DATE) > CURRENT_DATE LIMIT 3"
                    ).df().iloc[:, 0].tolist()
                    add("future_date", "critical", cnt, f"미래 날짜 {cnt}건", ex)
            safe_exec(r3)

        # R4: 유효하지 않은 나이
        if "age" in clow and is_num:
            def r4():
                cnt = conn.execute(
                    f"SELECT COUNT(*) FROM {expr} "
                    f"WHERE {safe} IS NOT NULL AND ({safe} < 0 OR {safe} > 150)"
                ).fetchone()[0]
                if cnt:
                    ex = conn.execute(
                        f"SELECT CAST({safe} AS VARCHAR) FROM {expr} "
                        f"WHERE {safe} IS NOT NULL AND ({safe} < 0 OR {safe} > 150) LIMIT 3"
                    ).df().iloc[:, 0].tolist()
                    add("invalid_age", "critical", cnt, f"나이 범위 오류 {cnt}건 (0~150 외)", ex)
            safe_exec(r4)

        # R5: 음수 금액
        if any(k in clow for k in ("salary", "price", "amount", "cost", "pay", "fee", "wage")) and is_num:
            def r5():
                cnt = conn.execute(
                    f"SELECT COUNT(*) FROM {expr} WHERE {safe} IS NOT NULL AND {safe} < 0"
                ).fetchone()[0]
                if cnt:
                    ex = conn.execute(
                        f"SELECT CAST({safe} AS VARCHAR) FROM {expr} "
                        f"WHERE {safe} IS NOT NULL AND {safe} < 0 LIMIT 3"
                    ).df().iloc[:, 0].tolist()
                    add("negative_amount", "critical", cnt, f"음수 금액 {cnt}건", ex)
            safe_exec(r5)

        # R6: 중복 ID
        if clow == "id" or clow.endswith("_id"):
            def r6():
                dup = conn.execute(
                    f"SELECT COUNT(*) FROM ("
                    f"  SELECT {safe}, COUNT(*) c FROM {expr} "
                    f"  WHERE {safe} IS NOT NULL GROUP BY {safe} HAVING c > 1)"
                ).fetchone()[0]
                if dup:
                    add("duplicate_id", "critical", dup, f"중복 ID {dup}개 값")
            safe_exec(r6)

        # R7: 통계적 이상치 (Z-score > 3)
        if is_num and p.get("stddev") and p["stddev"] > 0:
            def r7():
                cnt = conn.execute(
                    f"SELECT COUNT(*) FROM {expr} "
                    f"WHERE {safe} IS NOT NULL "
                    f"AND ABS(CAST({safe} AS DOUBLE) - {p['avg']}) / {p['stddev']} > 3"
                ).fetchone()[0]
                if cnt:
                    add("statistical_outlier", "info", cnt,
                        f"Z-score > 3 | avg={p['avg']} std={p['stddev']}")
            safe_exec(r7)

    # R8: 교차필드 일관성 — birth_date ↔ age (2년 이상 불일치)
    birth_col = next((c for c in profile if any(k in c.lower() for k in ("birth", "dob", "born"))), None)
    age_col   = next((c for c in profile if c.lower() == "age"), None)
    if birth_col and age_col:
        def r8():
            cnt = conn.execute(f"""
                SELECT COUNT(*) FROM {expr}
                WHERE "{birth_col}" IS NOT NULL
                  AND "{age_col}"   IS NOT NULL
                  AND TRY_CAST(CAST("{birth_col}" AS VARCHAR) AS DATE) IS NOT NULL
                  AND TRY_CAST(CAST("{birth_col}" AS VARCHAR) AS DATE) <= CURRENT_DATE
                  AND ABS(
                      CAST(DATE_DIFF('year',
                           TRY_CAST(CAST("{birth_col}" AS VARCHAR) AS DATE),
                           CURRENT_DATE) AS INTEGER)
                      - CAST("{age_col}" AS INTEGER)
                  ) > 2
            """).fetchone()[0]
            if cnt:
                violations.append({
                    "field":    f"{birth_col}+{age_col}",
                    "rule":     "cross_field_inconsistency",
                    "severity": "warning",
                    "count":    cnt,
                    "detail":   f"{birth_col}와 {age_col} 2년 이상 불일치 {cnt}건",
                    "examples": [],
                })
        try:
            r8()
        except Exception:
            pass

    return violations


def _load_json(conn, file_path: str) -> str:
    """JSON 파일을 Python으로 파싱해 DuckDB에 등록.
    최상위가 list이면 그대로, dict이면 list 값을 가진 키를 자동 탐색."""
    with open(file_path, encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        records = raw
    elif isinstance(raw, dict):
        records = None
        for key, val in raw.items():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                records = val
                print(f"[Stage1] 중첩 JSON 감지 — '{key}' 언래핑")
                break
        if records is None:
            records = [raw]
    else:
        raise ValueError("지원하지 않는 JSON 구조입니다.")

    df = pd.DataFrame(records)
    conn.register("_json_tbl", df)
    return "_json_tbl"


def _run(inputs: dict) -> dict:
    file_path   = os.path.abspath(inputs["file_path"])
    batch_size  = int(inputs.get("batch_size", 500))
    pipeline_id = inputs.get(
        "pipeline_id",
        f"run-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(uuid.uuid4())[:8]}",
    )

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"파일 없음: {file_path}")

    ext         = os.path.splitext(file_path)[1].lower()
    source_file = os.path.basename(file_path)

    if ext not in (_DUCKDB_EXTS | _PANDAS_EXTS):
        raise ValueError(f"지원하지 않는 형식: {ext}")

    print(f"[Stage1] 파일: {source_file}")
    conn = duckdb.connect()

    try:
        if ext in _PANDAS_EXTS:
            conn.register("_tbl", pd.read_excel(file_path))
            expr = "_tbl"
        elif ext == ".json":
            expr = _load_json(conn, file_path)
        else:
            expr = _reader_expr(file_path, ext)

        print("[Stage1] 프로파일 생성 중...")
        profile, col_info = _build_profile(conn, expr)
        total = profile[next(iter(profile))]["total"]

        print("[Stage1] 규칙 검증 중...")
        violations = _run_rules(conn, expr, profile, col_info)

        batch_count = math.ceil(total / batch_size)
        print(f"[Stage1] 배치 추출: {batch_count}개 × {batch_size}건")

        data = []
        for i in range(batch_count):
            df_b = conn.execute(
                f"SELECT * FROM {expr} LIMIT {batch_size} OFFSET {i * batch_size}"
            ).df()
            for c in df_b.select_dtypes(include=["datetime64[ns]"]).columns:
                df_b[c] = df_b[c].dt.strftime("%Y-%m-%d").where(df_b[c].notna(), None)
            data.append(df_b.where(pd.notnull(df_b), None).to_dict(orient="records"))

    finally:
        conn.close()

    crit = sum(1 for v in violations if v["severity"] == "critical")
    warn = sum(1 for v in violations if v["severity"] == "warning")
    info = sum(1 for v in violations if v["severity"] == "info")
    print(f"[Stage1] 완료 — 위반 {len(violations)}건 (C:{crit} W:{warn} I:{info})")

    return {
        "pipeline_id":     pipeline_id,
        "source_file":     source_file,
        "total_records":   total,
        "batch_count":     batch_count,
        "batch_size":      batch_size,
        "profile":         profile,
        "rule_violations": violations,
        "rule_summary":    {"total": len(violations), "critical": crit, "warning": warn, "info": info},
        "data":            data,
    }


stage1_duckdb_agent = RunnableLambda(_run)
