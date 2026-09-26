#!/usr/bin/env python3

"""Build an interactive monthly dashboard and Confluence table markup.

Purpose:
- Consolidate local notes, screenshots, ticket cache, meeting summaries, and
  imported email-analytics daily summaries into a single day-by-day dashboard.
- Let you review timeline rows visually and generate a downloadable Confluence
  wiki-table text file from the same rows.

How to run:
- ./venv/bin/python scripts/compile_dashboard.py
- ./venv/bin/python scripts/compile_dashboard.py --month 2026-07
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")
BBEDIT_DIR = os.path.expanduser("~/Documents/Personal/notes")

OUTPUT_DIR = os.path.join(BASE_DIR, "compilation")
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_DASHBOARD = os.path.join(OUTPUT_DIR, "work_journal_dashboard.html")

# Keep July 1 clean: only imported email analytics is treated as canonical.
DAY_CONTENT_SUPPRESSIONS = {
    "2026-07-01": {"note_logs", "screenshots", "tickets", "emails", "meetings", "note_blob"}
}


def _month_window(month: str) -> tuple[datetime, datetime]:
    """Return [month_start, next_month_start) for YYYY-MM input."""
    start = datetime.strptime(f"{month}-01", "%Y-%m-%d")
    if start.month == 12:
        end = datetime(start.year + 1, 1, 1)
    else:
        end = datetime(start.year, start.month + 1, 1)
    return start, end


def load_cache_file(filename: str):
    """Read a JSON cache file from cache/; return [] when missing or invalid."""
    path = os.path.join(CACHE_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _normalize_date(value: str) -> str:
    if not value:
        return ""
    value = str(value)
    if len(value) >= 10:
        return value[:10]
    return value


def _parse_time_for_day(day: str, raw_time: str) -> datetime | None:
    t_str = str(raw_time).upper().strip()
    try:
        if "AM" in t_str or "PM" in t_str:
            return datetime.strptime(f"{day} {t_str}", "%Y-%m-%d %I:%M %p")
        clean_t = ":".join(t_str.split(":")[:2])
        return datetime.strptime(f"{day} {clean_t}", "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _to_file_uri(path: str) -> str:
    """Convert a local absolute path to a browser-safe file URI."""
    try:
        return Path(path).expanduser().resolve().as_uri()
    except Exception:
        return f"file://{path}"


def _extract_note_body(line: str) -> str:
    """Strip leading time tokens so timeline lines stay compact."""
    compact = re.sub(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?\s*", "", line.strip(), flags=re.IGNORECASE)
    return compact.strip("-: ") or line.strip()


def _normalize_multiline(value: str) -> str:
    """Normalize line endings while preserving intentional line breaks."""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.strip("\n")


def _normalize_hhmm(value: str) -> str:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not m:
        return value.strip()
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _parse_note_date_marker(line: str, default_year: int) -> str | None:
    """Normalize ISO and month-name daily note headings to YYYY-MM-DD."""
    iso_match = re.fullmatch(r"\s*===\s*(\d{4}-\d{2}-\d{2})\s*===\s*", line)
    if iso_match:
        return iso_match.group(1)

    month_match = re.fullmatch(
        r"\s*(January|February|March|April|May|June|July|August|September|October|November|December|"
        r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\s+(\d{1,2})(?:st|nd|rd|th)?\s*",
        line,
        flags=re.IGNORECASE,
    )
    if not month_match:
        return None

    try:
        month = datetime.strptime(month_match.group(1)[:3].title(), "%b").month
        day = int(month_match.group(2))
        return datetime(default_year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _drop_redundant_leading_times(text: str) -> str:
    """Remove duplicated leading HH:MM labels in command-output style note lines."""
    out: list[str] = []
    for line in _normalize_multiline(text).split("\n"):
        m = re.match(r"^\s*(\d{1,2}:\d{2})\s*:\s+(.*)$", line)
        if not m:
            out.append(line)
            continue

        lead = _normalize_hhmm(m.group(1))
        payload = m.group(2)
        next_time = re.search(r"\b(\d{1,2}:\d{2})\b", payload)
        if next_time and _normalize_hhmm(next_time.group(1)) == lead:
            out.append(payload)
        else:
            out.append(line)
    return "\n".join(out).strip("\n")


def _compose_daily_notes(day_data: dict) -> str:
    """Return daily notes from full BBEdit block, with log-line fallback."""
    blob = _drop_redundant_leading_times(day_data.get("note_blob", "")).strip()
    if blob:
        return blob

    note_lines = [str(item.get("text", "")).strip() for item in day_data.get("note_logs", []) if str(item.get("text", "")).strip()]
    return _drop_redundant_leading_times("\n".join(note_lines)).strip()


def parse_bbedit_time_contexts(start_date_str: str):
    """Extract timestamped lines from BBEdit daily note files."""
    time_logs = []
    if not os.path.exists(BBEDIT_DIR):
        return time_logs

    files = glob.glob(os.path.join(BBEDIT_DIR, "*.txt")) + glob.glob(os.path.join(BBEDIT_DIR, "*.markdown"))
    time_pattern = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)", re.IGNORECASE)

    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                file_year_match = re.search(r"(20\d{2})", os.path.basename(fp))
                default_year = int(file_year_match.group(1)) if file_year_match else int(start_date_str[:4])
                curr_dt = ""
                for line in f:
                    note_date = _parse_note_date_marker(line, default_year)
                    if note_date:
                        curr_dt = note_date
                        continue
                    t_m = time_pattern.findall(line)
                    if t_m and curr_dt and curr_dt >= start_date_str:
                        raw_time = str(t_m[0]).strip()
                        parsed_dt = _parse_time_for_day(curr_dt, raw_time)
                        time_logs.append(
                            {
                                "date": curr_dt,
                                "raw_time": raw_time,
                                "text": line.strip(),
                                "parsed_dt": parsed_dt,
                            }
                        )
        except Exception:
            pass
    return time_logs


def _materialize_dashboard_asset(src_path: str, mtime: int, assets_dir: str) -> str:
    """Copy screenshot into compilation/assets and return relative HTML src path."""
    src = Path(src_path)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", src.stem)
    out_name = f"{safe_name}_{mtime}{src.suffix.lower()}"
    dest = Path(assets_dir) / out_name

    try:
        if not dest.exists() or os.path.getmtime(src_path) > os.path.getmtime(dest):
            shutil.copy2(src_path, dest)
    except Exception:
        # Fallback to direct file URI when copy fails.
        return _to_file_uri(src_path)

    rel = os.path.relpath(dest, OUTPUT_DIR)
    return rel.replace(os.sep, "/")


def _asset_name_from_dashboard_src(src: str) -> str:
    if not src:
        return ""
    if src.startswith("file://"):
        return os.path.basename(src)
    return os.path.basename(src.replace("\\", "/"))


def gather_screenshots(bbedit_logs, screenshot_summary_map, start_date_obj, assets_dir: str):
    """Collect recent screenshots and infer context from nearby note timestamps."""
    images = []
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        for fp in glob.glob(os.path.join(DOWNLOADS_DIR, ext)):
            mtime = os.path.getmtime(fp)
            if mtime < start_date_obj.timestamp():
                continue

            dt_obj = datetime.fromtimestamp(mtime)
            dt_str = dt_obj.strftime("%Y-%m-%d")
            tks = re.findall(r"(INC\d+|REQ\d+|Task-\d+|US-\d+)", os.path.basename(fp), re.IGNORECASE)

            matched_snippet = ""
            for log in bbedit_logs:
                if log["date"] != dt_str:
                    continue
                parsed_dt = log.get("parsed_dt")
                if parsed_dt is None:
                    continue
                if abs((dt_obj - parsed_dt).total_seconds()) <= 1800:
                    matched_snippet = _extract_note_body(log["text"])
                    break

            summary_key = f"{fp}|{int(mtime)}"
            ai_summary = screenshot_summary_map.get(summary_key, "")
            dashboard_src = _materialize_dashboard_asset(fp, int(mtime), assets_dir)

            images.append(
                {
                    "type": "screenshot",
                    "path": fp,
                    "path_uri": _to_file_uri(fp),
                    "name": os.path.basename(fp),
                    "date": dt_str,
                    "timestamp": dt_obj,
                    "tickets": ", ".join(set(tks)) if tks else "Screenshot Evidence",
                    "inferred_context": matched_snippet,
                    "ai_summary": ai_summary,
                    "dashboard_src": dashboard_src,
                    "asset_name": _asset_name_from_dashboard_src(dashboard_src),
                }
            )
    return images


def parse_bbedit_notes_for_sidebar(start_date_str: str):
    """Return full per-day note blocks for optional reference usage."""
    notes = {}
    if not os.path.exists(BBEDIT_DIR):
        return notes
    files = glob.glob(os.path.join(BBEDIT_DIR, "*.txt")) + glob.glob(os.path.join(BBEDIT_DIR, "*.markdown"))
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                file_year_match = re.search(r"(20\d{2})", os.path.basename(fp))
                default_year = int(file_year_match.group(1)) if file_year_match else int(start_date_str[:4])
                curr_dt = ""
                current_lines: list[str] = []
                for line in f:
                    note_date = _parse_note_date_marker(line, default_year)
                    if note_date:
                        if curr_dt and curr_dt >= start_date_str:
                            notes[curr_dt] = "".join(current_lines).strip()
                        curr_dt = note_date
                        current_lines = []
                    elif curr_dt:
                        current_lines.append(line)
                if curr_dt and curr_dt >= start_date_str:
                    notes[curr_dt] = "".join(current_lines).strip()
        except Exception:
            pass
    return notes


def build_day_events(day, day_data):
    """Build chronological note/screenshot event rows for one day."""
    events = []

    for ss in day_data.get("screenshots", []):
        ts = ss.get("timestamp")
        summary = ss.get("inferred_context", "").strip() or ss.get("ai_summary", "").strip()
        if not summary:
            summary = "Screenshot captured. Add summary if needed."
        events.append(
            {
                "sort_ts": ts,
                "date": day,
                "time": ts.strftime("%H:%M") if ts else "",
                "ref": ss.get("tickets", "Screenshot Evidence"),
                "summary": summary,
                "kind": "screenshot",
                "screenshot": ss,
            }
        )

    events.sort(key=lambda x: x.get("sort_ts") or datetime.strptime(f"{day} 23:59", "%Y-%m-%d %H:%M"))
    return events


def _line(html: list[str], value: str) -> None:
    html.append(value)


def _escape_attr(value: str) -> str:
    return escape(value, quote=True)


def _apply_day_suppressions(day: str, day_data: dict) -> None:
    suppressed = DAY_CONTENT_SUPPRESSIONS.get(day)
    if not suppressed:
        return
    for key in suppressed:
        if key not in day_data:
            continue
        if isinstance(day_data[key], list):
            day_data[key] = []
        elif isinstance(day_data[key], str):
            day_data[key] = ""


def build_timeline(days: int, month: str | None = None):
    """Build the full day-indexed timeline structure from all local inputs."""
    if month:
        start_date_obj, end_date_obj = _month_window(month)
    else:
        start_date_obj = datetime.now() - timedelta(days=days)
        end_date_obj = datetime.now() + timedelta(days=1)

    start_date_str = start_date_obj.strftime("%Y-%m-%d")

    assets_dir = os.path.join(OUTPUT_DIR, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    tickets = load_cache_file("work_items_cache.json")
    meetings = load_cache_file("meeting_summaries_cache.json")
    emails = load_cache_file("emails_cache.json")
    email_analytics_daily = load_cache_file("email_analytics_daily_cache.json")
    screenshot_summaries = load_cache_file("screenshot_summaries_cache.json")

    screenshot_summary_map = {
        f"{item.get('path', '')}|{int(item.get('mtime', 0))}": str(item.get("summary", ""))
        for item in screenshot_summaries
        if item.get("path")
    }

    bbedit_logs = parse_bbedit_time_contexts(start_date_str)
    notes_by_date = parse_bbedit_notes_for_sidebar(start_date_str)
    screenshots = gather_screenshots(bbedit_logs, screenshot_summary_map, start_date_obj, assets_dir)

    timeline = {}
    total_days = max(1, (end_date_obj - start_date_obj).days) if month else days + 1

    for d in range(total_days):
        day_str = (start_date_obj + timedelta(days=d)).strftime("%Y-%m-%d")
        timeline[day_str] = {
            "screenshots": [],
            "tickets": [],
            "emails": [],
            "note_logs": [],
            "note_blob": "",
            "meetings": [],
            "email_analytics": [],
        }

    for log in bbedit_logs:
        day = log.get("date")
        if day in timeline:
            timeline[day]["note_logs"].append(log)

    for day, text in notes_by_date.items():
        if day in timeline:
            timeline[day]["note_blob"] = text

    for ss in screenshots:
        day = ss.get("date")
        if day in timeline:
            timeline[day]["screenshots"].append(ss)

    for t in tickets:
        clean_date = _normalize_date(t.get("date_modified", ""))
        if clean_date in timeline:
            timeline[clean_date]["tickets"].append(t)

    for e in emails:
        e_date = _normalize_date(e.get("date", ""))
        if e_date in timeline:
            timeline[e_date]["emails"].append(e)

    for m in meetings:
        m_date = _normalize_date(m.get("date", ""))
        if m_date in timeline:
            timeline[m_date]["meetings"].append(m)

    for item in email_analytics_daily:
        day = _normalize_date(item.get("date", ""))
        if day in timeline:
            timeline[day]["email_analytics"].append(item)

    for day in timeline:
        _apply_day_suppressions(day, timeline[day])

    return timeline


def build_confluence_rows(timeline: dict[str, dict]) -> list[dict[str, str]]:
    """Create unified rows used by both dashboard export and text file export."""
    rows: list[dict[str, str]] = []

    for day in sorted(timeline.keys()):
        day_data = timeline[day]
        events = build_day_events(day, day_data)

        for t in day_data.get("tickets", []):
            source = str(t.get("source", ""))
            prefix = "ADO" if "DevOps" in source else "SN"
            ref = f"{prefix} {t.get('id', 'UNKNOWN')}"
            summary = str(t.get("title", "")).strip()
            if summary:
                rows.append({"date": day, "ref": ref, "summary": summary, "attachment": "", "url": str(t.get("url", "")).strip(), "kind": "ticket"})

        for ev in events:
            time_prefix = f"{ev.get('time', '')}: " if ev.get("time") else ""
            attachment = ""
            if ev.get("kind") == "screenshot":
                ref = f"Screenshot ({ev.get('ref', 'Evidence')})"
                ss = ev.get("screenshot") or {}
                attachment = str(ss.get("asset_name", "")).strip()
            else:
                ref = "Note"
            rows.append(
                {
                    "date": day,
                    "ref": ref,
                    "summary": f"{time_prefix}{ev.get('summary', '').strip()}".strip(),
                    "attachment": attachment,
                    "url": "",
                    "kind": str(ev.get("kind", "note")),
                }
            )

        day_notes = _compose_daily_notes(day_data)
        if day_notes:
            rows.append({"date": day, "ref": "Daily Notes", "summary": day_notes, "attachment": "", "url": "", "kind": "daily-notes"})

        for mt in day_data.get("meetings", []):
            title = str(mt.get("inferred_title", "Meeting")).strip()
            kb = str(mt.get("high_fidelity_kb", "")).strip()
            if kb:
                rows.append(
                    {
                        "date": day,
                        "ref": f"Meeting: {title}",
                        "summary": kb,
                        "attachment": "",
                        "url": "",
                        "kind": "meeting",
                        "file_name": str(mt.get("file_name", "")),
                    }
                )

        for item in day_data.get("email_analytics", []):
            summary = str(item.get("daily_summary", "")).strip()
            if summary:
                rows.append({"date": day, "ref": "Daily Email Summary", "summary": summary, "attachment": "", "url": "", "kind": "email-analytics"})

    return rows


def generate_dashboard(days: int = 31, output_file: str = OUTPUT_DASHBOARD, month: str | None = None):
    """Compile interactive dashboard HTML with downloadable Confluence export action."""
    scope_label = month if month else f"last {days} days"
    print(f"Compiling unified workspace for {scope_label}...")
    timeline = build_timeline(days, month=month)

    html: list[str] = []
    _line(html, "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Journal</title><style>")
    _line(html, "body { font-family:sans-serif; background:#f4f5f7; color:#172b4d; padding:20px; }")
    _line(html, ".navbar { background:#0052cc; color:white; padding:15px; display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; border-radius:4px; gap:12px; flex-wrap:wrap; }")
    _line(html, ".controls { display:flex; gap:8px; align-items:center; }")
    _line(html, ".day-block { background:white; border:1px solid #dfe1e6; border-radius:8px; padding:16px; margin-bottom:16px; }")
    _line(html, ".day-header { font-size:16px; font-weight:bold; color:#0052cc; border-bottom:1px solid #dfe1e6; padding-bottom:6px; margin-bottom:12px; }")
    _line(html, ".section-title { font-weight:bold; font-size:12px; margin:12px 0 6px 0; color:#1f3f72; }")
    _line(html, ".activity-line { margin:6px 0; line-height:1.35; }")
    _line(html, ".ts { color:#5e6c84; font-weight:bold; margin-right:4px; }")
    _line(html, ".ticket-badge { background:#eae6ff; color:#403294; padding:2px 6px; border-radius:3px; font-size:11px; font-weight:bold; }")
    _line(html, ".ticket-badge.sn { background:#e3fcef; color:#006644; }")
    _line(html, "textarea { width:100%; box-sizing:border-box; margin-top:6px; padding:6px; }")
    _line(html, "img { max-width:100%; max-height:260px; display:block; margin:6px 0; border:1px solid #ccc; border-radius:4px; }")
    _line(html, "pre { background:#f4f5f7; padding:10px; border-radius:4px; font-size:11px; max-height:260px; overflow-y:auto; white-space:pre-wrap; }")
    _line(html, "button { background:#0052cc; color:white; border:none; padding:10px 16px; border-radius:4px; font-weight:bold; cursor:pointer; }")
    _line(html, "small.subtle { color:#dfe8ff; }")
    _line(html, "#genStatus { color:#dfe8ff; font-size:12px; }")
    _line(html, "</style></head><body>")

    _line(
        html,
        "<div class='navbar'><div><h1 style='margin:0;'>Confluence Work Journal Compiler</h1><small class='subtle'>Review rows, then download Markdown handoff output.</small></div><div class='controls'><button type='button' onclick='compileJournal()'>Generate Markdown File</button></div><span id='genStatus'></span></div>",
    )
    _line(html, "<div class='main-workspace'><form id='journalForm'>")

    total_rows = 0

    for day in sorted(timeline.keys()):
        day_data = timeline[day]
        events = build_day_events(day, day_data)

        if (
            not events
            and not day_data["tickets"]
            and not day_data["meetings"]
            and not day_data["email_analytics"]
            and not day_data["emails"]
            and not day_data["note_blob"]
        ):
            continue

        _line(html, f"<div class='day-block'><div class='day-header'>{escape(day)}</div>")

        if day_data["tickets"]:
            _line(html, "<div class='section-title'>Ticket Summary</div>")
            for t in day_data["tickets"]:
                source = str(t.get("source", ""))
                is_ado = "DevOps" in source
                b_style = "ticket-badge" if is_ado else "ticket-badge sn"
                tid = escape(str(t.get("id", "UNKNOWN")))
                title = escape(str(t.get("title", "Untitled")))
                ref = f"{'ADO' if is_ado else 'SN'} {str(t.get('id', 'UNKNOWN'))}"
                ref_url = str(t.get("url", "")).strip()
                ref_markup = f"<a href='{escape(ref_url, quote=True)}' target='_blank' rel='noreferrer'>{escape(ref)}</a>" if ref_url else escape(ref)
                desc = str(t.get("title", "")).strip()
                _line(html, f"<div class='activity-line'><span class='{b_style}'>{ref_markup}</span> {title}</div>")
                _line(
                    html,
                    (
                        "<div class='journal-row' data-kind='ticket' data-date='"
                        f"{_escape_attr(day)}' data-ref='{_escape_attr(ref)}' data-url='{_escape_attr(ref_url)}' data-attachment=''><input type='hidden' class='journal-desc' value='{_escape_attr(desc)}'></div>"
                    ),
                )
                total_rows += 1

        if events:
            _line(html, "<div class='section-title'>Chronological Activity</div>")
            for ev in events:
                kind = ev.get("kind", "note")
                ref = str(ev.get("ref", ""))
                summary = str(ev.get("summary", ""))
                ev_time = str(ev.get("time", "")).strip()
                time_markup = f"<span class='ts'>{escape(ev_time)}:</span> " if ev_time else ""

                if kind == "screenshot" and ev.get("screenshot"):
                    ss = ev["screenshot"]
                    image_src = escape(str(ss.get("dashboard_src", ss.get("path_uri", ""))), quote=True)
                    name = escape(str(ss.get("name", "screenshot")))
                    _line(html, "<div class='activity-line'>")
                    _line(html, f"{time_markup}{escape(summary)}")
                    _line(html, f"<img src='{image_src}' alt='{name}' loading='lazy'>")
                    _line(html, "</div>")
                    row_ref = f"Screenshot ({ref})"
                    row_attachment = str(ss.get("asset_name", "")).strip()
                else:
                    _line(html, f"<div class='activity-line'>{time_markup}{escape(summary)}</div>")
                    row_ref = "Note"
                    row_attachment = ""

                combined_summary = f"{ev_time + ': ' if ev_time else ''}{summary}".strip()
                _line(
                    html,
                    (
                        "<div class='journal-row' data-kind='"
                        f"{_escape_attr(kind)}' data-date='{_escape_attr(day)}' data-ref='{_escape_attr(row_ref)}' data-attachment='{_escape_attr(row_attachment)}'>"
                        f"<input type='hidden' class='journal-desc' value='{_escape_attr(combined_summary)}'></div>"
                    ),
                )
                total_rows += 1

        day_notes = _compose_daily_notes(day_data)
        if day_notes:
            _line(html, "<div class='section-title'>Daily Notes</div>")
            _line(html, f"<pre>{escape(day_notes)}</pre>")
            _line(
                html,
                (
                    "<div class='journal-row' data-kind='daily-notes' data-date='"
                    f"{_escape_attr(day)}' data-ref='Daily Notes' data-attachment=''><input type='hidden' class='journal-desc' value='{_escape_attr(day_notes)}'></div>"
                ),
            )
            total_rows += 1

        if day_data["meetings"]:
            _line(html, "<div class='section-title'>Meeting Minutes</div>")
            for mt in day_data["meetings"]:
                title = str(mt.get("inferred_title", "Meeting"))
                kb = str(mt.get("high_fidelity_kb", ""))
                _line(html, f"<div class='activity-line'><strong>{escape(title)}</strong></div>")
                _line(html, f"<pre>{escape(kb)}</pre>")
                _line(
                    html,
                    (
                        "<div class='journal-row' data-kind='meeting' data-date='"
                        f"{_escape_attr(day)}' data-ref='{_escape_attr(f'Meeting: {title}')}' data-attachment=''><input type='hidden' class='journal-desc' value='{_escape_attr(kb)}'></div>"
                    ),
                )
                total_rows += 1

        if day_data["email_analytics"]:
            _line(html, "<div class='section-title'>Daily Email Summary</div>")
            for item in day_data["email_analytics"]:
                summary = str(item.get("daily_summary", "")).strip() or "No daily summary captured."
                _line(html, f"<pre>{escape(summary)}</pre>")
                _line(
                    html,
                    (
                        "<div class='journal-row' data-kind='email-analytics' data-date='"
                        f"{_escape_attr(day)}' data-ref='Daily Email Summary' data-attachment=''><input type='hidden' class='journal-desc' value='{_escape_attr(summary)}'></div>"
                    ),
                )
                total_rows += 1

        _line(html, "</div>")

    _line(html, "</form></div>")

    _line(html, "<script>")
    _line(html, "function _normalizeMultiline(s) { return (s || '').replace(/\\r\\n/g, '\\n').replace(/\\r/g, '\\n').trim(); }")
    _line(html, "function _escapeMd(s) { return (s || '').replace(/\\|/g, '\\\\|'); }")
    _line(html, "function _appendMultilineBullet(lines, text, prefix) {")
    _line(html, "  const body = _normalizeMultiline(text);")
    _line(html, "  if (!body) { return false; }")
    _line(html, "  const parts = body.split('\\n');")
    _line(html, "  const first = _escapeMd(parts[0]);")
    _line(html, "  lines.push('- ' + (prefix ? prefix + first : first));")
    _line(html, "  for (let i = 1; i < parts.length; i += 1) { lines.push('  ' + _escapeMd(parts[i])); }")
    _line(html, "  return true;")
    _line(html, "}")
    _line(html, "function _downloadTextFile(filename, content) { const blob = new Blob([content], { type: 'text/plain;charset=utf-8' }); const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url); }")
    _line(html, "function compileJournal() {")
    _line(html, "  const rows = document.querySelectorAll('.journal-row');")
    _line(html, "  const lines = ['# Work Journal'];")
    _line(html, "  let count = 0;")
    _line(html, "  let currentDay = '';")
    _line(html, "  let currentSection = '';")
    _line(html, "  const sectionForKind = (kind, ref) => {")
    _line(html, "    if (kind === 'ticket') return 'Ticket Summary';")
    _line(html, "    if (kind === 'meeting') return 'Meeting Minutes';")
    _line(html, "    if (kind === 'email-analytics') return 'Daily Email Summary';")
    _line(html, "    if (kind === 'daily-notes') return 'Daily Notes';")
    _line(html, "    if (kind === 'screenshot' || kind === 'note') return 'Chronological Activity';")
    _line(html, "    if ((ref || '').startsWith('Screenshot (')) return 'Chronological Activity';")
    _line(html, "    if ((ref || '').startsWith('Meeting:')) return 'Meeting Minutes';")
    _line(html, "    if ((ref || '').startsWith('Daily Email Summary')) return 'Daily Email Summary';")
    _line(html, "    return 'Activity';")
    _line(html, "  };")
    _line(html, "  for (const row of rows) {")
    _line(html, "    const d = row.getAttribute('data-date') || ''; const k = row.getAttribute('data-kind') || ''; const r = row.getAttribute('data-ref') || ''; const u = row.getAttribute('data-url') || ''; const a = row.getAttribute('data-attachment') || '';")
    _line(html, "    const hidden = row.querySelector('.journal-desc');")
    _line(html, "    let s = hidden ? hidden.value : '';")
    _line(html, "    if (a) { s = '!'+a+'! ' + s; }")
    _line(html, "    s = _normalizeMultiline(s);")
    _line(html, "    if (!s) { continue; }")
    _line(html, "    const refCell = u ? '[' + _escapeMd(r) + '](' + u + ')' : _escapeMd(r);")
    _line(html, "    if (d !== currentDay) { currentDay = d; currentSection = ''; lines.push(''); lines.push('## ' + d); }")
    _line(html, "    const section = sectionForKind(k, r);")
    _line(html, "    if (section !== currentSection) { currentSection = section; lines.push('### ' + section); }")
    _line(html, "    let added = false;")
    _line(html, "    if (k === 'ticket') { added = _appendMultilineBullet(lines, s, refCell + ': '); }")
    _line(html, "    else if (k === 'screenshot' || k === 'note') { added = _appendMultilineBullet(lines, s, _escapeMd(r || 'Activity') + ': '); }")
    _line(html, "    else if (k === 'meeting' || k === 'email-analytics' || k === 'daily-notes') { added = _appendMultilineBullet(lines, s, ''); }")
    _line(html, "    else { added = _appendMultilineBullet(lines, s, ''); }")
    _line(html, "    if (added) { count += 1; }")
    _line(html, "  }")
    _line(html, "  const fileName = 'confluence_markup_' + new Date().toISOString().slice(0, 10) + '.md';")
    _line(html, "  _downloadTextFile(fileName, lines.join('\\n'));")
    _line(html, "  document.getElementById('genStatus').textContent = count + ' rows generated and downloaded.';")
    _line(html, "}")
    _line(html, "</script>")
    _line(html, "</body></html>")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(html))
    print(f"[✓] Dashboard compiled to: {output_file}")
    print(f"[✓] Estimated export rows available: {total_rows}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compile dashboard and downloadable Confluence markup")
    parser.add_argument("--days", type=int, default=31, help="Lookback window in days (default: 31)")
    parser.add_argument("--month", default="", help="Optional month scope in YYYY-MM (example: 2026-07)")
    parser.add_argument("--output", default=OUTPUT_DASHBOARD, help="Output dashboard HTML path")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    generate_dashboard(days=args.days, output_file=args.output, month=args.month or None)
