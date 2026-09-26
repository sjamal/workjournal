#!/usr/bin/env python3

"""Run monthly workjournal pipeline in one command.

Purpose:
- Execute cache imports/build steps in the right order.
- Support a default offline mode (no Outlook scrape).
- Optionally include direct Outlook scraping when requested.

How to run:
- ./venv/bin/python scripts/run_monthly_workjournal.py --month 2026-07
- ./venv/bin/python scripts/run_monthly_workjournal.py --month 2026-07 --include-outlook --summarize-screenshots
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def _run(cmd: list[str]) -> None:
    print("[RUN]", " ".join(cmd))
    subprocess.run(cmd, cwd=BASE_DIR, check=True)


def _days_for_month(month: str) -> int:
    year, mon = month.split("-")
    y = int(year)
    m = int(mon)
    if m == 12:
        next_y, next_m = y + 1, 1
    else:
        next_y, next_m = y, m + 1

    from datetime import date

    return (date(next_y, next_m, 1) - date(y, m, 1)).days


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run monthly workjournal workflow")
    parser.add_argument("--month", required=True, help="Month scope in YYYY-MM (example: 2026-07)")
    parser.add_argument("--include-outlook", action="store_true", help="Also run direct Outlook cache scrape")
    parser.add_argument("--summarize-screenshots", action="store_true", help="Run optional Ollama screenshot summarization")
    parser.add_argument("--force-screenshot-summaries", action="store_true", help="Force recompute screenshot summaries")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    days = _days_for_month(args.month)

    py = str(BASE_DIR / "venv" / "bin" / "python")
    if not Path(py).exists():
        print("[X] Missing interpreter at ./venv/bin/python")
        return 1

    try:
        _run([py, "scripts/import_email_analytics_reports.py"])
        _run([py, "scripts/fetch_tickets.py", "--month", args.month])
        _run([py, "scripts/summarize_transcripts.py"])

        if args.summarize_screenshots:
            cmd = [py, "scripts/summarize_screenshots.py", "--days", str(days)]
            if args.force_screenshot_summaries:
                cmd.append("--force")
            _run(cmd)

        if args.include_outlook:
            _run([py, "scripts/fetch_emails.py", "--days", str(days)])

        _run([py, "scripts/compile_dashboard.py", "--month", args.month])
        _run([py, "scripts/generate_journal.py", "--month", args.month])

        print("[✓] Monthly workjournal pipeline completed successfully.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"[X] Pipeline failed with exit code {exc.returncode}")
        return exc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
