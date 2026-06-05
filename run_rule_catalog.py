"""Export the canonical P0/P1 rule catalog."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.checkers import format_rule_catalog_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Export P0/P1 severity rule catalog.")
    parser.add_argument(
        "--output",
        default="experiments/reports/severity_rule_catalog.md",
        help="Markdown output path.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(format_rule_catalog_markdown(), encoding="utf-8")
    print(f"rule_catalog: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
