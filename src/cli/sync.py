"""sync.py — Bidirectional sync between Pliny and Karakeep.

Handles:
1. Karakeep → Pliny: Webhook endpoint receives new bookmark events,
   extracts URLs, and ingests them into Pliny via url_ingest.ingest_url()
2. Pliny → Karakeep: After ingesting a URL into Pliny, pushes the
   bookmark to Karakeep's API
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.paths import DB_PATH

# ── Config ──

KARAKEEP_BASE_URL = os.getenv("KARAKEEP_BASE_URL", "http://127.0.0.1:3000")
PLINY_BASE_URL = os.getenv("PLINY_BASE_URL", "http://172.17.0.1:3131")

# Try to load Karakeep API token
KARAKEEP_TOKEN: str | None = None


def _load_karakeep_token() -> str | None:
    """Load Karakeep API token from env or .env file."""
    token = os.environ.get("KARAKEEP_API_TOKEN")
    if token:
        return token

    # Try pliny/.env
    dotenv = Path(__file__).resolve().parent.parent.parent / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            line = line.strip()
            if line.startswith("KARAKEEP_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


def get_token() -> str:
    global KARAKEEP_TOKEN
    if KARAKEEP_TOKEN is None:
        KARAKEEP_TOKEN = _load_karakeep_token()
    if not KARAKEEP_TOKEN:
        raise ValueError("KARAKEEP_API_TOKEN not configured")
    return KARAKEEP_TOKEN


# ── Pliny → Karakeep ──


def push_to_karakeep(url: str, title: str = "", tags: list[str] | None = None) -> dict | None:
    """Push a URL bookmark into Karakeep.

    Called after ingest_url() completes successfully.

    Returns the Karakeep bookmark response dict, or None on failure.
    """
    if not url or url.startswith("agent:"):
        return None  # Don't push agent memories to Karakeep

    try:
        token = get_token()
    except ValueError:
        return None  # Token not configured — skip

    body: dict[str, Any] = {
        "type": "link",
        "url": url,
    }
    if title:
        body["title"] = title
    if tags:
        body["tags"] = [{"tagName": t} for t in tags]

    req = urllib.request.Request(
        f"{KARAKEEP_BASE_URL}/api/v1/bookmarks",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "PlinySync/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"! Karakeep push failed ({e.code}): {error_body[:200]}")
        return None
    except Exception as e:
        print(f"! Karakeep push error: {e}")
        return None


# ── Karakeep → Pliny ──


def handle_karakeep_event(event: str, data: dict) -> dict:
    """Handle a Karakeep webhook event.

    Expected payload from Karakeep webhook:
    {
        "event": "created",      # or "edited", "crawled", "ai tagged", "deleted"
        "bookmark": {
            "id": "...",
            "url": "https://...",
            "title": "...",
            "tags": ["..."],
            ...
        }
    }

    Returns a status dict with the result.
    """
    bookmark = data.get("bookmark", {})
    url = bookmark.get("url", "") or bookmark.get("content", {}).get("url", "")

    if not url:
        return {"status": "skipped", "reason": "no URL in payload"}

    # Only process 'created' events for new bookmarks
    if event not in ("created",):
        return {"status": "skipped", "event": event}

    # Check if already in Pliny
    from lib.schema import get_db
    db = get_db(DB_PATH)
    try:
        existing = db.execute(
            "SELECT id FROM entries WHERE source_url = ?",
            (url,),
        ).fetchone()
        if existing:
            return {"status": "skipped", "reason": "already in Pliny", "url": url}
    finally:
        db.close()

    # Import and ingest
    from ingest.url_ingest import ingest_url
    entry_id = ingest_url(url)
    if entry_id:
        return {"status": "ingested", "entry_id": entry_id, "url": url}
    return {"status": "failed", "url": url}
