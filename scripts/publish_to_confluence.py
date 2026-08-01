import os
import json
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

import requests # type: ignore
from requests.auth import HTTPBasicAuth  # type: ignore

load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
BBEDIT_NOTES_FILE = os.path.expanduser("~/Documents/Personal/notes/2026-notes.txt")

CUTOFF_DAYS = 30
START_DATE_OBJ = datetime.now() - timedelta(days=CUTOFF_DAYS)
START_DATE_STR = START_DATE_OBJ.strftime("%Y-%m-%d")

def load_cache_file(filename):
    path = os.path.join(CACHE_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return []

def parse_bbedit_journal_blocks():
    blocks = {}
    if not os.path.exists(BBEDIT_NOTES_FILE): return blocks
    with open(BBEDIT_NOTES_FILE, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    chunks = re.split(r'===\s*(\d{4}-\d{2}-\d{2})(?:,\s*\d{1,2}:\d{2}\s*[A-Z]{2})?\s*===', content, flags=re.IGNORECASE)
    if len(chunks) > 1:
        for i in range(1, len(chunks), 2):
            dt = chunks[i].strip()
            if dt >= START_DATE_STR:
                blocks.setdefault(dt, []).append(chunks[i+1].strip())
    return blocks

def build_confluence_page():
    tickets = load_cache_file("work_items_cache.json")
    meetings = load_cache_file("meeting_summaries_cache.json")
    notes_by_date = parse_bbedit_journal_blocks()

    # Create sorted chronological map rows array
    all_dates = sorted(list(set(list(notes_by_date.keys()) + [t.get("date_modified", "")[:10] for t in tickets if t.get("date_modified")])))

    xhtml = ["<h2>🗓️ Integrated Monthly Operational Log</h2>"]
    xhtml.append("<p><em>Generated programmatically from offline operational databases and BBEdit scratchpads.</em></p>")
    xhtml.append("<table data-layout='full-width' border='1'><thead><tr><th>Date</th><th>Reference Tracking</th><th>Task Accomplishment Summary</th></tr></thead><tbody>")

    for day in all_dates:
        if day < START_DATE_STR: continue
        
        # 1. Process System Tickets matching date
        for t in tickets:
            if t.get("date_modified", "")[:10] == day:
                is_ado = "DevOps" in t["source"]
                color = "#403294" if is_ado else "#006644"
                lbl = "ADO" if is_ado else "SN"
                xhtml.append(f"<tr><td><strong>{day}</strong></td><td><span style='color:{color}; font-weight:bold;'>{lbl} {t['id']}</span></td><td>Resolved engineering task details for: {t['title']}</td></tr>")
        
        # 2. Process Manual Notes & Scraped Browser Conversations matching date
        if day in notes_by_date:
            for note_text in notes_by_date[day]:
                clean_note = note_text.replace('\n', '<br/>')
                xhtml.append(f"<tr><td><strong>{day}</strong></td><td><span style='color:#a54800; font-weight:bold;'>Scratchpad Log</span></td><td>{clean_note}</td></tr>")

    xhtml.append("</tbody></table>")

    # Append KT Meetings sections below the main grid
    if meetings:
        xhtml.append("<h2>💡 Technical Knowledge Transfer Reference Sheets</h2>")
        for mt in sorted(meetings, key=lambda x: x.get('date', '')):
            if mt.get('date', '') >= START_DATE_STR:
                kb_body = mt['high_fidelity_kb'].replace('\n', '<br/>')
                xhtml.append(f"<div style='background-color:#fafbfc; border-left:4px solid #0052cc; padding:15px; margin-bottom:20px;'><h3>{mt['inferred_title']} ({mt['date']})</h3><p>{kb_body}</p></div>")

    return "\n".join(xhtml)

def publish_page():
    url = f"{os.getenv('CONFLUENCE_URL')}/rest/api/content"
    auth = HTTPBasicAuth(os.getenv("CONFLUENCE_EMAIL"), os.getenv("CONFLUENCE_TOKEN"))
    page_html = build_confluence_page()
    
    payload = {
        "type": "page",
        "title": os.getenv("CONFLUENCE_TITLE"),
        "space": {"key": os.getenv("CONFLUENCE_SPACE")},
        "body": {"storage": {"value": page_html, "representation": "storage"}}
    }
    
    print("\n[+] Pushing formatted operational journal directly to Confluence API...")
    response = requests.post(url, json=payload, auth=auth, headers={"Content-Type": "application/json"})
    # UPDATE LINE 92 TO ACCEPT BOTH CODES:
    if response.status_code in [200, 201]:
        print(f"[✓] Success! Transaction Accepted by Confluence (Status: {response.status_code})")
        try:
            print(f"[+] Page Link: {os.getenv('CONFLUENCE_URL')}/pages/viewpage.action?pageId={response.json().get('id')}")
        except:
            print("[+] Page created. Check your target corporate space timeline to verify background rendering.")
    else:
        print(f"[X] Confluence API Block ({response.status_code}): {response.text}")

if __name__ == "__main__":
    publish_page()
