import os
import json
import base64
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv

# Load secret credentials from the local .env file
load_dotenv()

# --- Configurations & Constants ---
DAYS_AGO = 30
CACHE_FILE = "work_items_cache.json"
START_DATE = (datetime.now() - timedelta(days=DAYS_AGO)).strftime("%Y-%m-%d")

# ADO Env Vars
ADO_ORG = os.getenv("ADO_ORG")
ADO_PROJECT = os.getenv("ADO_PROJECT")
ADO_PAT = os.getenv("ADO_PAT")

# ServiceNow Env Vars
SN_INSTANCE = os.getenv("SN_INSTANCE")
#SN_USER = os.getenv("SN_USER")
#SN_PASSWORD = os.getenv("SN_PASSWORD")
#SN_COOKIE = os.getenv("SN_COOKIE") # Fallback cookie support for strict SSO environments

# --- Helper: Save Output Cache ---
def save_to_cache(data):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=4)
        print(f"\n[✓] Success! Local cache written safely to: {os.path.abspath(CACHE_FILE)}")
    except Exception as e:
        print(f"[X] Failed writing data to local cache: {e}")

# --- Module 1A: Azure DevOps Boards Fetcher ---
def fetch_azure_devops():
    if not all([ADO_ORG, ADO_PROJECT, ADO_PAT]):
        print("[!] Skipping Azure DevOps: Missing credentials in .env file.")
        return []

    print("\nConnecting to Azure DevOps Boards...")
    
    # ADO uses HTTP Basic Authentication with an empty username and the PAT as the password
    user_pass = f":{ADO_PAT}"
    b64_auth = base64.b64encode(user_pass.encode()).decode()
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/json"
    }

    # WIQL Query targeting items assigned to you or changed in the last 30 days
    # Note: '@me' natively targets your authenticated token profile
    wiql_url = f"https://dev.azure.com/{ADO_ORG}/{ADO_PROJECT}/_apis/wit/wiql?api-version=7.1"
    query_payload = {
        "query": f"""
        SELECT [System.Id], [System.Title], [System.WorkItemType], [System.State], [System.ChangedDate] 
        FROM WorkItems 
        WHERE [System.AreaPath] UNDER '{ADO_PROJECT}' 
          AND [System.ChangedDate] >= '{START_DATE}'
          AND ([System.AssignedTo] = @me OR [System.ChangedBy] = @me)
        ORDER BY [System.ChangedDate] DESC
        """
    }

    try:
        # Step 1: Execute query to get a list of target IDs
        response = requests.post(wiql_url, json=query_payload, headers=headers)
        if response.status_code != 200:
            print(f"[X] ADO Query Error ({response.status_code}): {response.text}")
            return []

        work_items_refs = response.json().get("workItems", [])
        if not work_items_refs:
            print("[-] No recent Azure DevOps items found.")
            return []

        item_ids = [str(item["id"]) for item in work_items_refs]
        print(f"[+] Found {len(item_ids)} work item references. Hydrating details...")

        # Step 2: Batch request details for all discovered IDs (Max 200 per batch per API rules)
        details_url = f"https://dev.azure.com/{ADO_ORG}/_apis/wit/workitems?ids={','.join(item_ids)}&api-version=7.1"
        details_response = requests.get(details_url, headers=headers)
        
        parsed_items = []
        for item in details_response.json().get("value", []):
            fields = item.get("fields", {})
            parsed_items.append({
                "source": "Azure DevOps",
                "id": str(item.get("id")),
                "type": fields.get("System.WorkItemType"),
                "title": fields.get("System.Title"),
                "state": fields.get("System.State"),
                "date_modified": fields.get("System.ChangedDate"),
                "url": item.get("_links", {}).get("html", {}).get("href")
            })
        return parsed_items

    except Exception as e:
        print(f"[X] Exception encountered fetching from ADO: {e}")
        return []

# --- Module 1B: ServiceNow Table Fetcher ---
def fetch_servicenow():
    # Targets the file downloaded from your browser. Change name if it is 'caller_history.json'
    possible_files = ["incident.json", "caller_history.json"]
    export_file = None
    
    for filename in possible_files:
        path = os.path.expanduser(f"./incidents/{filename}")
        if os.path.exists(path):
            export_file = path
            break
            
    if not export_file:
        print(f"\n[!] Skipping ServiceNow: No matching JSON export file found in ./incidents.")
        return []

    print(f"\nReading ServiceNow data from: {os.path.basename(export_file)}...")
    parsed_tickets = []

    try:
        with open(export_file, 'r') as f:
            data = json.load(f)
        
        # --- Flexible Structure Parser ---
        records = []
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            if "result" in data:
                records = data["result"]
            elif "records" in data:
                records = data["records"]
            elif "rows" in data:
                records = data["rows"]
            else:
                # If it's a flat dictionary mapping keys to item objects
                records = list(data.values())

        if not isinstance(records, list):
            # Final fallback: if data is a dict representing just one item, wrap it in a list
            if isinstance(data, dict) and any(k in data for k in ['number', 'sys_id', 'short_description']):
                records = [data]
            else:
                print(f"[X] Error: Could not extract record array from JSON object keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                return []

        for record in records:
            if not isinstance(record, dict):
                continue
                
            # Extract attributes dynamically out of the native JSON dictionary keys
            ticket_id = record.get('number', record.get('id', 'UNKNOWN'))
            short_desc = record.get('short_description', record.get('title', record.get('description', 'No Description')))
            sys_id = record.get('sys_id', record.get('uid', ''))
            updated = record.get('sys_updated_on', record.get('updated_at', record.get('sys_created_on', 'Unknown')))
            state = record.get('state', record.get('status', 'Unknown'))
            
            # Unpack sub-objects if they are represented as sub-dictionaries
            if isinstance(ticket_id, dict): ticket_id = ticket_id.get('display_value', 'UNKNOWN')
            if isinstance(short_desc, dict): short_desc = short_desc.get('display_value', 'No Description')
            if isinstance(sys_id, dict): sys_id = sys_id.get('value', '')
            if isinstance(updated, dict): updated = updated.get('display_value', 'Unknown')
            if isinstance(state, dict): state = state.get('display_value', 'Unknown')

            parsed_tickets.append({
                "source": "ServiceNow (INC)",
                "id": str(ticket_id),
                "type": "Incident",
                "title": str(short_desc),
                "state": str(state), 
                "date_modified": str(updated),
                "url": f"https://{SN_INSTANCE}.service-now.com{sys_id}"
            })
                
        print(f"[+] Successfully extracted {len(parsed_tickets)} records from your ServiceNow download!")
        return parsed_tickets

    except Exception as e:
        print(f"[X] Exception parsing ServiceNow local JSON: {e}")
        return []

# --- Main Runtime Workflow ---
if __name__ == "__main__":
    print("========================================")
    print("Starting Module 1: Corporate API Fetcher")
    print("========================================")
    
    all_tickets = []
    
    # Execute Tasks
    all_tickets.extend(fetch_azure_devops())
    all_tickets.extend(fetch_servicenow())
    
    # Save directly to disk
    save_to_cache(all_tickets)
