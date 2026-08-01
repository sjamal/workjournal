#!/usr/bin/env python3

"""Extract useful Teams snippets from support-log bundles into local cache.

Purpose:
- Parse recent MSTeams support-log exports in Downloads and build
    cache/teams_chats_cache.json with likely conversational lines.

How to run:
- ./venv/bin/python scripts/fetch_teams_logs.py
"""

import os
import json
import re
import glob
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")
TEAMS_CACHE_FILE = os.path.join(CACHE_DIR, "teams_chats_cache.json")

def find_extracted_teams_directory():
    search_pattern = os.path.join(DOWNLOADS_DIR, "MSTeams Support Logs *")
    matching_dirs = glob.glob(search_pattern)
    if not matching_dirs:
        return None
    matching_dirs.sort(key=os.path.getmtime, reverse=True)
    return matching_dirs[0] if matching_dirs else None

def parse_teams_log_bundle():
    os.makedirs(CACHE_DIR, exist_ok=True)
    target_dir = find_extracted_teams_directory()
    
    if not target_dir:
        print("[!] Teams folder matching pattern not discovered yet.")
        return

    print(f"\nPerforming Scan on Bundle: {os.path.basename(target_dir)}")
    
    log_files = []
    for ext in ["*.txt", "*.log", "*.json"]:
        log_files.extend(glob.glob(os.path.join(target_dir, "**", ext), recursive=True))

    captured_elements = []
    ticket_pattern = re.compile(r'(INC\d+|REQ\d+|Task-\d+|US-\d+)', re.IGNORECASE)

    for log_path in log_files:
        # Ignore raw telemetry, lock, and system execution trace files completely
        log_lower = log_path.lower()
        if any(x in log_lower for x in ["telemetry", "skype", "app_side", "watchdog", "crash"]):
            continue
            
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # STRICT CRITERIA: Skip system lines containing pointers, hex code, or framework flags
                    if any(x in line for x in ["<INFO>", "<WARN>", "<ERROR>", "0x000", "native_modules", "crosscloud"]):
                        continue
                        
                    tickets = ticket_pattern.findall(line)
                    # Look for markers indicating a human conversational text payload string
                    if tickets or any(kw in line.lower() for kw in ["messagecontent", "chattext", "displayname"]):
                        stat = os.stat(log_path)
                        date_str = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d")
                        
                        clean_line = line.strip()
                        # Clean out common JSON wrappers if present
                        msg_match = re.search(r'"(content|text|body|message)"\s*:\s*"([^"]+)"', clean_line, re.IGNORECASE)
                        
                        snippet = msg_match.group(2) if msg_match else clean_line
                        
                        if len(snippet) > 15 and len(snippet) < 300:
                            captured_elements.append({
                                "source": "Teams Chat Trace",
                                "date": date_str,
                                "snippet": snippet,
                                "associated_tickets": ", ".join(set(tickets)) if tickets else "None"
                            })
        except Exception:
            pass

    # Unique filter using a mapping dictionary
    unique_map = {item['snippet']: item for item in captured_elements}
    output = list(unique_map.values())

    with open(TEAMS_CACHE_FILE, 'w') as f:
        json.dump(output, f, indent=4)
    print(f"[✓] Teams cache successfully populated with {len(output)} clean conversational log rows.")

if __name__ == "__main__":
    parse_teams_log_bundle()
