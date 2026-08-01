#!/usr/bin/env python3

"""Compile an interactive dashboard for monthly work journal assembly."""

from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime, timedelta
from html import escape

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")
BBEDIT_DIR = os.path.expanduser("~/Documents/Personal/notes")

OUTPUT_DIR = os.path.join(BASE_DIR, "compilation")
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_DASHBOARD = os.path.join(OUTPUT_DIR, "work_journal_dashboard.html")

CUTOFF_DAYS = 30
START_DATE_OBJ = datetime.now() - timedelta(days=CUTOFF_DAYS)
START_DATE_STR = START_DATE_OBJ.strftime("%Y-%m-%d")


def load_cache_file(filename: str):
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


def parse_bbedit_time_contexts():
    time_logs = []
    if not os.path.exists(BBEDIT_DIR):
        return time_logs

    files = glob.glob(os.path.join(BBEDIT_DIR, "*.txt")) + glob.glob(os.path.join(BBEDIT_DIR, "*.markdown"))
    time_pattern = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?)", re.IGNORECASE)

    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                curr_dt = START_DATE_STR
                for line in f:
                    day_m = re.search(r"===\s*(\d{4}-\d{2}-\d{2})\s*===", line)
                    if day_m:
                        curr_dt = day_m.group(1).strip()
                        continue
                    t_m = time_pattern.findall(line)
                    if t_m and curr_dt >= START_DATE_STR:
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


def gather_screenshots(bbedit_logs, screenshot_summary_map):
    images = []
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        for fp in glob.glob(os.path.join(DOWNLOADS_DIR, ext)):
            mtime = os.path.getmtime(fp)
            if mtime < START_DATE_OBJ.timestamp():
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
                # Expanded matching window to improve auto-capture rate.
                if abs((dt_obj - parsed_dt).total_seconds()) <= 1800:
                    matched_snippet = log["text"]
                    break

            summary_key = f"{fp}|{int(mtime)}"
            ai_summary = screenshot_summary_map.get(summary_key, "")

            images.append(
                {
                    "type": "screenshot",
                    "path": fp,
                    "name": os.path.basename(fp),
                    "date": dt_str,
                    "timestamp": dt_obj,
                    "tickets": ", ".join(set(tks)) if tks else "Screenshot Evidence",
                    "inferred_context": matched_snippet,
                    "ai_summary": ai_summary,
                }
            )
    return images


def parse_bbedit_notes_for_sidebar():
    notes = {}
    if not os.path.exists(BBEDIT_DIR):
        return notes
    files = glob.glob(os.path.join(BBEDIT_DIR, "*.txt")) + glob.glob(os.path.join(BBEDIT_DIR, "*.markdown"))
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                chunks = re.split(r"===\s*(\d{4}-\d{2}-\d{2})\s*===", f.read())
                if len(chunks) > 1:
                    for i in range(1, len(chunks), 2):
                        dt = chunks[i].strip()
                        if dt >= START_DATE_STR:
                            notes[dt] = chunks[i + 1].strip()
        except Exception:
            pass
    return notes


def build_day_events(day, day_data):
    events = []

    # Chronological note events from timestamp fences.
    for log in day_data.get("note_logs", []):
        parsed_dt = log.get("parsed_dt")
        if parsed_dt is None:
            continue
        events.append(
            {
                "sort_ts": parsed_dt,
                "date": day,
                "time": parsed_dt.strftime("%H:%M"),
                "ref": "Note",
                "summary": log.get("text", "").strip(),
                "kind": "note",
            }
        )

    # Chronological screenshot events.
    for ss in day_data.get("screenshots", []):
        ts = ss.get("timestamp")
        summary = ss.get("inferred_context", "").strip() or ss.get("ai_summary", "").strip()
        if not summary:
            summary = "Screenshot captured. Add manual summary if needed."
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


def generate_dashboard():
    print("Compiling Complete 30-Day Unified Workspace...")

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

    bbedit_logs = parse_bbedit_time_contexts()
    notes_by_date = parse_bbedit_notes_for_sidebar()
    screenshots = gather_screenshots(bbedit_logs, screenshot_summary_map)

    timeline = {}
    for d in range(CUTOFF_DAYS + 1):
        day_str = (START_DATE_OBJ + timedelta(days=d)).strftime("%Y-%m-%d")
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

    html: list[str] = []
    _line(html, "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Journal</title><style>")
    _line(html, "body { font-family:sans-serif; background:#f4f5f7; color:#172b4d; padding:20px; }")
    _line(html, ".navbar { background:#0052cc; color:white; padding:15px; display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; border-radius:4px; }")
    _line(html, ".day-block { background:white; border:1px solid #b3bac5; border-radius:8px; padding:20px; margin-bottom:20px; }")
    _line(html, ".day-header { font-size:16px; font-weight:bold; color:#0052cc; border-bottom:2px solid #dfe1e6; padding-bottom:4px; margin-bottom:15px; }")
    _line(html, ".entry { border:1px solid #eee; border-radius:6px; padding:10px; margin-bottom:10px; background:#fafbfc; }")
    _line(html, ".entry-note { border-left:4px solid #0052cc; }")
    _line(html, ".entry-shot { border-left:4px solid #a54800; }")
    _line(html, ".ticket-badge { background:#eae6ff; color:#403294; padding:2px 4px; border-radius:3px; font-size:11px; font-weight:bold; }")
    _line(html, ".ticket-badge.sn { background:#e3fcef; color:#006644; }")
    _line(html, "textarea { width:100%; box-sizing:border-box; margin-top:5px; padding:6px; }")
    _line(html, "textarea.s-sum { min-height:80px; }")
    _line(html, "img { max-width:100%; max-height:220px; display:block; margin:5px 0; border:1px solid #ccc; }")
    _line(html, "pre { background:#f4f5f7; padding:10px; border-radius:4px; font-size:11px; max-height:220px; overflow-y:auto; white-space:pre-wrap; }")
    _line(html, "button { background:#0052cc; color:white; border:none; padding:10px 20px; border-radius:4px; font-weight:bold; cursor:pointer; }")
    _line(html, "</style></head><body>")

    _line(html, "<div class='navbar'><h1>Confluence Work Journal Compiler</h1><button type='button' onclick='compileJournal()'>Generate Confluence Output</button></div>")
    _line(html, "<div class='main-workspace'><form id='journalForm'>")

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

        _line(html, f"<div class='day-block'><div class='day-header'>📅 {escape(day)}</div>")

        # ADO/SNOW summary at top per request.
        if day_data["tickets"]:
            _line(html, "<div style='font-weight:bold; font-size:12px; margin-bottom:8px;'>🎟️ Ticket Summary</div>")
            for t in day_data["tickets"]:
                source = str(t.get("source", ""))
                is_ado = "DevOps" in source
                b_style = "ticket-badge" if is_ado else "ticket-badge sn"
                tid = escape(str(t.get("id", "UNKNOWN")))
                title = escape(str(t.get("title", "Untitled")))
                _line(html, f"<div style='padding:4px 0;'><span class='{b_style}'>{'ADO' if is_ado else 'SN'} {tid}</span> {title}</div>")

        # Chronological notes/screenshots interspersed.
        _line(html, "<div style='font-weight:bold; font-size:12px; margin-top:12px;'>🕒 Chronological Activity</div>")
        if not events:
            _line(html, "<div class='entry'>No timestamped notes/screenshots captured for this day.</div>")
        else:
            for ev in events:
                kind = ev.get("kind", "note")
                ref = escape(str(ev.get("ref", "")))
                summary = escape(str(ev.get("summary", "")))
                ev_time = escape(str(ev.get("time", "")))
                css = "entry-note" if kind == "note" else "entry-shot"

                _line(html, f"<div class='entry {css}'>")
                _line(html, f"<div style='font-size:11px; color:#5e6c84;'><strong>{ev_time}</strong> | {escape(kind.title())} | {ref}</div>")

                if kind == "screenshot" and ev.get("screenshot"):
                    ss = ev["screenshot"]
                    path = escape(str(ss.get("path", "")))
                    name = escape(str(ss.get("name", "screenshot")))
                    _line(html, f"<div style='font-size:11px; color:#666;'>📷 Asset: {name}</div><img src='file://{path}'>")
                    _line(html, f"<textarea class='s-sum'>{summary}</textarea>")
                else:
                    _line(html, f"<div>{summary}</div>")

                _line(html, f"<input type='hidden' class='entry-date' value='{escape(day)}'>")
                _line(html, f"<input type='hidden' class='entry-ref' value='{ref}'>")
                _line(html, f"<input type='hidden' class='entry-desc' value='{summary}'>")
                _line(html, "</div>")

        # Meeting minutes near bottom of day narrative.
        if day_data["meetings"]:
            _line(html, "<div style='font-weight:bold; font-size:12px; margin-top:12px;'>💡 Meeting Minutes</div>")
            for mt in day_data["meetings"]:
                title = escape(str(mt.get("inferred_title", "Meeting")))
                kb = escape(str(mt.get("high_fidelity_kb", "")))
                _line(html, f"<div class='entry entry-note'><div style='font-size:11px; color:#5e6c84;'><strong>Meeting</strong> | {title}</div><pre>{kb}</pre></div>")
                _line(html, f"<input type='hidden' class='entry-date' value='{escape(day)}'>")
                _line(html, f"<input type='hidden' class='entry-ref' value='Meeting: {title}'>")
                _line(html, f"<input type='hidden' class='entry-desc' value='{kb}'>")

        # Email analytics narrative summary at bottom of day.
        if day_data["email_analytics"]:
            _line(html, "<div style='font-weight:bold; font-size:12px; margin-top:12px;'>📊 Email Analytics Daily Summary</div>")
            for item in day_data["email_analytics"]:
                summary = escape(str(item.get("daily_summary", "")).strip() or "No daily summary captured.")
                _line(html, f"<div class='entry'><pre>{summary}</pre></div>")
                _line(html, f"<input type='hidden' class='entry-date' value='{escape(day)}'>")
                _line(html, "<input type='hidden' class='entry-ref' value='Email Analytics Summary'>")
                _line(html, f"<input type='hidden' class='entry-desc' value='{summary}'>")

        # Raw notes and inbox log reference blocks.
        if day_data["note_blob"]:
            _line(html, "<div style='font-weight:bold; font-size:12px; margin-top:12px;'>📝 Full Notes (Reference)</div>")
            _line(html, f"<pre>{escape(day_data['note_blob'])}</pre>")

        if day_data["emails"]:
            _line(html, "<div style='font-weight:bold; font-size:12px; margin-top:12px; color:#0747a6;'>✉️ Outlook Inbox Log (Reference)</div>")
            for mail in day_data["emails"]:
                sender = escape(str(mail.get("sender", "")))
                subject = escape(str(mail.get("subject", "")))
                assoc = escape(str(mail.get("associated_tickets", "None")))
                _line(html, f"<div class='entry'><strong>From:</strong> {sender} | {subject} <span style='color:#a54800; font-size:11px;'>({assoc})</span></div>")

        _line(html, "</div>")

    _line(html, "</form></div>")
    _line(html, "<div id='outBlock' style='display:none; background:#fff; border:1px solid #dfe1e6; border-radius:8px; padding:16px; margin-top:20px;'>")
    _line(html, "<h2 style='margin-top:0;'>Confluence Storage Format Output</h2>")
    _line(html, "<textarea id='rawX' style='width:100%; height:220px; box-sizing:border-box; font-family:monospace;'></textarea>")
    _line(html, "<div style='margin-top:10px;'><button type='button' onclick='copyXHTML()'>Copy Output</button></div>")
    _line(html, "</div>")

    _line(html, "<script>")
    _line(html, "function copyXHTML() { const ta = document.getElementById('rawX'); ta.select(); document.execCommand('copy'); alert('Copied output to clipboard.'); }")
    _line(html, "function compileJournal() {")
    _line(html, "  const dates = document.querySelectorAll('.entry-date');")
    _line(html, "  const refs = document.querySelectorAll('.entry-ref');")
    _line(html, "  const descs = document.querySelectorAll('.entry-desc');")
    _line(html, "  let out = '<h2>🗓️ Monthly Activity Log & Highlights</h2>'; ")
    _line(html, "  out += '<table border=\"1\" style=\"border-collapse:collapse; width:100%;\"><thead style=\"background-color:#f4f5f7;\"><tr><th>Date</th><th>Reference</th><th>Summary</th></tr></thead><tbody>'; ")
    _line(html, "  for (let i = 0; i < dates.length; i++) {")
    _line(html, "    const d = dates[i].value || ''; const r = refs[i].value || ''; const s = descs[i].value || '';")
    _line(html, "    if (s.trim() !== '') { out += '<tr><td><strong>' + d + '</strong></td><td>' + r + '</td><td>' + s.replace(/\\n/g, '<br/>') + '</td></tr>'; }")
    _line(html, "  }")
    _line(html, "  out += '</tbody></table>'; ")
    _line(html, "  document.getElementById('rawX').value = out;")
    _line(html, "  document.getElementById('outBlock').style.display = 'block';")
    _line(html, "}")
    _line(html, "</script>")
    _line(html, "</body></html>")

    with open(OUTPUT_DASHBOARD, "w", encoding="utf-8") as f:
        f.write("\n".join(html))
    print(f"[✓] Dashboard compiled perfectly to repo file: {OUTPUT_DASHBOARD}")


if __name__ == "__main__":
    generate_dashboard()
