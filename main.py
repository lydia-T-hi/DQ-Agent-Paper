#!/usr/bin/env python3
"""
DQ Multi-Agent Pipeline — CLI 진입점
Usage:
  python main.py <file_path> [--batch-size N] [--skip-openai]
"""
import argparse
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

GRADE_LABEL = {"A": "우수", "B": "양호", "C": "주의", "D": "위험"}


def check_env(skip_openai: bool) -> list:
    missing = []
    if not skip_openai and not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    return missing


def main():
    parser = argparse.ArgumentParser(
        description="DQ Multi-Agent Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py sample_input.csv\n"
            "  python main.py data.jsonl --batch-size 100\n"
            "  python main.py data.csv --skip-openai\n"
        ),
    )
    parser.add_argument("file_path", help="입력 파일 (csv/jsonl/parquet/xlsx 등)")
    parser.add_argument("--batch-size", type=int, default=500, metavar="N",
                        help="배치 크기 (기본: 500)")
    parser.add_argument("--skip-openai", action="store_true",
                        help="Stage 3A OpenAI 판단 건너뜀 (API 키 없을 때)")
    parser.add_argument("--config", default="A5", choices=["A1", "A2", "A3", "A4", "A5"],
                        help="실험 구성 (04 문서 §4, 기본: A5 전체 파이프라인)")
    args = parser.parse_args()

    # 파일 확인
    if not os.path.exists(args.file_path):
        print(f"[ERROR] 파일 없음: {args.file_path}")
        sys.exit(1)

    # API 키 확인 (3A를 쓰지 않는 구성이면 OpenAI 키 불필요)
    needs_openai = args.config in ("A4", "A5") and not args.skip_openai
    missing = check_env(skip_openai=not needs_openai)
    if missing:
        print(f"[ERROR] .env에 누락된 키: {', '.join(missing)}")
        print("  --skip-openai 옵션을 사용하면 OpenAI 없이 실행 가능합니다.")
        sys.exit(1)

    print()
    print("=" * 64)
    print("  DQ Multi-Agent Pipeline")
    print(f"  파일     : {args.file_path}")
    print(f"  배치크기 : {args.batch_size}")
    print(f"  구성     : {args.config}")
    print(f"  OpenAI   : {'사용' if needs_openai else '건너뜀'}")
    print("=" * 64)
    print()

    import orchestrator

    t0 = time.time()
    try:
        result = orchestrator.run(
            file_path=args.file_path,
            batch_size=args.batch_size,
            skip_openai=args.skip_openai,
            config=args.config,
        )
    except FileNotFoundError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 파이프라인 실행 중 오류: {e}")
        raise

    elapsed = round(time.time() - t0, 1)
    scores  = result.get("scores", {})
    grade   = result.get("grade", "?")
    cs      = result.get("consensus_summary", {})

    print()
    print("=" * 64)
    print("  완료")
    print(f"  소요 시간    : {elapsed}초")
    print(f"  최종 DQ 점수 : {scores.get('weighted_final', '?')}/100"
          f"  [{grade}등급 — {GRADE_LABEL.get(grade, '?')}]")
    print(f"  Critical     : {cs.get('critical_fields', 0)}개 필드")
    print(f"  Warning      : {cs.get('warning_fields', 0)}개 필드")
    print(f"  보고서       : {result.get('output_path')}")
    print("=" * 64)
    print()


if __name__ == "__main__":
    main()
