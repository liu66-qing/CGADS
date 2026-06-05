"""Generate an evidence-chain report for the gold calibration dataset."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.calibration import load_jsonl
from src.report import write_gold_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate calibration evidence-chain report.")
    parser.add_argument(
        "--path",
        default="data/calibration/gold_standard_v1.jsonl",
        help="Path to calibration JSONL.",
    )
    parser.add_argument(
        "--output-dir",
        default="experiments/reports",
        help="Directory for generated report files.",
    )
    parser.add_argument("--no-strict30", action="store_true", help="Skip strict 30-case audit.")
    args = parser.parse_args()

    cases = load_jsonl(Path(args.path))
    paths = write_gold_report(
        cases,
        output_dir=Path(args.output_dir),
        strict30=not args.no_strict30,
    )
    print(f"markdown: {paths['markdown']}")
    print(f"summary: {paths['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
