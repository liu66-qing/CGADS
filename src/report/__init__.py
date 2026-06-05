"""Evidence-chain report generation."""

from .gold_report import (
    build_case_markdown,
    build_dataset_markdown,
    build_dataset_summary,
    write_gold_report,
)

__all__ = [
    "build_case_markdown",
    "build_dataset_markdown",
    "build_dataset_summary",
    "write_gold_report",
]
