#!/usr/bin/env python3

"""Import daily markdown artifacts from email-analytics into workjournal cache.

Purpose:
- Read `daily_YYYY-MM-DD.md` files from sibling email-analytics output.
- Build cache/email_analytics_daily_cache.json for dashboard and export workflows.

How to run:
- ./venv/bin/python scripts/import_email_analytics_reports.py
- ./venv/bin/python scripts/import_email_analytics_reports.py --source-dir ../email-analytics/output
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
CACHE_DIR = BASE_DIR / "cache"
CACHE_FILE = CACHE_DIR / "email_analytics_daily_cache.json"


def _default_source_dir() -> Path:
    # Assumes sibling repository layout: github/email-analytics and github/workjournal.
    return BASE_DIR.parent / "email-analytics" / "output"


def _extract_section(lines: list[str], header: str) -> list[str]:
    start = None
    end = None
    for i, line in enumerate(lines):
        if line.strip() == header:
            start = i + 1
            continue
        if start is not None and line.startswith("## "):
            end = i
            break
    if start is None:
        return []
    return lines[start:end] if end is not None else lines[start:]


def _extract_daily_summary(text: str) -> str:
    lines = text.splitlines()
    summary_lines = [x.strip() for x in _extract_section(lines, "## Summary") if x.strip().startswith("-")]
    action_lines = [x.strip() for x in _extract_section(lines, "## Action Required") if x.strip().startswith("-")]
    project_lines = [x.strip() for x in _extract_section(lines, "## Project Activity") if x.strip().startswith("-")]
    awareness_lines = [x.strip() for x in _extract_section(lines, "## Awareness") if x.strip().startswith("-")]

    # Keep all useful bullets, but deduplicate recurring alerts while preserving order.
    deduped_awareness = list(dict.fromkeys(awareness_lines))

    parts: list[str] = []
    if summary_lines:
        parts.append("Summary:")
        parts.extend(summary_lines)
    if action_lines:
        parts.append("Action Required:")
        parts.extend(action_lines)
    if project_lines:
        parts.append("Project Activity:")
        parts.extend(project_lines)
    if deduped_awareness:
        parts.append("Awareness:")
        parts.extend(deduped_awareness)

    if not parts:
        return ""
    return "\n".join(parts)


def import_daily_reports(source_dir: Path, pattern: str = "daily_*.md") -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    regex = re.compile(r"daily_(\d{4}-\d{2}-\d{2})\.md$")

    for path in sorted(source_dir.glob(pattern)):
        match = regex.search(path.name)
        if not match:
            continue
        date = match.group(1)
        text = path.read_text(encoding="utf-8", errors="ignore")
        summary = _extract_daily_summary(text)
        records.append(
            {
                "date": date,
                "source_file": str(path),
                "daily_summary": summary,
            }
        )

    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=str(_default_source_dir()))
    parser.add_argument("--pattern", default="daily_*.md")
    parser.add_argument("--output", default=str(CACHE_FILE))
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser()
    if not source_dir.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")

    records = import_daily_reports(source_dir, args.pattern)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote {output_path} ({len(records)} records)")


if __name__ == "__main__":
    main()
