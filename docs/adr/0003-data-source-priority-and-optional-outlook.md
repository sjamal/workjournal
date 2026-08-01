# ADR 0003: Data Source Priority And Optional Outlook

- Status: Accepted
- Date: 2026-07-31

## Context

The workflow combines multiple local and remote-ish sources (ticket APIs, local exports, notes, screenshots, transcript summaries, and email analytics artifacts). There was confusion about whether direct Outlook scraping is required when daily summaries are already imported from `email-analytics`.

## Decision

Adopt explicit source priority:

1. `import_email_analytics_reports.py` is the default source for email narrative.
2. `fetch_tickets.py` provides ADO and ServiceNow ticket context.
3. `summarize_transcripts.py` and optional `summarize_screenshots.py` enrich context.
4. `fetch_emails.py` remains optional for direct Outlook scraping only.

## Consequences

- Outlook does not need to be running unless direct Outlook scraping is intentionally used.
- Users can run a stable monthly path even without M365 API/OAuth state.
- Documentation clearly separates optional and required data paths.