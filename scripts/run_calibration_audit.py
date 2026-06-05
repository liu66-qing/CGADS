"""Audit the gold-standard calibration JSONL dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.calibration import audit_cases, load_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit gold-standard calibration cases.")
    parser.add_argument(
        "--path",
        default="data/calibration/gold_standard_v1.jsonl",
        help="Path to the JSONL calibration dataset.",
    )
    parser.add_argument("--strict30", action="store_true", help="Require final 30-case distribution.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable audit report.")
    args = parser.parse_args()

    cases = load_jsonl(Path(args.path))
    report = audit_cases(cases, strict30=args.strict30)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"passed: {report.passed}")
        print(f"cases: {report.total_cases}")
        print(f"status: {dict(report.status_distribution)}")
        print(f"task: {dict(report.task_distribution)}")
        print(f"persona: {dict(report.persona_distribution)}")
        print(f"boundary: {dict(report.boundary_distribution)}")
        print(f"p0_rules: {dict(report.p0_rule_distribution)}")
        print(f"p1_rules: {dict(report.p1_rule_distribution)}")
        if report.issues:
            print("issues:")
            for issue in report.issues:
                print(f"  [{issue.level}] {issue.case_id}: {issue.message}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
