#!/usr/bin/env python3
"""ingest_cli.py — Ingest raw content into Pliny's index via url_ingest.

Usage:
    python3 src/cli/ingest_cli.py --url "https://..." --title "Entry" --content "Full text"
"""

from __future__ import annotations

import hashlib
import re
import time

from lib.schema import get_db
from lib.embed import embed_json
from lib.paths import DB_PATH
from ingest.url_ingest import ingest_url


def slugify(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def ingest(source_url: str, title: str, content: str, entry_id: str | None = None) -> str:
    """Ingest a URL via the full url_ingest pipeline."""
    result = ingest_url(source_url, entry_id)
    return result or ""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ingest a new entry into Pliny")
    parser.add_argument("--url", required=True, help="Source URL")
    parser.add_argument("--title", required=True, help="Entry title")
    parser.add_argument("--content", required=True, help="Entry content body")
    parser.add_argument("--id", help="Optional entry slug (auto-generated if omitted)")
    args = parser.parse_args()

    eid = ingest(args.url, args.title, args.content, args.id)
    print(f"V Ingested: {eid}")
