#!/usr/bin/env python3

"""Normalize ServiceNow incident export JSON into simple ticket objects.

Purpose:
- Parse incidents/incident.json or incidents/caller_history.json.
- Emit normalized ticket fields for quick inspection or downstream use.

How to run:
- ./venv/bin/python parse_sn_json.py
- ./venv/bin/python parse_sn_json.py --input incidents/caller_history.json --output cache/sn_parsed.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _unwrap(value, default: str = "") -> str:
    if isinstance(value, dict):
        return str(value.get("display_value", value.get("value", default)))
    return str(value if value is not None else default)


def _extract_records(data) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("result", "records", "rows"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        if any(k in data for k in ("number", "sys_id", "short_description", "updated_at")):
            return [data]
        return [x for x in data.values() if isinstance(x, dict)]
    return []


def parse_servicenow_json(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        raw = json.load(f)

    records = _extract_records(raw)
    parsed: list[dict[str, str]] = []
    for record in records:
        parsed.append(
            {
                "id": _unwrap(record.get("number", record.get("id", "UNKNOWN")), "UNKNOWN"),
                "title": _unwrap(record.get("short_description", record.get("title", "No Description")), "No Description"),
                "state": _unwrap(record.get("state", record.get("status", "Unknown")), "Unknown"),
                "updated": _unwrap(record.get("sys_updated_on", record.get("updated_at", "Unknown")), "Unknown"),
                "sys_id": _unwrap(record.get("sys_id", record.get("uid", "")), ""),
            }
        )
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize ServiceNow JSON export into simple ticket rows")
    parser.add_argument("--input", default="incidents/caller_history.json", help="Input JSON path")
    parser.add_argument("--output", default="", help="Optional output JSON file path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    parsed = parse_servicenow_json(input_path)
    print(f"Parsed records: {len(parsed)}")

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
        print(f"Wrote normalized output: {output_path}")


if __name__ == "__main__":
    main()
