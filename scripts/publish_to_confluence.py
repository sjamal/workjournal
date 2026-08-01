#!/usr/bin/env python3

"""Publish consolidated journal content to Confluence Cloud via REST API.

Purpose:
- Create a Confluence Cloud page from the same consolidated rows used by the
  dashboard and Markdown export.
- Upload screenshot assets from compilation/assets as page attachments so
  image references can render inline.

How to run:
- ./venv/bin/python scripts/publish_to_confluence.py --month 2026-07
- ./venv/bin/python scripts/publish_to_confluence.py --month 2026-07 --upload-assets
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime
from html import escape
from pathlib import Path

import requests
from dotenv import load_dotenv

from compile_dashboard import build_confluence_rows, build_timeline

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BASE_DIR / "compilation" / "assets"


def _escape_attr(value: str) -> str:
    return escape(str(value), quote=True)


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


def _build_storage_html(rows: list[dict[str, str]], title: str) -> str:
    parts = [f"<h1>{escape(title)}</h1>"]
    current_day = ""
    current_section = ""
    list_open = False

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            parts.append("</ul>")
            list_open = False

    for row in rows:
        date = escape(str(row.get("date", "")))
        section = _section_for_row(row)
        ref_label = str(row.get("ref", "")).strip()
        url = str(row.get("url", "")).strip()
        summary = str(row.get("summary", "")).strip()
        attachment = str(row.get("attachment", "")).strip()
        kind = str(row.get("kind", "")).strip()

        if not summary:
            continue

        if date != current_day:
            close_list()
            current_day = date
            current_section = ""
            parts.append(f"<h2>{date}</h2>")

        if section != current_section:
            close_list()
            current_section = section
            parts.append(f"<h3>{escape(section)}</h3>")
            parts.append("<ul>")
            list_open = True

        if kind == "ticket":
            ref_html = f"<a href='{_escape_attr(url)}'>{escape(ref_label)}</a>" if url else escape(ref_label)
            bullet = f"{ref_html}: {escape(summary)}"
        elif kind in {"screenshot", "note"}:
            label = escape(ref_label or "Activity")
            body = escape(summary)
            if attachment:
                body = f"<ac:image><ri:attachment ri:filename=\"{_escape_attr(attachment)}\" /></ac:image> {body}"
            bullet = f"{label}: {body}"
        else:
            bullet = escape(summary)

        parts.append(f"<li>{bullet}</li>")

    close_list()
    return "\n".join(parts)


def _upload_attachment(base_url: str, page_id: str, email: str, token: str, file_path: Path) -> None:
    url = f"{base_url}/rest/api/content/{page_id}/child/attachment"
    headers = {"X-Atlassian-Token": "no-check"}
    with file_path.open("rb") as fh:
        files = {"file": (file_path.name, fh, "application/octet-stream")}
        response = requests.post(url, auth=(email, token), headers=headers, files=files, timeout=120)
        response.raise_for_status()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish monthly workjournal content to Confluence Cloud")
    parser.add_argument("--month", default=datetime.now().strftime("%Y-%m"), help="Month scope in YYYY-MM (example: 2026-07)")
    parser.add_argument("--title", default=os.getenv("CONFLUENCE_TITLE", "Work Journal"), help="Confluence page title")
    parser.add_argument("--space-key", default=os.getenv("CONFLUENCE_SPACE", ""), help="Confluence space key")
    parser.add_argument("--parent-page-id", default=os.getenv("CONFLUENCE_PARENT_PAGE_ID", ""), help="Optional parent page ID to create the journal under")
    parser.add_argument("--base-url", default=os.getenv("CONFLUENCE_URL", ""), help="Confluence base URL, for example https://example.atlassian.net/wiki")
    parser.add_argument("--email", default=os.getenv("CONFLUENCE_EMAIL", ""), help="Confluence account email")
    parser.add_argument("--api-token", default=os.getenv("CONFLUENCE_API_TOKEN", os.getenv("CONFLUENCE_TOKEN", "")), help="Confluence API token")
    parser.add_argument("--upload-assets", action="store_true", help="Upload screenshots from compilation/assets as page attachments")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.base_url or not args.email or not args.api_token or not args.space_key:
        print("[X] Missing Confluence credentials or space key. Set CONFLUENCE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN, and CONFLUENCE_SPACE.")
        return 1

    timeline = build_timeline(31, month=args.month)
    rows = build_confluence_rows(timeline)
    storage_html = _build_storage_html(rows, args.title)

    create_url = f"{args.base_url}/rest/api/content"
    payload = {
        "type": "page",
        "title": args.title,
        "space": {"key": args.space_key},
        "body": {"storage": {"value": storage_html, "representation": "storage"}},
    }
    parent_page_id = str(args.parent_page_id).strip()
    if parent_page_id:
        payload["ancestors"] = [{"id": parent_page_id}]

    print(f"[+] Creating Confluence page in space {args.space_key}...")
    response = requests.post(create_url, auth=(args.email, args.api_token), json=payload, timeout=120)
    response.raise_for_status()
    page_id = response.json().get("id")
    page_url = f"{args.base_url}/pages/viewpage.action?pageId={page_id}"
    print(f"[✓] Page created: {page_url}")
    if parent_page_id:
        print(f"[✓] Created under parent page id: {parent_page_id}")

    if args.upload_assets:
        if ASSETS_DIR.exists():
            files = sorted(p for p in ASSETS_DIR.iterdir() if p.is_file())
            for file_path in files:
                print(f"[+] Uploading attachment: {file_path.name}")
                _upload_attachment(args.base_url, page_id, args.email, args.api_token, file_path)
            print(f"[✓] Uploaded {len(files)} attachments from {ASSETS_DIR}")
        else:
            print(f"[-] Assets directory not found: {ASSETS_DIR}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
