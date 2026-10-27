#!/usr/bin/env python3

"""Merge monthly ServiceNow JSON exports into incidents/incident.json.

Purpose:
- Combine incidents/sn_incidents_YYYY-MM*.json and sn_changes_YYYY-MM*.json from
    servicenow_export_links.py downloads.
- Keep only tickets with activity in the month (created, updated, resolved, closed,
    commented on by me, or mentioned me) and set sys_updated_on to the latest in-month
    activity so compile_dashboard.py places each ticket on that day.
- Print follow-up download links for tickets found only in journal/mention exports.

How to run:
- ./venv/bin/python scripts/merge_servicenow_exports.py --month 2026-09
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
INCIDENTS_DIR = BASE_DIR / "incidents"
DATE_FIELDS = ("sys_updated_on", "sys_created_on", "opened_at", "resolved_at", "closed_at")


def _load_records(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if isinstance(data, dict):
        for key in ("records", "result", "rows"):
            if isinstance(data.get(key), list):
                return data[key]
    return data if isinstance(data, list) else []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge monthly ServiceNow exports into incidents/incident.json")
    parser.add_argument("--month", required=True, help="Month scope in YYYY-MM")
    parser.add_argument("--incidents-dir", default=str(INCIDENTS_DIR))
    parser.add_argument("--instance", default=os.getenv("SN_INSTANCE", ""), help="ServiceNow instance name")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    folder = Path(args.incidents_dir)
    month = args.month

    ticket_files = sorted(folder.glob(f"sn_incidents_{month}*.json")) + sorted(folder.glob(f"sn_changes_{month}*.json"))
    if not ticket_files:
        print(f"[!] Skipping ServiceNow merge: no sn_incidents_{month}*.json or sn_changes_{month}*.json in {folder}")
        return 0

    tickets = [record for path in ticket_files for record in _load_records(path)]
    journal = _load_records(folder / f"sn_journal_{month}.json")
    mentions = _load_records(folder / f"sn_mentions_{month}.json")
    print(f"[+] Loaded {len(tickets)} tickets, {len(journal)} journal entries, {len(mentions)} mentions")

    extra_dates: dict[str, list[str]] = defaultdict(list)
    extra_tables: dict[str, str] = {}
    for entry in journal:
        extra_dates[entry.get("element_id", "")].append(entry.get("sys_created_on", ""))
        extra_tables[entry.get("element_id", "")] = entry.get("name", "incident")
    for note in mentions:
        extra_dates[note.get("document", "")].append(note.get("sys_created_on", ""))
        extra_tables[note.get("document", "")] = note.get("table", "incident")

    merged: dict[str, dict] = {}
    for ticket in tickets:
        sys_id = ticket.get("sys_id", "")
        dates = [ticket.get(field, "") for field in DATE_FIELDS] + extra_dates.get(sys_id, [])
        in_month = sorted(str(d) for d in dates if str(d).startswith(month))
        if not in_month:
            continue
        record = dict(ticket)
        record["sys_updated_on"] = in_month[-1]
        merged[sys_id] = record

    output = folder / "incident.json"
    output.write_text(json.dumps({"records": list(merged.values())}, indent=1), encoding="utf-8")
    print(f"[✓] Wrote {len(merged)} of {len(tickets)} tickets with {month} activity to {output}")

    missing: dict[str, list[str]] = defaultdict(list)
    for sys_id, table in extra_tables.items():
        if sys_id and sys_id not in merged and table in ("incident", "change_request"):
            missing[table].append(sys_id)
    for table, ids in missing.items():
        kind = "changes" if table == "change_request" else "incidents"
        query = quote("sys_idIN" + ",".join(ids), safe="")
        print(f"[!] {len(ids)} {table} records from journal/mentions are not in the exports.")
        print(f"    Save as sn_{kind}_{month}_extra.json and re-run:")
        print(f"    https://{args.instance or '<instance>'}.service-now.com/{table}.do?JSONv2&sysparm_query={query}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
