def fetch_servicenow():
    # Targets the specific JSON file exported to your Downloads folder
    export_file = os.path.expanduser("~/Downloads/incident.json")
    
    if not os.path.exists(export_file):
        print(f"\n[!] Skipping ServiceNow: '{export_file}' not found.")
        print("[-] Ensure you exported your records from the browser as JSON.")
        return []

    print("\nReading ServiceNow data from local JSON export...")
    parsed_tickets = []

    try:
        with open(export_file, 'r') as f:
            data = json.load(f)
        
        # ServiceNow list exports wrap records in a top-level list or a 'result' key
        records = data.get("result", data) if isinstance(data, dict) else data
        
        if not isinstance(records, list):
            print("[X] Unexpected JSON structure inside incident.json.")
            return []

        for record in records:
            # Map the attributes out safely using standard JSON dictionary keys
            ticket_id = record.get('number', {}).get('display_value', record.get('number', 'UNKNOWN'))
            short_desc = record.get('short_description', {}).get('display_value', record.get('short_description', 'No Description'))
            sys_id = record.get('sys_id', {}).get('value', record.get('sys_id', ''))
            updated = record.get('sys_updated_on', {}).get('display_value', record.get('sys_updated_on', 'Unknown'))
            state = record.get('state', {}).get('display_value', record.get('state', 'Unknown'))
            
            parsed_tickets.append({
                "source": "ServiceNow (INC)",
                "id": ticket_id,
                "type": "Incident",
                "title": short_desc,
                "state": state, 
                "date_modified": updated,
                "url": f"https://{os.getenv('SN_INSTANCE', 'uthrprod')}://{sys_id}"
            })
                
        print(f"[+] Successfully extracted {len(parsed_tickets)} records from incident.json.")
        return parsed_tickets

    except Exception as e:
        print(f"[X] Exception parsing ServiceNow local JSON: {e}")
        return []
