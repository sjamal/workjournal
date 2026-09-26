#!/usr/bin/env python3

"""Publish or update a monthly workjournal page in Confluence Cloud."""

from __future__ import annotations

import argparse
import os
import re
from datetime import datetime
from html import escape
from pathlib import Path

import requests
from dotenv import load_dotenv

from compile_dashboard import build_confluence_rows, build_timeline

load_dotenv()
BASE_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = BASE_DIR / "compilation" / "assets"
SCREENSHOT_THUMBNAIL_WIDTH = 320


def _escape_attr(value: str) -> str:
    return escape(str(value), quote=True)


def _section_for_row(row: dict[str, str]) -> str:
    kind = str(row.get("kind", "")).strip()
    ref = str(row.get("ref", "")).strip()
    if kind == "ticket": return "Ticket Summary"
    if kind == "meeting": return "Meeting Minutes"
    if kind == "email-analytics": return "Daily Email Summary"
    if kind == "daily-notes": return "Daily Notes"
    if kind in {"screenshot", "note"} or ref.startswith("Screenshot ("): return "Chronological Activity"
    if ref.startswith("Meeting:"): return "Meeting Minutes"
    if ref == "Daily Email Summary": return "Daily Email Summary"
    return "Activity"


def _escape_with_breaks(value: str) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    return "<br/>".join(escape(line) for line in text.split("\n"))


def _code_signal(line: str) -> int:
    stripped = line.strip()
    if not stripped:
        return 0
    if line[:1].isspace() and re.match(r"^(?:--?\w+|['\"]|https?://|[A-Za-z_][\w.-]*=)", stripped):
        return 2
    if re.match(r"^(?:\$|%|>>>|PS [^>]+>|[A-Za-z0-9_.-]+@[^ ]+[#$%>]\s*)", stripped, re.IGNORECASE):
        return 3
    if re.match(r"^[A-Za-z0-9_.-]+@[^ ]+\s+#\s+", stripped):
        return 3
    if re.match(r"^[A-Za-z0-9_.-]+:[~\/A-Za-z0-9_.-]*\s+#\s+", stripped):
        return 3
    if re.match(r"^(?:sudo|cd|ls|find|grep|awk|sed|cat|curl|git|python(?:3)?|pip|npm|make|docker|kubectl|az|gh|sha256sum|openssl|ssh|chmod|chown|systemctl|journalctl|terraform|ansible|rm|cp|mv|mkdir|rmdir|touch|tee|vim|nano|less|more|head|tail|sort|uniq|wc|diff|tar|zip|unzip|rpm|dpkg|apt|dnf|mgradm|mgrctl|reboot|mount|umount|tree|df|du|free|ip|ss|nsradmin|transactional-update|puppet|puppetserver|lvcreate|lvextend|lvdisplay|vgcreate|vgextend|pvcreate|resize2fs|xfs_growfs|parted)\b", stripped, re.IGNORECASE):
        return 3
    if re.match(r"^\s*\d+\s+(?:\d{4}-\d{2}-\d{2}\s+)?\d{1,2}:\d{2}:\d{2}\s+(?:sudo|cd|ls|find|grep|awk|sed|cat|curl|git|python|pip|ssh|chmod|chown|systemctl|docker|kubectl|az|gh|zypper|puppet|mgrctl|mgradm)\b", stripped, re.IGNORECASE):
        return 3
    if re.match(r"^[A-Za-z0-9][A-Za-z0-9.-]*\.(?:az|easi|utoronto|local|internal|com|net|org|edu)\b", stripped, re.IGNORECASE):
        return 2
    if re.match(r"^[A-Za-z0-9][A-Za-z0-9.-]*\s+\([^()]+\)$", stripped):
        return 2
    if re.match(r"^(?:total\s+\d+|[dlcbps-][rwx-]{8,}\s+\d+\s+\S+\s+\S+|\S+\s+\S+\s+\S+\s+(?:mounted|online|active))", stripped, re.IGNORECASE):
        return 2
    if re.match(r"^(?:zypper|puppet|df|lsblk|mount|fdisk|lv|vg|pv|resize2fs|xfs_growfs|parted|nslookup|dig|host|hostname)\b", stripped, re.IGNORECASE):
        return 3
    if re.match(r"^(?:#!/|export\s+|set\s+-[eux]|function\s+|(?:INFO|WARN|ERROR|DEBUG|TRACE)\b|\[[+!X✓-]\]|(?:HTTP|GET|POST|PUT|DELETE)\s+\d{3}\b|Traceback|File \".*\", line )", stripped, re.IGNORECASE):
        return 3
    if re.match(r"^#\s+(?:verify|run|check|set|create|install|remove|list|query|copy|configure|start|stop|restart|test|build)\b", stripped, re.IGNORECASE):
        return 2
    if re.match(r"^(?:[A-Za-z_][\w.-]*=|[A-Za-z_][\w.-]*:\s+\S|\{\s*[\"']|[\[{].*[\]}]$)", stripped):
        return 2
    if re.search(r"(?:\s|^)(?:\|\||&&|>>|2>&1|\|)(?:\s|$)", stripped) or re.search(r"\b(?:stdout|stderr|exit code|return code)\b", stripped, re.IGNORECASE):
        return 2
    if re.match(r"^(?:\d{4}-\d{2}-\d{2}[T ]|\d{1,2}:\d{2}(?::\d{2})?)", stripped):
        return 2
    if re.search(r"(?:^|\s)(?:/Users/|/etc/|~/|\./|\.\./)", stripped):
        return 2
    if re.match(r"^(?:[0-9a-f]{1,4}:){2,}[0-9a-f:]*$|^(?:\d{1,3}\.){3}\d{1,3}\b", stripped, re.IGNORECASE):
        return 1
    if re.match(r"^[A-Za-z0-9_.-]+\.(?:local|internal|com|net|org|edu)\b", stripped, re.IGNORECASE):
        return 1
    if re.match(r"^[dlcbps-][rwx-]{8,}\s+\d+\s+\S+\s+\S+\s+\d+", stripped):
        return 1
    if re.match(r"^(?:Filesystem|NAME\s+MAJ:MIN|Device|容量|Size|Used|Avail|Mounted|total\s+\d+|/dev/\S+)", stripped, re.IGNORECASE):
        return 1
    if re.match(r"^(?:[├└│]──|[|`]--)", stripped):
        return 1
    return 0


def _looks_like_code(line: str) -> bool:
    return _code_signal(line) > 0


def _code_language(lines: list[str]) -> str:
    text = "\n".join(lines).lower()
    if any(token in text for token in ("#!/bin/", "sudo ", "git ", "grep ", "export ", "set -e")):
        return "bash"
    if any(token in text for token in ("import ", "def ", "from ", "print(")):
        return "python"
    if text.lstrip().startswith(("{", "[")):
        return "json"
    return "none"


def _code_macro(lines: list[str]) -> str:
    body = "\n".join(lines).replace("]]>", "]]]]><![CDATA[>")
    language = _code_language(lines)
    return (
        '<ac:structured-macro ac:name="code">'
        f'<ac:parameter ac:name="language">{language}</ac:parameter>'
        f"<ac:plain-text-body><![CDATA[{body}]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )


def _render_summary(value: str) -> str:
    """Render and merge adjacent operational paragraphs as complete code blocks."""
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    classified_blocks: list[tuple[bool, list[str]]] = []
    for block in re.split(r"\n\s*\n", normalized):
        lines = [line.rstrip() for line in block.split("\n") if line.strip()]
        signals = [_code_signal(line) for line in lines]
        signal_count = sum(signal > 0 for signal in signals)
        strong_count = sum(signal >= 3 for signal in signals)
        code_ratio = signal_count / max(1, len(lines))
        is_code = bool(strong_count or (signal_count >= 2 and code_ratio >= 0.5))
        classified_blocks.append((is_code, lines))

    rendered: list[str] = []
    index = 0
    while index < len(classified_blocks):
        is_code, lines = classified_blocks[index]
        if is_code:
            merged = list(lines)
            index += 1
            while index < len(classified_blocks) and classified_blocks[index][0]:
                previous_line = merged[-1].rstrip()
                next_lines = classified_blocks[index][1]
                continuation = previous_line.endswith("\\") or (
                    next_lines
                    and next_lines[0][:1].isspace()
                    and re.match(r"^(?:--?\w+|['\"]|https?://)", next_lines[0].strip())
                )
                if not continuation:
                    break
                merged.extend(next_lines)
                index += 1
            rendered.append(_code_macro(merged))
        else:
            rendered.append(_escape_with_breaks("\n".join(lines)))
            index += 1
    return "<br/>".join(rendered)


def _meeting_time(row: dict[str, str]) -> str:
    source = str(row.get("file_name", ""))
    match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", source, re.IGNORECASE)
    if not match:
        return "time not recorded"
    hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), match.group(3).upper()
    return f"{hour}:{minute:02d} {meridiem}"


def _meeting_title(ref_label: str) -> str:
    title = re.sub(r"^Meeting:\s*", "", ref_label).strip()
    return re.sub(r"\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)\s*$", "", title, flags=re.IGNORECASE).strip()


def _render_meeting_summary(value: str) -> str:
    """Convert Markdown-like meeting summaries into Confluence elements."""
    rendered: list[str] = []
    paragraph: list[str] = []
    bullets: list[str] = []

    def close_paragraph() -> None:
        if paragraph:
            rendered.append(f"<p>{_render_summary(' '.join(paragraph))}</p>")
            paragraph.clear()

    def close_bullets() -> None:
        if bullets:
            rendered.append("<ul>" + "".join(f"<li>{_render_summary(item)}</li>" for item in bullets) + "</ul>")
            bullets.clear()

    for raw_line in str(value).replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            close_paragraph()
            close_bullets()
            continue
        heading = re.match(r"^(?:#{2,6}\s+|\*\*)(.*?)(?:\*\*)?$", line)
        if heading:
            close_paragraph()
            close_bullets()
            rendered.append(f"<h5>{escape(heading.group(1).strip('* ').strip())}</h5>")
            continue
        bullet = re.match(r"^(?:[-*]|\d+\.)\s+(.*)$", line)
        if bullet:
            close_paragraph()
            bullets.append(bullet.group(1).strip())
            continue
        close_bullets()
        paragraph.append(line)

    close_paragraph()
    close_bullets()
    return "\n".join(rendered)


def _build_storage_html(rows: list[dict[str, str]]) -> str:
    """Build plain storage markup; the Confluence page title remains the title."""
    parts: list[str] = []
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
            if kind != "meeting":
                parts.append(f"<h4>{escape(section)}</h4>")
                parts.append("<ul>")
                list_open = True

        if kind == "ticket":
            ref_html = f"<a href='{_escape_attr(url)}'>{escape(ref_label)}</a>" if url else escape(ref_label)
            bullet = f"{ref_html}: {_escape_with_breaks(summary)}"
        elif kind in {"screenshot", "note"}:
            body = _render_summary(summary)
            if attachment:
                body = (
                    f'<ac:image ac:thumbnail="true" ac:width="{SCREENSHOT_THUMBNAIL_WIDTH}">'
                    f'<ri:attachment ri:filename="{_escape_attr(attachment)}" />'
                    f"</ac:image> {body}"
                )
            bullet = f"{escape(ref_label or 'Activity')}: {body}"
        elif kind == "meeting":
            close_list()
            parts.append(f"<h4>{escape(_meeting_title(ref_label))} ({escape(_meeting_time(row))})</h4>")
            parts.append(_render_meeting_summary(summary))
            current_section = ""
        else:
            bullet = _render_summary(summary) if kind == "daily-notes" else _escape_with_breaks(summary)
        if kind != "meeting":
            parts.append(f"<li>{bullet}</li>")

    close_list()
    return "\n".join(parts)


def _normalize_base_url(value: str) -> str:
    return re.sub(r"/spaces/.*$", "", value.strip().rstrip("/"))


def _referenced_asset_names(rows: list[dict[str, str]]) -> set[str]:
    return {str(row.get("attachment", "")).strip() for row in rows if str(row.get("attachment", "")).strip()}


def _existing_attachment_names(base_url: str, page_id: str, email: str, token: str) -> set[str]:
    url = f"{base_url}/rest/api/content/{page_id}/child/attachment"
    response = requests.get(url, auth=(email, token), params={"limit": 2000}, timeout=120)
    response.raise_for_status()
    return {str(item.get("title", "")).strip() for item in response.json().get("results", []) if str(item.get("title", "")).strip()}


def _upload_attachment(base_url: str, page_id: str, email: str, token: str, file_path: Path) -> None:
    url = f"{base_url}/rest/api/content/{page_id}/child/attachment"
    with file_path.open("rb") as file_handle:
        files = {"file": (file_path.name, file_handle, "application/octet-stream")}
        response = requests.post(url, auth=(email, token), headers={"X-Atlassian-Token": "no-check"}, files=files, timeout=120)
        response.raise_for_status()


def _update_page(base_url: str, page_id: str, email: str, token: str, storage_html: str) -> str:
    url = f"{base_url}/rest/api/content/{page_id}"
    response = requests.get(url, auth=(email, token), params={"expand": "version,title"}, timeout=120)
    response.raise_for_status()
    current = response.json()
    title = str(current.get("title", "Work Journal"))
    payload = {"version": {"number": int(current["version"]["number"]) + 1}, "type": "page", "title": title, "body": {"storage": {"value": storage_html, "representation": "storage"}}}
    update_response = requests.put(url, auth=(email, token), json=payload, timeout=120)
    update_response.raise_for_status()
    return title


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish or update a monthly workjournal page")
    parser.add_argument("--month", default=datetime.now().strftime("%Y-%m"), help="Month scope in YYYY-MM")
    parser.add_argument("--title", default=os.getenv("CONFLUENCE_TITLE", "Work Journal"), help="Title for newly created pages")
    parser.add_argument("--space-key", default=os.getenv("CONFLUENCE_SPACE", ""), help="Confluence space key for new pages")
    parser.add_argument("--parent-page-id", default=os.getenv("CONFLUENCE_PARENT_PAGE_ID", ""), help="Optional parent ID for new pages")
    parser.add_argument("--base-url", default=os.getenv("CONFLUENCE_URL", ""), help="Confluence site URL")
    parser.add_argument("--email", default=os.getenv("CONFLUENCE_EMAIL", ""), help="Confluence account email")
    parser.add_argument("--api-token", default=os.getenv("CONFLUENCE_API_TOKEN", os.getenv("CONFLUENCE_TOKEN", "")), help="Confluence API token")
    parser.add_argument("--page-id", help="Update this existing page instead of creating a page")
    parser.add_argument("--upload-assets", action="store_true", help="Upload only screenshots referenced by this month")
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without changing Confluence")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.base_url or not args.email or not args.api_token:
        print("[X] Missing Confluence credentials")
        return 1
    if not args.page_id and not args.space_key:
        print("[X] Set --page-id for an existing page or CONFLUENCE_SPACE to create a page")
        return 1

    args.base_url = _normalize_base_url(args.base_url)
    timeline = build_timeline(31, month=args.month)
    rows = build_confluence_rows(timeline)
    storage_html = _build_storage_html(rows)
    asset_paths = [ASSETS_DIR / name for name in sorted(_referenced_asset_names(rows))]
    missing_assets = [path.name for path in asset_paths if not path.is_file()]
    if missing_assets:
        print(f"[X] Missing referenced screenshot assets: {', '.join(missing_assets[:10])}")
        return 1

    target = f"existing page {args.page_id}" if args.page_id else f"new page in {args.space_key}"
    print(f"[+] Target: {target}")
    print(f"[+] Month {args.month}: {len(rows)} content rows, {len(asset_paths)} screenshot attachments")
    if args.dry_run:
        return 0

    if args.page_id:
        title = _update_page(args.base_url, args.page_id, args.email, args.api_token, storage_html)
        print(f"[✓] Updated page {args.page_id}: {title}")
        if args.upload_assets:
            existing = _existing_attachment_names(args.base_url, args.page_id, args.email, args.api_token)
            uploaded = 0
            for path in asset_paths:
                if path.name in existing:
                    continue
                print(f"[+] Uploading screenshot: {path.name}")
                _upload_attachment(args.base_url, args.page_id, args.email, args.api_token, path)
                uploaded += 1
            print(f"[✓] Uploaded {uploaded} new screenshots; skipped {len(asset_paths) - uploaded} already attached")
        return 0

    payload = {"type": "page", "title": args.title, "space": {"key": args.space_key}, "body": {"storage": {"value": storage_html, "representation": "storage"}}}
    if args.parent_page_id:
        payload["ancestors"] = [{"id": args.parent_page_id}]
    response = requests.post(f"{args.base_url}/rest/api/content", auth=(args.email, args.api_token), json=payload, timeout=120)
    response.raise_for_status()
    page_id = str(response.json().get("id", ""))
    print(f"[✓] Page created: {args.base_url}/pages/viewpage.action?pageId={page_id}")
    if args.upload_assets:
        for path in asset_paths:
            _upload_attachment(args.base_url, page_id, args.email, args.api_token, path)
        print(f"[✓] Uploaded {len(asset_paths)} screenshot attachments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
