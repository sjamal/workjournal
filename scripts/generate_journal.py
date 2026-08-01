#!/usr/bin/env python3

"""Generate non-interactive Markdown and legacy text exports from consolidated workjournal data.

Purpose:
- Produce compilation/confluence_markup.md without opening the dashboard UI.
- Use the same timeline sources as compile_dashboard.py for consistent output.

How to run:
- ./venv/bin/python scripts/generate_journal.py
- ./venv/bin/python scripts/generate_journal.py --days 31
"""

from __future__ import annotations

import argparse
import os

from compile_dashboard import build_confluence_rows, build_timeline

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_MD_FILE = os.path.join(BASE_DIR, "compilation", "confluence_markup.md")
OUTPUT_TEXT_FILE = os.path.join(BASE_DIR, "compilation", "confluence_markup.txt")


def _escape_markup_cell(value: str) -> str:
    compact = str(value).replace("\r", " ").replace("\n", " ").strip()
    return compact.replace("|", "\\|")


def _section_for_row(row: dict[str, str]) -> str:
    kind = str(row.get("kind", "")).strip()
    ref = str(row.get("ref", "")).strip()
    if kind == "ticket":
        return "Ticket Summary"
    if kind == "meeting":
        return "Meeting Minutes"
    if kind == "email-analytics":
        return "Email Analytics Daily Summary"
    if kind in {"screenshot", "note"}:
        return "Chronological Activity"
    if ref.startswith("Screenshot ("):
        return "Chronological Activity"
    if ref.startswith("Meeting:"):
        return "Meeting Minutes"
    if ref == "Email Analytics Summary":
        return "Email Analytics Daily Summary"
    return "Activity"


def generate_markup(days: int = 31, month: str | None = None) -> str:
    """Build README-style Markdown markup from consolidated timeline rows."""
    timeline = build_timeline(days, month=month)
    rows = build_confluence_rows(timeline)

    markup = ["# Work Journal"]
    current_day = ""
    current_section = ""
    for row in rows:
        date = _escape_markup_cell(row.get("date", ""))
        ref = _escape_markup_cell(row.get("ref", ""))
        url = str(row.get("url", "")).strip()
        if url:
            ref = f"[{ref}]({url})"
        summary = _escape_markup_cell(row.get("summary", ""))
        attachment = _escape_markup_cell(row.get("attachment", ""))
        if attachment:
            summary = f"!{attachment}! {summary}".strip()
        if not summary:
            continue

        if date != current_day:
            current_day = date
            current_section = ""
            markup.append(f"\n## {date}")

        section = _section_for_row(row)
        if section != current_section:
            current_section = section
            markup.append(f"### {section}")

        kind = str(row.get("kind", "")).strip()
        if kind == "ticket":
            markup.append(f"- {ref}: {summary}")
        elif kind in {"screenshot", "note"}:
            markup.append(f"- {ref}: {summary}")
        else:
            markup.append(f"- {summary}")

    return "\n".join(markup)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Markdown export files from local caches")
    parser.add_argument("--days", type=int, default=31, help="Lookback window in days (default: 31)")
    parser.add_argument("--month", default="", help="Optional month scope in YYYY-MM (example: 2026-07)")
    parser.add_argument("--output", default=OUTPUT_MD_FILE, help="Primary output markdown file path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    output = generate_markup(days=args.days, month=args.month or None)
    for target in (args.output, OUTPUT_TEXT_FILE):
        with open(target, "w", encoding="utf-8") as out_f:
            out_f.write(output)

    row_count = max(0, len(output.splitlines()) - 1)
    print(f"[✓] Markdown export written: {args.output}")
    print(f"[✓] Legacy text mirror written: {OUTPUT_TEXT_FILE}")
    print(f"[✓] Rows generated: {row_count}")


if __name__ == "__main__":
    main()
