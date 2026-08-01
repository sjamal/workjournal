import os
import glob
import re
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")
BBEDIT_NOTES_FILE = os.path.expanduser("~/Documents/Personal/notes/2026-notes.txt")
OUTPUT_TEXT_FILE = os.path.join(BASE_DIR, "compilation", "confluence_markup.txt")

def parse_journal_timeline():
    if not os.path.exists(BBEDIT_NOTES_FILE):
        print(f"[X] Notes file not found: {BBEDIT_NOTES_FILE}")
        return

    print("Processing notes and cross-referencing screenshot windows...")
    
    with open(BBEDIT_NOTES_FILE, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Split notes cleanly by your automated timestamp fence headings
    chunks = re.split(r'===\s*(\d{4}-\d{2}-\d{2}),\s*(\d{1,2}:\d{2}\s*[A-Z]{2})\s*===', content, flags=re.IGNORECASE)
    
    bbedit_blocks = []
    if len(chunks) > 1:
        for i in range(1, len(chunks), 3):
            date_str = chunks[i].strip()
            time_str = chunks[i+1].strip()
            text_block = chunks[i+2].strip()
            
            # Use raw string combinations for matching to eliminate floating timezone calculation gaps
            time_clean = time_str.upper().replace(" ", "")
            bbedit_blocks.append({
                "date": date_str,
                "time_match_key": f"{date_str} {time_clean}",
                "text": text_block
            })

    screenshots = []
    thirty_days_ago = datetime.now().timestamp() - (30 * 86400)
    ticket_pattern = re.compile(r'(INC\d+|REQ\d+|Task-\d+|US-\d+)', re.IGNORECASE)

    for ext in ("*.png", "*.jpg", "*.jpeg"):
        for fp in glob.glob(os.path.join(DOWNLOADS_DIR, ext)):
            mtime = os.path.getmtime(fp)
            if mtime >= thirty_days_ago:
                dt_obj = datetime.fromtimestamp(mtime)
                dt_str = dt_obj.strftime("%Y-%m-%d")
                
                # Generate matching string keys for 15 minutes before and after the screenshot mtime
                valid_keys = []
                for offset in range(-15, 16):
                    check_time = dt_obj + timedelta(minutes=offset)
                    valid_keys.append(check_time.strftime("%Y-%m-%d %I:%M%p").upper())

                # Strict checking execution loop
                matched_text = ""
                for block in bbedit_blocks:
                    if block["time_match_key"] in valid_keys:
                        matched_text = block["text"]
                        break
                
                # Extract ticket IDs directly from your web-scraped emails or note text
                tickets_found = ticket_pattern.findall(matched_text) if matched_text else []
                if not tickets_found:
                    tickets_found = ticket_pattern.findall(os.path.basename(fp))
                    
                ticket_reference = ", ".join(set(tickets_found)) if tickets_found else "Screenshot Evidence"

                # If no precision window text match occurred, force the cell to remain blank for your manual entry
                summary_output = matched_text.strip() if matched_text else ""

                screenshots.append({
                    "date": dt_str,
                    "timestamp": mtime,
                    "reference": ticket_reference,
                    "summary": summary_output
                })

    # Sort chronology: Oldest First
    screenshots.sort(key=lambda x: x["timestamp"])

    # Build the Confluence Wiki Markup Table
    markup = ["||Date||Ticket / Reference Tracing||Operational Accomplishment Summary||"]
    for ss in screenshots:
        # Clear out single-line break fragments to preserve Confluence table alignment cells
        clean_summary = ss["summary"].replace("\n", " ").replace("\r", " ").replace("|", " ")
        if not clean_summary:
            clean_summary = " " # Leave blank cell for manual completion inside Confluence
        markup.append(f"|{ss['date']}|* {ss['reference']} *|{clean_summary}|")

    os.makedirs(os.path.dirname(OUTPUT_TEXT_FILE), exist_ok=True)
    with open(OUTPUT_TEXT_FILE, "w", encoding="utf-8") as out_f:
        out_f.write("\n".join(markup))
        
    print(f"\n[✓] Success! Confluence table code compiled at: {OUTPUT_TEXT_FILE}")
    print("[-] Open this file in BBEdit, copy the text, and paste it inside Confluence via Insert -> Markup.")

if __name__ == "__main__":
    parse_journal_timeline()
