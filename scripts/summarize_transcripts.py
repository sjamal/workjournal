import os
import json
import glob
import re
import requests
import shutil
from datetime import datetime

# --- Configurations ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSCRIPTS_DIR = "transcripts"
CACHE_DIR = os.path.join(BASE_DIR, "cache")
MEETING_CACHE_FILE = os.path.join(CACHE_DIR, "meeting_summaries_cache.json")
OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3"

def parse_filename_metadata(filename):
    """
    Extracts dates like YYYY-MM-DD or YYYYMMDD from anywhere in the filename,
    then cleans up the remaining string into a human-readable title.
    """
    base_name, _ = os.path.splitext(filename)
    
    # Matches YYYY-MM-DD, YYYYMMDD, or DD-MM-YYYY anywhere inside the filename.
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})|(\d{8})|(\d{2}-\d{2}-\d{4})', base_name)
    
    extracted_date = datetime.now().strftime("%Y-%m-%d") # Default backup date
    clean_title = base_name

    if date_match:
        raw_date = date_match.group(0)
        try:
            if "-" in raw_date:
                if re.match(r'^\d{4}-\d{2}-\d{2}$', raw_date):
                    parsed_dt = datetime.strptime(raw_date, "%Y-%m-%d")
                else:
                    parsed_dt = datetime.strptime(raw_date, "%d-%m-%Y")
            else:
                parsed_dt = datetime.strptime(raw_date, "%Y%m%d")
            extracted_date = parsed_dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
        
        # Strip the date and any dangling separators out of the title string
        clean_title = base_name.replace(raw_date, "").strip("_").strip("-")
    
    # Convert underscores/hyphens to spaces and apply Title Case
    clean_title = re.sub(r'[_|-]+', ' ', clean_title).strip().title()
    return clean_title, extracted_date

def save_and_archive_cache(new_data):
    """
    Saves data to master cache file, and creates a timestamped mirror backup file.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    # 1. Read existing cache data if present to prevent overwriting historic logs
    existing_data = []
    if os.path.exists(MEETING_CACHE_FILE):
        try:
            with open(MEETING_CACHE_FILE, 'r') as f:
                existing_data = json.load(f)
        except Exception:
            pass

    # 2. Merge data matching by filename to prevent duplicates
    existing_map = {item['file_name']: item for item in existing_data}
    for item in new_data:
        existing_map[item['file_name']] = item # Overwrites if file updated, appends if brand new
        
    merged_list = list(existing_map.values())

    # 3. Write Master Cache File
    with open(MEETING_CACHE_FILE, 'w') as f:
        json.dump(merged_list, f, indent=4)
        
    # 4. Write Timestamped Backup Mirror
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    timestamped_filename = f"meeting_summaries_cache_{timestamp}.json"
    timestamped_path = os.path.join(CACHE_DIR, timestamped_filename)
    
    shutil.copy2(MEETING_CACHE_FILE, timestamped_path)
    print(f"\n[✓] Master cache updated: {MEETING_CACHE_FILE}")
    print(f"[✓] Timestamped historical copy archived: {timestamped_path}")

# (Keep read_transcript_file and summarize_kt_with_ollama exactly the same as previous response)
def read_transcript_file(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f: return f.read()

def summarize_kt_with_ollama(text, meeting_title):
    prompt = f"You are a Staff Technical Writer compiling an engineering Knowledge Base. Analyze the following Knowledge Transfer (KT) session transcript for '{meeting_title}'. Format your response using clear markdown subsections for Core Architecture, Institutional FAQs, and Next Steps/Commands.\n\nTRANSCRIPT:\n{text[:9000]}"
    payload = {"model": MODEL_NAME, "prompt": prompt, "stream": False}
    try:
        response = requests.post(OLLAMA_API_URL, json=payload, timeout=120)
        return response.json().get("response", "").strip() if response.status_code == 200 else "Ollama error"
    except Exception as e: return f"Error: {e}"

def process_all_transcripts():
    files = glob.glob(os.path.join(TRANSCRIPTS_DIR, "*.txt"))
    if not files:
        print("[!] No transcript text files found.")
        return
    
    new_summaries = []
    for filepath in files:
        filename = os.path.basename(filepath)
        content = read_transcript_file(filepath)
        if not content.strip(): continue
            
        meeting_title, meeting_date = parse_filename_metadata(filename)
        print(f"[+] Processing: {filename} -> {meeting_title} ({meeting_date})")
        
        deep_summary = summarize_kt_with_ollama(content, meeting_title)
        new_summaries.append({
            "source": "Knowledge Transfer Transcript",
            "file_name": filename,
            "inferred_title": meeting_title,
            "date": meeting_date,
            "high_fidelity_kb": deep_summary
        })
        
    save_and_archive_cache(new_summaries)

if __name__ == "__main__":
    process_all_transcripts()
