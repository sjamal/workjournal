#!/usr/bin/env python3

"""Build a local HTML page of ServiceNow JSON export links for one month.

Purpose:
- Write compilation/servicenow_export_YYYY-MM.html with one-click JSONv2 download links
    for incidents, change requests, journal entries, and mentions involving the signed-in user.
- Open the page in a browser already signed in to ServiceNow and save each download
    into incidents/ with the filename shown, then run merge_servicenow_exports.py.

How to run:
- ./venv/bin/python scripts/servicenow_export_links.py --month 2026-09
"""

from __future__ import annotations

import argparse
import calendar
import html
import os
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "compilation"
ME = "javascript:gs.getUserID()"


def build_links(month: str) -> list[tuple[str, str, str, str]]:
    year, mon = (int(x) for x in month.split("-"))
    last_day = calendar.monthrange(year, mon)[1]
    start = f"javascript:gs.dateGenerate('{month}-01','00:00:00')"
    end = f"javascript:gs.dateGenerate('{month}-{last_day:02d}','23:59:59')"
    open_in_month = f"opened_at<={end}^closed_at>={start}^ORclosed_atISEMPTY"
    return [
        (
            "1. Incidents involving me (open during the month)",
            f"sn_incidents_{month}.json",
            "incident",
            f"{open_in_month}^assigned_to={ME}^ORopened_by={ME}^ORcaller_id={ME}^ORwatch_listLIKE{ME}^ORwork_notes_listLIKE{ME}",
        ),
        (
            "1b. Fallback if #1 errors or is empty: incidents without watch-list conditions",
            f"sn_incidents_{month}.json",
            "incident",
            f"{open_in_month}^assigned_to={ME}^ORopened_by={ME}^ORcaller_id={ME}",
        ),
        (
            "2. Change requests involving me (open during the month)",
            f"sn_changes_{month}.json",
            "change_request",
            f"{open_in_month}^assigned_to={ME}^ORopened_by={ME}^ORrequested_by={ME}^ORwatch_listLIKE{ME}",
        ),
        (
            "2b. Fallback if #2 errors or is empty: changes without watch-list condition",
            f"sn_changes_{month}.json",
            "change_request",
            f"{open_in_month}^assigned_to={ME}^ORopened_by={ME}^ORrequested_by={ME}",
        ),
        (
            "3. My comments and work notes (may be restricted)",
            f"sn_journal_{month}.json",
            "sys_journal_field",
            f"sys_created_by=javascript:gs.getUserName()^sys_created_onBETWEEN{start}@{end}^nameINincident,change_request",
        ),
        (
            "4. @mentions of me (optional, may be restricted)",
            f"sn_mentions_{month}.json",
            "live_notification",
            f"user={ME}^sys_created_onBETWEEN{start}@{end}",
        ),
    ]


def build_page(month: str, instance: str) -> str:
    base = f"https://{instance}.service-now.com"
    lines = [
        f"<html><head><meta charset='utf-8'><title>ServiceNow {month} export</title></head>",
        "<body style='font-family:sans-serif;max-width:900px'>",
        f"<h2>ServiceNow export – {month}</h2>",
        "<p>Sign in to ServiceNow first. For each link: open it, then save the page (Cmd+S, format: Page Source) "
        "into <code>workjournal/incidents/</code> with the filename shown. If your browser shows a download prompt "
        "instead, save it with that name.</p>",
        "<p>Then run <code>./venv/bin/python scripts/merge_servicenow_exports.py --month "
        f"{month}</code> (the monthly orchestrator does this automatically).</p>",
        "<ol style='list-style:none;padding:0'>",
    ]
    for title, filename, table, query in build_links(month):
        q = quote(query, safe="")
        json_url = html.escape(f"{base}/{table}.do?JSONv2&sysparm_query={q}")
        list_url = html.escape(f"{base}/{table}_list.do?sysparm_query={q}")
        lines.append(
            f"<li style='margin:1em 0'><b>{title}</b><br>Save as <code>{filename}</code><br>"
            f"<a href='{json_url}'>Download JSON</a> &nbsp;|&nbsp; "
            f"<a href='{list_url}'>Open as list (to preview, or Export → JSON/CSV)</a></li>"
        )
    lines.append("</ol></body></html>")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ServiceNow export link page for one month")
    parser.add_argument("--month", required=True, help="Month scope in YYYY-MM")
    parser.add_argument("--instance", default=os.getenv("SN_INSTANCE", ""), help="ServiceNow instance name")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.instance:
        print("[X] Missing ServiceNow instance: set SN_INSTANCE in .env or pass --instance")
        return 1
    OUTPUT_DIR.mkdir(exist_ok=True)
    out = OUTPUT_DIR / f"servicenow_export_{args.month}.html"
    out.write_text(build_page(args.month, args.instance), encoding="utf-8")
    print(f"[✓] ServiceNow export links written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
