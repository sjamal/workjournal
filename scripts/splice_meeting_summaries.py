#!/usr/bin/env python3

"""Update only selected meeting summaries on an existing monthly Confluence page.

Purpose:
- Replace (or insert) individual meeting sections from meeting_summaries_cache.json
  without regenerating the whole page, so hand edits elsewhere on the page are kept.
- Refuse to publish over an unsaved draft with different text, or a page that
  changed since it was read, and check screenshots still render afterwards.

How to run:
- ./venv/bin/python scripts/splice_meeting_summaries.py --month 2026-10 --page-id <id> \
      [--file "<transcript file name>" ...] [--stats] [--dry-run]
- --stats adds or refreshes the Monthly Statistics section at the top of the page.
"""

from __future__ import annotations

import argparse
import html
import os
import re
from html import escape

import requests
from dotenv import load_dotenv

from compile_dashboard import build_confluence_rows, build_timeline
from monthly_stats import with_stats
from publish_to_confluence import _meeting_time, _meeting_title, _normalize_base_url, _render_meeting_summary

load_dotenv()
HEADING = re.compile(r"<h([2-4])[^>]*>(.*?)</h\1>", re.S)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _visible_lines(storage: str) -> list[str]:
    storage = re.sub(r"<ac:parameter[^>]*>.*?</ac:parameter>", "", storage, flags=re.S)
    return [line.strip() for line in html.unescape(re.sub(r"<[^>]+>", "\n", storage)).split("\n") if line.strip()]


def _balanced(fragment: str) -> bool:
    stack: list[str] = []
    for close, tag, self_closing in re.findall(r"<(/?)([a-zA-Z][\w:]*)[^>]*?(/?)>", re.sub(r"<!\[CDATA\[.*?\]\]>", "", fragment, flags=re.S)):
        if self_closing or tag in {"br", "hr", "img"}:
            continue
        if close:
            if not stack or stack.pop() != tag:
                return False
        else:
            stack.append(tag)
    return not stack


def _image_counts(view_html: str) -> tuple[int, int]:
    return len(re.findall(r"<img\b", view_html)), view_html.count("UNKNOWN_ATTACHMENT")


def _meeting_blocks(month: str, files: list[str]) -> list[tuple[str, str, str]]:
    """Return (date, heading text, storage block) for each selected meeting."""
    rows = build_confluence_rows(build_timeline(31, month=month))
    blocks = []
    for name in files:
        row = next((r for r in rows if r.get("kind") == "meeting" and r.get("file_name") == name), None)
        if row is None:
            raise SystemExit(f"[X] No meeting for {name!r} in {month}; check the cache and the file's date")
        heading = f"{_meeting_title(str(row.get('ref', '')))} ({_meeting_time(row)})"
        block = f"<h4>{escape(heading)}</h4>\n{_render_meeting_summary(str(row.get('summary', '')))}\n"
        blocks.append((str(row.get("date", "")), heading, block))
    return blocks


def _splice(storage: str, date: str, heading: str, block: str) -> tuple[str, str]:
    """Replace the section with the same heading (case-insensitive), or insert it on its day."""
    headings = [(m.start(), m.group(1), _text(m.group(2))) for m in HEADING.finditer(storage)]
    for i, (start, _, title) in enumerate(headings):
        if title.lower() == heading.lower():
            end = headings[i + 1][0] if i + 1 < len(headings) else len(storage)
            return storage[:start] + block + storage[end:], f"replace {end - start} -> {len(block)} chars"

    day = next((i for i, (_, level, title) in enumerate(headings) if level == "2" and title == date), None)
    if day is None:
        raise SystemExit(f"[X] No {date} section on the page to insert {heading!r} into")
    rest = headings[day + 1:]
    next_day = next((h for h in rest if h[1] == "2"), None)
    email = next((h for h in rest if h[2] == "Daily Email Summary" and (next_day is None or h[0] < next_day[0])), None)
    at = email[0] if email else (next_day[0] if next_day else len(storage))
    return storage[:at] + block + storage[at:], f"insert {len(block)} chars on {date}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Splice meeting summaries into an existing monthly page")
    parser.add_argument("--month", required=True, help="Month of the page in YYYY-MM")
    parser.add_argument("--page-id", required=True, help="Existing Confluence page to update")
    parser.add_argument("--file", dest="files", action="append", default=[], help="Transcript file name to splice; repeat for multiple")
    parser.add_argument("--stats", action="store_true", help="Add or refresh the Monthly Statistics section")
    parser.add_argument("--base-url", default=os.getenv("CONFLUENCE_URL", ""), help="Confluence site URL")
    parser.add_argument("--email", default=os.getenv("CONFLUENCE_EMAIL", ""), help="Confluence account email")
    parser.add_argument("--api-token", default=os.getenv("CONFLUENCE_API_TOKEN", os.getenv("CONFLUENCE_TOKEN", "")), help="Confluence API token")
    parser.add_argument("--ignore-draft", action="store_true", help="Publish even if an unsaved draft has different text")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without changing Confluence")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.files and not args.stats:
        print("[X] Pass --file and/or --stats")
        return 1
    if not args.base_url or not args.email or not args.api_token:
        print("[X] Missing Confluence credentials")
        return 1
    base_url = _normalize_base_url(args.base_url)
    auth = (args.email, args.api_token)
    url = f"{base_url}/rest/api/content/{args.page_id}"

    response = requests.get(url, auth=auth, params={"expand": "version,title,body.storage,body.view"}, timeout=120)
    response.raise_for_status()
    page = response.json()
    version = int(page["version"]["number"])
    storage = page["body"]["storage"]["value"]
    print(f"[+] Page {args.page_id} v{version}: {page['title']}")

    # Only a draft saved after the current version can hold unpublished edits; older ones are stale.
    draft = requests.get(url, auth=auth, params={"status": "draft", "expand": "version,body.storage"}, timeout=120)
    if draft.ok and _visible_lines(draft.json()["body"]["storage"]["value"]) != _visible_lines(storage):
        if draft.json()["version"]["when"] > page["version"]["when"]:
            print("[!] An unsaved draft has newer edits; close the editor or publish it first")
            if not args.ignore_draft:
                return 1
        else:
            print("[+] Ignoring a stale draft older than the current version")

    updated = storage
    for date, heading, block in _meeting_blocks(args.month, args.files):
        if not _balanced(block):
            print(f"[X] Unbalanced markup in {heading!r}")
            return 1
        updated, action = _splice(updated, date, heading, block)
        print(f"[+] {heading}: {action}")
    if args.stats:
        refreshed = "refresh" if "Monthly Statistics</h2>" in updated else "insert"
        updated = with_stats(updated, args.month)
        print(f"[+] Monthly Statistics: {refreshed}")
    if args.dry_run:
        return 0

    before = _image_counts(page["body"]["view"]["value"])
    current = requests.get(url, auth=auth, params={"expand": "version"}, timeout=120).json()
    if int(current["version"]["number"]) != version:
        print(f"[X] Page changed to v{current['version']['number']} while preparing; rerun")
        return 1
    payload = {
        "version": {"number": version + 1, "message": "Update meeting summaries"},
        "type": "page",
        "title": page["title"],
        "body": {"storage": {"value": updated, "representation": "storage"}},
    }
    requests.put(url, auth=auth, json=payload, timeout=180).raise_for_status()

    view = requests.get(url, auth=auth, params={"expand": "version,body.view"}, timeout=180).json()
    images, unknown = _image_counts(view["body"]["view"]["value"])
    print(f"[✓] Published v{view['version']['number']}; screenshots {before[0]} -> {images}")
    if images != before[0] or unknown:
        print(f"[!] Check the page: screenshot count changed or {unknown} UNKNOWN_ATTACHMENT references")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
