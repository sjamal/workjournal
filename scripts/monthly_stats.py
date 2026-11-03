#!/usr/bin/env python3

"""Build the Monthly Statistics section for a workjournal Confluence page.

Purpose:
- Summarize a month at a glance: tickets by source and theme, meetings, screenshots,
  note days, and email digest totals (action items, PRs, recurring alerts, projects).
- Ticket, meeting and screenshot counts come from the page storage itself, so they match
  what is published (including hand edits) and work for past months whose ticket cache
  has since been replaced. Email figures come from email_analytics_daily_cache.json.

How to run:
- ./venv/bin/python scripts/monthly_stats.py --month 2026-10 --storage page.xml   # print the section
- publish_to_confluence.py adds it to full publishes; splice_meeting_summaries.py --stats
  adds or refreshes it on an existing page.
"""

from __future__ import annotations

import argparse
import collections
import html
import json
import os
import re
from html import escape

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMAIL_CACHE = os.path.join(BASE_DIR, "cache", "email_analytics_daily_cache.json")
STATS_HEADING = "Monthly Statistics"
STANDARD_SECTIONS = {"Ticket Summary", "Chronological Activity", "Daily Notes", "Daily Email Summary"}

# First matching theme wins; tune the patterns to match how tickets are titled.
THEMES = [
    ("OS patching & upgrades", r"SLES ?15\.\d|Win updates|Ubuntu \d\d|OS maintenance"),
    ("Certificate renewals", r"\bRenew\b|cert renewal|TLS certificate"),
    ("Configuration management", r"puppet|ansible"),
    ("Platform engineering", r"SUMA|MLM|SLES ?16|Gen2|CLM|upgrade .* to \d"),
    ("Identity, secrets & access", r"App Reg|secret|Off-board|SPN|service principal|Terraform|grouper|password|stale context|Key ?Vault|access to"),
    ("Network security", r"NSG|firewall|network connection|private endpoint"),
    ("Security & vulnerability", r"CVE|MDC|Defender|Crowdstrike|security note|should prevent|should be associated|block public access"),
]


def _heading_text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def strip_stats(storage: str) -> str:
    """Remove an existing Monthly Statistics section (heading up to the next h2)."""
    match = re.search(rf"<h2[^>]*>\s*{STATS_HEADING}\s*</h2>", storage)
    if not match:
        return storage
    following = re.search(r"<h2[^>]*>", storage[match.end():])
    end = match.end() + following.start() if following else len(storage)
    return storage[:match.start()] + storage[end:]


def page_stats(storage: str) -> dict:
    storage = strip_stats(storage)
    tickets: dict[str, str] = {}
    for ref, title in re.findall(r">((?:ADO|SN) [A-Z]*\d+)</a>:\s*([^<]+)", storage):
        tickets.setdefault(ref, html.unescape(title).strip())
    # Calendar replies sometimes arrive as ServiceNow items; they aren't incidents.
    tickets = {ref: title for ref, title in tickets.items() if not title.startswith("Accepted:")}

    themes = collections.Counter()
    for title in tickets.values():
        themes[next((name for name, pattern in THEMES if re.search(pattern, title, re.I)), "Application & other support")] += 1

    h4 = [_heading_text(m) for m in re.findall(r"<h4[^>]*>(.*?)</h4>", storage, re.S)]
    return {
        "ado": sum(ref.startswith("ADO ") for ref in tickets),
        "incidents": sum(ref.startswith("SN INC") for ref in tickets),
        "changes": sum(ref.startswith("SN CHG") for ref in tickets),
        "themes": themes,
        "meetings": sum(title not in STANDARD_SECTIONS for title in h4),
        "note_days": h4.count("Daily Notes"),
        "screenshots": storage.count("<ac:image"),
    }


def _section(text: str, name: str) -> list[str]:
    match = re.search(rf"^{name}:\s*\n((?:- .*\n?)*)", text, re.M)
    return [line[2:].strip() for line in match.group(1).splitlines()] if match else []


def email_stats(month: str, cache_file: str = EMAIL_CACHE) -> dict:
    try:
        with open(cache_file) as handle:
            days = [d for d in json.load(handle) if str(d.get("date", "")).startswith(month)]
    except (OSError, ValueError):
        days = []
    totals, projects, alerts = collections.Counter(), collections.Counter(), set()
    actions: list[str] = []
    for day in days:
        text = str(day.get("daily_summary", ""))
        for line in _section(text, "Summary"):
            key, _, value = line.partition(":")
            if value.strip().isdigit():
                totals[key.strip()] += int(value)
        for line in _section(text, "Project Activity"):
            key, _, value = line.rpartition(":")
            if value.strip().isdigit():
                projects[key.strip()] += int(value)
        actions += _section(text, "Action Required")
        for line in _section(text, "Awareness"):
            alert = re.match(r"Recurring alert: (.+?) \(fired", line)
            if alert:
                alerts.add(alert.group(1))
    return {
        "days": len(days),
        "emails": totals["Emails"],
        "threads": totals["Threads"],
        "action_items": len(actions),
        "incident_notices": sum(bool(re.search(r"INC\d+ (assigned|has been updated)", a)) for a in actions),
        "pull_requests": sum(a.startswith("PR -") for a in actions),
        "projects": projects,
        "recurring_alerts": sorted(alerts),
    }


def _table(rows: list[tuple[str, object]]) -> str:
    body = "".join(f"<tr><th>{escape(str(k))}</th><td>{escape(str(v))}</td></tr>" for k, v in rows)
    return f"<table><tbody>{body}</tbody></table>"


def render_stats(month: str, storage: str, cache_file: str = EMAIL_CACHE) -> str:
    page, mail = page_stats(storage), email_stats(month, cache_file)
    parts = [f"<h2>{STATS_HEADING}</h2>", "<h4>Overview</h4>", _table([
        ("Azure DevOps items", page["ado"]),
        ("ServiceNow incidents", page["incidents"]),
        ("ServiceNow changes", page["changes"]),
        ("Meetings summarized", page["meetings"]),
        ("Days with notes", page["note_days"]),
        ("Screenshots", page["screenshots"]),
        ("Emails processed", mail["emails"]),
        ("Action-required items", mail["action_items"]),
        ("Pull requests", mail["pull_requests"]),
        ("Incident notifications", mail["incident_notices"]),
    ])]
    if page["themes"]:
        parts += ["<h4>Work by Theme</h4>", _table(page["themes"].most_common())]
    if mail["projects"]:
        parts += ["<h4>Email Activity by Project</h4>", _table(mail["projects"].most_common(8))]
    if mail["recurring_alerts"]:
        parts += ["<h4>Recurring Alerts</h4>", "<ul>" + "".join(f"<li>{escape(a)}</li>" for a in mail["recurring_alerts"]) + "</ul>"]
    parts.append(
        "<p><em>Tickets are distinct items modified this month, not necessarily completed. "
        f"Email figures cover {mail['days']} digest days and depend on how much mail was exported.</em></p>"
    )
    return "\n".join(parts) + "\n"


def with_stats(storage: str, month: str, cache_file: str = EMAIL_CACHE) -> str:
    """Return storage with a fresh Monthly Statistics section before the first day."""
    storage = strip_stats(storage)
    section = render_stats(month, storage, cache_file)
    first_day = re.search(r"<h2[^>]*>\s*\d{4}-\d{2}-\d{2}\s*</h2>", storage)
    at = first_day.start() if first_day else 0
    return storage[:at] + section + storage[at:]


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the Monthly Statistics section for a page")
    parser.add_argument("--month", required=True, help="Month in YYYY-MM")
    parser.add_argument("--storage", required=True, help="File holding the page's storage markup")
    args = parser.parse_args()
    with open(args.storage) as handle:
        print(render_stats(args.month, handle.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
