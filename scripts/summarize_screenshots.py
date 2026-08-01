#!/usr/bin/env python3

"""Optionally summarize screenshots using local Ollama vision models.

Purpose:
- Generate screenshot summary cache entries for timeline enrichment.
- Keep this step optional for privacy- and latency-friendly local runs.

How to run:
- ./venv/bin/python scripts/summarize_screenshots.py --days 31
- ./venv/bin/python scripts/summarize_screenshots.py --days 31 --force
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import re
from datetime import datetime, timedelta

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
CACHE_FILE = os.path.join(CACHE_DIR, "screenshot_summaries_cache.json")
DOWNLOADS_DIR = os.path.expanduser("~/Downloads")
BBEDIT_DIR = os.path.expanduser("~/Documents/Personal/notes")

OLLAMA_URL = os.getenv("WORKJOURNAL_OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("WORKJOURNAL_OLLAMA_VISION_MODEL", "llava:7b")


def parse_notes_by_day():
    notes = {}
    if not os.path.exists(BBEDIT_DIR):
        return notes

    files = glob.glob(os.path.join(BBEDIT_DIR, "*.txt")) + glob.glob(os.path.join(BBEDIT_DIR, "*.markdown"))
    for fp in files:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                chunks = re.split(r"===\s*(\d{4}-\d{2}-\d{2})\s*===", f.read())
                if len(chunks) > 1:
                    for i in range(1, len(chunks), 2):
                        day = chunks[i].strip()
                        body = chunks[i + 1].strip()
                        if body:
                            notes[day] = body
        except Exception:
            pass
    return notes


def encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def summarize_image(path: str, day_notes: str) -> str:
    prompt = (
        "Write exactly one short sentence summarizing this work screenshot for an IT work journal. "
        "Keep it under 20 words if possible, mention only the main observable activity or outcome, and do not use bullet points.\n\n"
        f"Day notes context:\n{day_notes[:1500]}"
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "images": [encode_image(path)],
        "stream": False,
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return str(data.get("response", "")).strip()
    except Exception as exc:
        return f"AI summary unavailable: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=31, help="Lookback window in days (default: 31)")
    parser.add_argument("--downloads", default=DOWNLOADS_DIR)
    parser.add_argument("--output", default=CACHE_FILE)
    parser.add_argument("--force", action="store_true", help="Recompute summaries even if cache has matching key")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    existing = []
    if os.path.exists(args.output):
        try:
            with open(args.output, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    existing_map = {f"{x.get('path','')}|{x.get('mtime',0)}": x for x in existing}

    cutoff = datetime.now().timestamp() - (args.days * 86400)
    day_notes = parse_notes_by_day()

    records = []
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        for path in glob.glob(os.path.join(os.path.expanduser(args.downloads), ext)):
            mtime = os.path.getmtime(path)
            if mtime < cutoff:
                continue

            day = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            key = f"{path}|{int(mtime)}"

            if not args.force and key in existing_map:
                records.append(existing_map[key])
                continue

            summary = summarize_image(path, day_notes.get(day, ""))
            records.append(
                {
                    "path": path,
                    "mtime": int(mtime),
                    "date": day,
                    "summary": summary,
                    "model": OLLAMA_MODEL,
                }
            )
            print(f"Summarized {os.path.basename(path)}")

    records.sort(key=lambda x: (x.get("date", ""), x.get("path", "")))
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2)

    print(f"Wrote {args.output} ({len(records)} records)")


if __name__ == "__main__":
    main()
