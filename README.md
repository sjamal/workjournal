# workjournal

A local, multi-input work-journal compiler for combining:

- BBEdit day notes
- screenshot evidence from local downloads
- ticket snapshots (ADO + ServiceNow)
- Outlook mailbox metadata cache
- meeting transcript summaries
- daily report summaries imported from sibling `email-analytics`

Outputs are generated in `compilation/` for Confluence-ready use.

## Source Priority

For monthly journal assembly, use these priorities:

1. `import_email_analytics_reports.py` for email narrative context.
2. `fetch_tickets.py` for ADO and ServiceNow ticket context.
3. `summarize_transcripts.py` for meeting summaries.
4. `summarize_screenshots.py` for optional screenshot AI enrichment.
5. `fetch_emails.py` only when you explicitly want direct Outlook inbox scraping.

Important:
- `fetch_emails.py` is optional and independent from email-analytics import.
- If you are not directly scraping Outlook, Outlook does not need to be running.
- `fetch_tickets.py` reads `incidents/caller_history.json` when available.

## Privacy Model

- Keep all secrets in local `.env` only.
- Keep generated artifacts and caches local (`cache/`, `compilation/`).
- Do not commit raw incident exports, transcript text, or screenshots.

Use `.env.example` as the public-safe configuration template.

## Quick Setup

```bash
cd /Users/jamals/Documents/ITS/EASI/repos/github/workjournal

# If venv exists
./venv/bin/python -m pip install -U pip requests python-dotenv

# If venv is missing
python3 -m venv venv
source venv/bin/activate
pip install -U pip requests python-dotenv

cp .env.example .env
```

## Core Workflow

Run this sequence after generating daily outputs in sibling `email-analytics`.
Use `31` for monthly runs to avoid missing a long month.
For exact monthly boundaries, prefer `--month YYYY-MM`.

```bash
./venv/bin/python scripts/import_email_analytics_reports.py
./venv/bin/python scripts/fetch_tickets.py --days 31
./venv/bin/python scripts/summarize_transcripts.py

# Optional: AI summary for screenshots (local Ollama vision)
./venv/bin/python scripts/summarize_screenshots.py --days 31

# Optional: direct Outlook scrape (only if explicitly needed)
./venv/bin/python scripts/fetch_emails.py --days 31

./venv/bin/python scripts/compile_dashboard.py --month 2026-07
./venv/bin/python scripts/generate_journal.py --month 2026-07

# One-command orchestration (recommended)
./venv/bin/python scripts/run_monthly_workjournal.py --month 2026-07 --summarize-screenshots
```

## Primary Outputs

- `compilation/work_journal_dashboard.html` (interactive dashboard)
- `compilation/confluence_markup.md` (primary README-style Markdown handoff)
- `compilation/confluence_markup.txt` (legacy mirror of the same Markdown)
- `cache/email_analytics_daily_cache.json`
- `cache/meeting_summaries_cache.json`
- `cache/screenshot_summaries_cache.json` (optional)
- `cache/work_items_cache.json`

## Input Expectations

- BBEdit notes: `~/Documents/Personal/notes`
- screenshots: `~/Downloads`
- transcript files: `transcripts/*.txt`
- incident exports: `incidents/*.json`
- email-analytics daily files: `../email-analytics/output/daily_YYYY-MM-DD.md`

## Dashboard Behavior

- Top of each day: ticket summary.
- Main day body: chronological note and screenshot lines (timestamp-first format).
- Bottom of day: meeting minutes and email-analytics daily summary blocks.
- `Generate Confluence Markup File` downloads a markup `.txt` file from the browser.
- `Generate Confluence Markup File` downloads a Markdown `.md` file from the browser.

### About The Generate Button

When you click `Generate Confluence Markup File`:

1. The script collects all visible rows represented in the page.
2. It builds README-style Markdown with `#`, `##`, and `###` headings plus sequential bullet lists.
3. It downloads a `confluence_markup_YYYY-MM-DD.md` file from your browser.

Screenshot rows include Confluence attachment tokens (`!filename.png!`) in the summary cell.

Important:
- Confluence will only render those image tokens when the files are attached to the page.
- Use files in `compilation/assets/` as the upload source.

If nothing appears, rebuild the dashboard first with:

```bash
./venv/bin/python scripts/compile_dashboard.py --month 2026-07
```

Then reopen `compilation/work_journal_dashboard.html`.

### Confluence Import Guidance

If you are not using the direct API publisher script:

1. Create or open your target Confluence page.
2. Upload screenshots from `compilation/assets/` as page attachments.
3. Open `compilation/confluence_markup.md` (or the downloaded Markdown file).
4. Copy table text and paste into the page editor.
5. Save the page; attachment tokens should render as inline images.

Ticket references are clickable in the Markdown export and point to the real ticket URLs.

Note:
- Confluence Cloud does not reliably import pasted Markdown as a structured page.
- The Markdown file is a handoff artifact for review or conversion, not a guaranteed direct import format.
- For a reliable page creation flow, use the REST API publisher below.

### Why `compile_dashboard.py` and `generate_journal.py` both exist

- `compile_dashboard.py`: interactive review/edit surface, image preview, and in-page export generation.
- `generate_journal.py`: non-interactive batch export to `compilation/confluence_markup.md` using the same consolidated timeline sources.

## Orchestrator Script

Use the orchestrator for repeatable monthly runs:

```bash
./venv/bin/python scripts/run_monthly_workjournal.py --month 2026-07 --summarize-screenshots
```

Options:

- `--include-outlook` to run direct Outlook scraping.
- `--summarize-screenshots` to run Ollama screenshot summaries.
- `--force-screenshot-summaries` to recompute screenshot cache entries.

## REST API Publisher

If you want Confluence page creation automated, use:

```bash
./venv/bin/python scripts/publish_to_confluence.py --month 2026-07 --upload-assets
```

Required environment variables:

- `CONFLUENCE_URL`
- `CONFLUENCE_EMAIL`
- `CONFLUENCE_API_TOKEN` or `CONFLUENCE_TOKEN`
- `CONFLUENCE_SPACE`
- Optional: `CONFLUENCE_PARENT_PAGE_ID`

This path creates the page via REST API and uploads `compilation/assets/` as attachments.
If `CONFLUENCE_PARENT_PAGE_ID` is set, the new page is created as a child of that page.

If you want the July journal to live under your existing page at `~jamalsar`, pass the parent page id for `Notes from July 2026` and the script will create the new page beneath it.

Recommended reference model:

1. Use the page id as the stable reference for the parent page.
2. Use the page title for human navigation only.
3. Use the REST API page id returned by the create call when uploading attachments.

## Local AI (Optional)

Screenshot summarization uses local Ollama when available.

Environment options:

- `WORKJOURNAL_OLLAMA_URL` (default `http://localhost:11434/api/generate`)
- `WORKJOURNAL_OLLAMA_VISION_MODEL` (default `llava:7b`)

## Troubleshooting

- If imported daily summaries are empty, re-run `import_email_analytics_reports.py` and verify `../email-analytics/output/daily_*.md` exists.
- If imported daily summaries look too short, rerun import after updating daily files; importer now includes complete key bullet sections.
- If screenshot AI summaries are empty, verify local Ollama is running and model is pulled.
- If Outlook scan returns no tables, close Outlook and rerun `fetch_emails.py`.
- If transcript dates are wrong, ensure filenames include one of: `YYYY-MM-DD`, `YYYYMMDD`, `DD-MM-YYYY`.
