#!/usr/bin/env python3

"""Fetch ticket activity from Azure DevOps and local ServiceNow export JSON.

Purpose:
- Build cache/work_items_cache.json consumed by compile_dashboard.py.
- Merge ADO API results with local incidents/incident.json or incidents/caller_history.json.

How to run:
- ./venv/bin/python scripts/fetch_tickets.py
- ./venv/bin/python scripts/fetch_tickets.py --days 31
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "work_items_cache.json")

ADO_ORG = os.getenv("ADO_ORG")
ADO_PROJECT = os.getenv("ADO_PROJECT")
ADO_PAT = os.getenv("ADO_PAT")
SN_INSTANCE = os.getenv("SN_INSTANCE")


def save_to_cache(data: list[dict]) -> None:
    """Persist combined ticket rows for dashboard consumption."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        print(f"[✓] Ticket cache written: {CACHE_FILE}")
    except Exception as exc:
        print(f"[X] Failed writing ticket cache: {exc}")


def _normalize_sn_value(value, default: str = "") -> str:
    if isinstance(value, dict):
        return str(value.get("display_value", value.get("value", default)))
    return str(value if value is not None else default)


def fetch_azure_devops(
    start_date: str,
    end_date: str | None = None,
    work_item_types: list[str] | None = None,
    all_project_items: bool = False,
) -> list[dict]:
    """Fetch Azure DevOps work items changed within an optional date window."""
    if not all([ADO_ORG, ADO_PROJECT, ADO_PAT]):
        print("[!] Skipping Azure DevOps: missing ADO_ORG/ADO_PROJECT/ADO_PAT in .env")
        return []

    print("[+] Fetching Azure DevOps work items...")
    auth_header = base64.b64encode(f":{ADO_PAT}".encode("utf-8")).decode("utf-8")
    headers = {"Authorization": f"Basic {auth_header}", "Content-Type": "application/json"}

    wiql_url = f"https://dev.azure.com/{ADO_ORG}/{ADO_PROJECT}/_apis/wit/wiql?api-version=7.1"
    type_clause = ""
    if work_item_types:
        quoted_types = ", ".join(f"'{item.replace(chr(39), chr(39) * 2)}'" for item in work_item_types)
        type_clause = f"AND [System.WorkItemType] IN ({quoted_types})"

    ownership_clause = "" if all_project_items else "AND ([System.AssignedTo] = @me OR [System.ChangedBy] = @me)"
    end_clause = f"AND [System.ChangedDate] < '{end_date}'" if end_date else ""
    query_payload = {
        "query": f"""
        SELECT [System.Id], [System.Title], [System.WorkItemType], [System.State], [System.ChangedDate]
        FROM WorkItems
        WHERE [System.AreaPath] UNDER '{ADO_PROJECT}'
          AND [System.ChangedDate] >= '{start_date}'
          {end_clause}
          {type_clause}
          {ownership_clause}
        ORDER BY [System.ChangedDate] DESC
        """
    }

    try:
        response = requests.post(wiql_url, json=query_payload, headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"[X] ADO query failed ({response.status_code}): {response.text}")
            return []

        refs = response.json().get("workItems", [])
        if not refs:
            print("[-] No recent Azure DevOps items found.")
            return []

        item_ids = [int(item["id"]) for item in refs]
        details_url = f"https://dev.azure.com/{ADO_ORG}/_apis/wit/workitemsbatch?api-version=7.1"
        details_response = requests.post(
            details_url,
            json={
                "ids": item_ids,
                "fields": [
                    "System.Id",
                    "System.Title",
                    "System.WorkItemType",
                    "System.State",
                    "System.ChangedDate",
                ],
            },
            headers=headers,
            timeout=30,
        )
        if details_response.status_code != 200:
            print(f"[!] ADO batch details request failed ({details_response.status_code}); retrying items individually")
            details = []
            for item_id in item_ids:
                single_url = f"https://dev.azure.com/{ADO_ORG}/_apis/wit/workitems/{item_id}?api-version=7.1"
                single_response = requests.get(single_url, headers=headers, timeout=30)
                if single_response.status_code == 200:
                    details.append(single_response.json())
                else:
                    print(f"[!] Skipping ADO work item {item_id} ({single_response.status_code})")
        else:
            details = details_response.json().get("value", [])

        parsed_items: list[dict] = []
        for item in details:
            fields = item.get("fields", {})
            parsed_items.append(
                {
                    "source": "Azure DevOps",
                    "id": str(item.get("id", "")),
                    "type": str(fields.get("System.WorkItemType", "")),
                    "title": str(fields.get("System.Title", "")),
                    "state": str(fields.get("System.State", "")),
                    "date_modified": str(fields.get("System.ChangedDate", "")),
                    "url": f"https://dev.azure.com/{ADO_ORG}/{ADO_PROJECT}/_workitems/edit/{item.get('id', '')}",
                }
            )
        print(f"[✓] Azure DevOps items: {len(parsed_items)}")
        return parsed_items
    except Exception as exc:
        print(f"[X] Exception while fetching Azure DevOps items: {exc}")
        return []


def _find_servicenow_export() -> str | None:
    for filename in ("incident.json", "caller_history.json"):
        path = os.path.join(BASE_DIR, "incidents", filename)
        if os.path.exists(path):
            return path
    return None


def _extract_records(data) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("result", "records", "rows"):
            if isinstance(data.get(key), list):
                return [x for x in data[key] if isinstance(x, dict)]
        if any(k in data for k in ("number", "sys_id", "short_description", "updated_at")):
            return [data]
        vals = [x for x in data.values() if isinstance(x, dict)]
        return vals
    return []


def fetch_servicenow() -> list[dict]:
    """Parse local ServiceNow export JSON from incidents/ folder."""
    export_file = _find_servicenow_export()
    if not export_file:
        print("[!] Skipping ServiceNow: incidents/incident.json or incidents/caller_history.json not found")
        return []

    print(f"[+] Parsing ServiceNow export: {os.path.basename(export_file)}")

    try:
        with open(export_file, "r", encoding="utf-8", errors="ignore") as f:
            data = json.load(f)
    except Exception as exc:
        print(f"[X] Could not parse ServiceNow export JSON: {exc}")
        return []

    records = _extract_records(data)
    if not records:
        print("[-] No ServiceNow records found in export.")
        return []

    parsed_tickets: list[dict] = []
    for record in records:
        ticket_id = _normalize_sn_value(record.get("number", record.get("id", "UNKNOWN")), "UNKNOWN")
        short_desc = _normalize_sn_value(
            record.get("short_description", record.get("title", record.get("description", "No Description"))),
            "No Description",
        )
        sys_id = _normalize_sn_value(record.get("sys_id", record.get("uid", "")), "")
        updated = _normalize_sn_value(
            record.get("sys_updated_on", record.get("updated_at", record.get("sys_created_on", "Unknown"))),
            "Unknown",
        )
        state = _normalize_sn_value(record.get("state", record.get("status", "Unknown")), "Unknown")

        url = ""
        if SN_INSTANCE and sys_id:
            url = f"https://{SN_INSTANCE}.service-now.com/{sys_id.lstrip('/')}"

        parsed_tickets.append(
            {
                "source": "ServiceNow (INC)",
                "id": ticket_id,
                "type": "Incident",
                "title": short_desc,
                "state": state,
                "date_modified": updated,
                "url": url,
            }
        )

    print(f"[✓] ServiceNow items: {len(parsed_tickets)}")
    return parsed_tickets


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch ADO and local ServiceNow ticket activity into cache")
    parser.add_argument("--days", type=int, default=31, help="Lookback window in days (default: 31)")
    parser.add_argument("--month", help="Exact month scope in YYYY-MM; overrides --days")
    parser.add_argument("--start-date", help="Inclusive ADO changed-date boundary in YYYY-MM-DD")
    parser.add_argument("--end-date", help="Exclusive ADO changed-date boundary in YYYY-MM-DD")
    parser.add_argument(
        "--work-item-types",
        help="Comma-separated ADO types to include, for example 'User Story,Task'",
    )
    parser.add_argument(
        "--all-project-items",
        action="store_true",
        help="Include all matching project items instead of only @me-assigned or @me-changed items",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.month:
        try:
            month_start = datetime.strptime(args.month, "%Y-%m-01")
        except ValueError as exc:
            raise SystemExit("--month must use YYYY-MM") from exc
        if month_start.month == 12:
            month_end = datetime(month_start.year + 1, 1, 1)
        else:
            month_end = datetime(month_start.year, month_start.month + 1, 1)
        start_date = month_start.strftime("%Y-%m-%d")
        end_date = month_end.strftime("%Y-%m-%d")
    else:
        start_date = args.start_date or (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")
        end_date = args.end_date

    work_item_types = [item.strip() for item in (args.work_item_types or "").split(",") if item.strip()]

    all_tickets: list[dict] = []
    all_tickets.extend(fetch_azure_devops(start_date, end_date, work_item_types, args.all_project_items))
    all_tickets.extend(fetch_servicenow())

    save_to_cache(all_tickets)


if __name__ == "__main__":
    main()
