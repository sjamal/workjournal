import os
import re
import glob
from datetime import datetime, timedelta
import subprocess

# --- Configuration ---
DAYS_AGO = 30
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")
BBEDIT_DIR = os.path.expanduser("~/Library/Application Support/BBEdit/Documents") # Adjust to your notes path
OUTPUT_HTML = os.path.expanduser("~/Desktop/work_journal_review.html")

start_date = datetime.now() - timedelta(days=DAYS_AGO)

# --- 1. Extract Outlook Emails via AppleScript ---
def get_outlook_emails(days):
    print("Fetching Outlook emails via AppleScript...")
    applescript = f'''
    tell application "Microsoft Outlook"
        set startDate to (current date) - ({days} * days)
        set mailLogs to ""
        try
            set inboxMessages to messages of inbox
            repeat with msg in inboxMessages
                if time received of msg_ge startDate then
                    set mailLogs to mailLogs & (time received of msg as text) & " | " & subject of msg & "\\n"
                end if
            end repeat
        end try
        return mailLogs
    end tell
    '''
    try:
        proc = subprocess.run(['osascript', '-e', applescript], capture_output=True, text=True, check=True)
        return proc.stdout
    except Exception as e:
        return f"Could not fetch Outlook emails: {e}"

email_data = get_outlook_emails(DAYS_AGO)

# --- 2. Scan Downloads for Screenshots & Extract Metadata ---
image_extensions = ('*.png', '*.jpg', '*.jpeg', '*.gif')
screenshots = []

for ext in image_extensions:
    for filepath in glob.glob(os.path.join(DOWNLOADS_DIR, ext)):
        mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
        if mtime > start_date:
            # Extract ticket numbers from filename if present
            tickets = re.findall(r'(INC\d+|REQ\d+|Task-\d+|US-\d+)', filepath, re.IGNORECASE)
            screenshots.append({
                "path": filepath,
                "name": os.path.basename(filepath),
                "date": mtime.strftime("%Y-%m-%d %H:%M:%S"),
                "tickets": ", ".join(tickets) if tickets else "None"
            })

# Sort screenshots chronologically
screenshots.sort(key=lambda x: x['date'])

# --- 3. Scan BBEdit Notes for Ticket References ---
bbedit_tickets = set()
if os.path.exists(BBEDIT_DIR):
    for filepath in glob.glob(os.path.join(BBEDIT_DIR, "*.txt")):
        try:
            with open(filepath, 'r', errors='ignore') as f:
                content = f.read()
                found = re.findall(r'(INC\d+|REQ\d+|Task-\d+|US-\d+)', content, re.IGNORECASE)
                bbedit_tickets.update(found)
        except Exception:
            pass

# --- 4. Generate Interactive HTML Review Sheet ---
html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Work Journal Review Dashboard</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; margin: 30px; background: #f4f5f7; color: #333; }}
        .container {{ max-width: 1100px; margin: 0 auto; }}
        .header {{ background: #fff; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .item-row {{ display: flex; background: #fff; margin-bottom: 20px; padding: 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .preview {{ flex: 1; max-width: 400px; padding-right: 20px; }}
        .preview img {{ max-width: 100%; border: 1px solid #ddd; border-radius: 4px; }}
        .details {{ flex: 2; display: flex; flex-direction: column; }}
        .metadata {{ font-size: 0.9em; color: #666; margin-bottom: 10px; }}
        textarea {{ width: 100%; height: 80px; margin-top: 10px; padding: 8px; border-radius: 4px; border: 1px solid #ccc; }}
        button {{ background: #0052cc; color: white; border: none; padding: 12px 24px; border-radius: 4px; cursor: pointer; font-size: 16px; font-weight: bold; }}
        button:hover {{ background: #0065ff; }}
        pre {{ background: #f4f5f7; padding: 10px; border-radius: 4px; font-size: 0.85em; overflow-x: auto; }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>Monthly Work Journal Compiler</h1>
        <p><strong>Detected BBEdit Tickets:</strong> {', '.join(bbedit_tickets) if bbedit_tickets else 'None Found'}</p>
    </div>

    <form id="journalForm">
"""

for idx, item in enumerate(screenshots):
    html_content += f"""
        <div class="item-row">
            <div class="preview">
                <img src="file://{item['path']}" alt="Screenshot">
                <div class="metadata"><strong>File:</strong> {item['name']}</div>
            </div>
            <div class="details">
                <div class="metadata">
                    <strong>Date Captured:</strong> {item['date']} | 
                    <strong>Filename Tickets:</strong> {item['tickets']}
                </div>
                <label><strong>Describe the benefit/task achieved here:</strong></label>
                <input type="hidden" name="date_{idx}" value="{item['date']}">
                <input type="hidden" name="tickets_{idx}" value="{item['tickets']}">
                <textarea name="summary_{idx}" placeholder="During this step, I resolved..."></textarea>
            </div>
        </div>
    """

html_content += """
        <button type="button" onclick="generateConfluenceMarkup()">Generate Confluence Code</button>
    </form>
    
    <div class="header" style="margin-top: 30px;">
        <h2>Recent Email Log (Reference)</h2>
        <pre>""" + email_data + """</pre>
    </div>

    <div id="outputSection" class="header" style="display:none; margin-top:30px;">
        <h2>Copy into Confluence (Storage HTML Macro)</h2>
        <textarea id="markupOutput" style="height: 300px; font-family: monospace;"></textarea>
    </div>
</div>

<script>
function generateConfluenceMarkup() {
    const form = document.getElementById('journalForm');
    const formData = new FormData(form);
    let htmlResult = "<table><thead><tr><th>Date</th><th>Associated Tickets</th><th>Accomplishment Summary</th></tr></thead><tbody>";
    
    // Process rows loop
    let idx = 0;
    while(formData.has('date_' + idx)) {
        let date = formData.get('date_' + idx);
        let tickets = formData.get('tickets_' + idx);
        let summary = formData.get('summary_' + idx);
        
        if(summary.trim() !== "") {
            htmlResult += `<tr><td>${date}</td><td>${tickets}</td><td>${summary}</td></tr>`;
        }
        idx++;
    }
    htmlResult += "</tbody></table>";
    
    document.getElementById('markupOutput').value = htmlResult;
    document.getElementById('outputSection').style.display = 'block';
    window.scrollTo(0, document.body.scrollHeight);
}
</script>
</body>
</html>
"""

with open(OUTPUT_HTML, 'w') as f:
    f.write(html_content)

print(f"Success! Open the dashboard on your desktop to begin reviewing: {OUTPUT_HTML}")

