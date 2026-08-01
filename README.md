# workjournal

A local, multi-input work-journal compiler for combining:

- BBEdit day notes
- screenshot evidence from local downloads
- ticket snapshots (ADO + ServiceNow)
- Outlook mailbox metadata cache
- meeting transcript summaries
- daily report summaries imported from sibling `email-analytics`

Outputs are generated in `compilation/` for Confluence-ready use.

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

Run this sequence after generating daily outputs in the sibling `email-analytics` repo.

```bash
./venv/bin/python scripts/import_email_analytics_reports.py
./venv/bin/python scripts/fetch_tickets.py
./venv/bin/python scripts/fetch_emails.py
./venv/bin/python scripts/summarize_transcripts.py

# Optional: AI summary for screenshots (local Ollama vision)
./venv/bin/python scripts/summarize_screenshots.py --days 30

./venv/bin/python scripts/compile_dashboard.py
./venv/bin/python scripts/generate_journal.py
```

## Primary Outputs

- `compilation/work_journal_dashboard.html` (interactive dashboard)
- `compilation/confluence_markup.txt` (table markup helper)
- `cache/email_analytics_daily_cache.json`
- `cache/meeting_summaries_cache.json`
- `cache/screenshot_summaries_cache.json` (optional)

## Input Expectations

- BBEdit notes: `~/Documents/Personal/notes`
- screenshots: `~/Downloads`
- transcript files: `transcripts/*.txt`
- incident exports: `incidents/*.json`
- email-analytics daily files: `../email-analytics/output/daily_YYYY-MM-DD.md`

## Dashboard Behavior

- Top of each day: ticket summary.
- Main day body: chronological interspersed note and screenshot events.
- Bottom of day: meeting minutes and email-analytics daily summary blocks.
- `Generate Confluence Output` builds copy-ready monthly markup in-page.

## Local AI (Optional)

Screenshot summarization uses local Ollama when available.

Environment options:

- `WORKJOURNAL_OLLAMA_URL` (default `http://localhost:11434/api/generate`)
- `WORKJOURNAL_OLLAMA_VISION_MODEL` (default `llava:7b`)

## Troubleshooting

- If imported daily summaries are empty, re-run `import_email_analytics_reports.py` and verify `../email-analytics/output/daily_*.md` exists.
- If screenshot AI summaries are empty, verify local Ollama is running and model is pulled.
- If Outlook scan returns no tables, close Outlook and rerun `fetch_emails.py`.
- If transcript dates are wrong, ensure filenames include one of: `YYYY-MM-DD`, `YYYYMMDD`, `DD-MM-YYYY`.
