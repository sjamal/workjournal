import os
import json
import glob
import re
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
EMAIL_CACHE_FILE = os.path.join(CACHE_DIR, "emails_cache.json")

OUTLOOK_PROFILE_DIR = os.path.expanduser("~/Library/Group Containers/UBF8T346G9.Office/Outlook/Outlook 15 Profiles")
CUTOFF_DAYS = 30
START_DATE = datetime.now() - timedelta(days=CUTOFF_DAYS)

def fetch_new_outlook_emails():
    print("\n========================================")
    print("Deep Scanning New Outlook SQLite Message Containers")
    print("========================================")
    
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    # Locate all sqlite container files across your active Outlook user profile structure
    db_paths = glob.glob(os.path.join(OUTLOOK_PROFILE_DIR, "**", "*.sqlite"), recursive=True)
    if not db_paths:
        print("[!] Could not locate any Outlook SQLite cache files.")
        return
        
    print(f"[+] Found {len(db_paths)} internal database layers. Searching for message indexes...")
    parsed_emails = []
    ticket_pattern = re.compile(r'(INC\d+|REQ\d+|Task-\d+|US-\d+)', re.IGNORECASE)
    
    target_file = None
    target_table = None
    
    # Scan through every single database file found until we discover the correct table schema layer
    for db_file in db_paths:
        try:
            conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [r[0] for r in cursor.fetchall()]
            conn.close()
            
            # Cross-reference known table schemas used by Microsoft Outlook for messages
            for t_name in ["MessageRecords", "RecordTable", "Messages", "MailMessageRecords", "MailMessage"]:
                if t_name in tables:
                    target_file = db_file
                    target_table = t_name
                    break
            if target_file:
                break
        except:
            pass

    if not target_file or not target_table:
        print("[X] Database schema search exhausted. No message tables found.")
        print("[-] Try closing Outlook completely so its background sync logs flush onto disk.")
        return
        
    print(f"[✓] Target Found! File: {os.path.basename(os.path.dirname(target_file))}/{os.path.basename(target_file)}")
    print(f"[+] Extracting indices via table data layer: '{target_table}'")
    
    try:
        conn = sqlite3.connect(f"file:{target_file}?mode=ro", uri=True)
        cursor = conn.cursor()
        
        # Pull columns mapping absolute timeline markers and content strings
        cursor.execute(f"SELECT MailDate, SenderName, Subject FROM {target_table} ORDER BY MailDate DESC LIMIT 400;")
        rows = cursor.fetchall()
        
        for row in rows:
            raw_time, sender, subject = row[0], row[1], row[2]
            try:
                # Convert Microsoft absolute timestamp increments
                if raw_time > 100000000000:
                    raw_time = raw_time / 1000
                elif raw_time < 500000000:  # Adjust core Mac time tracking epoch offset
                    raw_time = raw_time + 978307200
                
                clean_date = datetime.fromtimestamp(raw_time).strftime("%Y-%m-%d")
                
                if clean_date >= START_DATE.strftime("%Y-%m-%d") and subject:
                    found_tickets = ticket_pattern.findall(str(subject))
                    ticket_str = ", ".join(set(found_tickets)) if found_tickets else "None"
                    
                    parsed_emails.append({
                        "date": clean_date,
                        "sender": str(sender),
                        "subject": str(subject),
                        "associated_tickets": ticket_str
                    })
            except:
                pass
                
        conn.close()
        
        # Apply deduplication lookup maps
        unique_emails = {item['subject']: item for item in parsed_emails}
        final_output = list(unique_emails.values())
        
        with open(EMAIL_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(final_output, f, indent=4)
        print(f"[✓] Success! Cached {len(final_output)} emails inside: {EMAIL_CACHE_FILE}")
        
    except Exception as e:
        print(f"[X] Internal database query processing failure: {e}")

if __name__ == "__main__":
    fetch_new_outlook_emails()
