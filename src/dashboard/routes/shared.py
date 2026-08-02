"""Shared utilities for route modules."""

import json
import logging
import asyncio
import urllib.parse
from pathlib import Path

import sqlite3
from lib.schema import get_db as _schema_get_db
from lib.paths import DB_PATH, PLINY_ROOT

log = logging.getLogger(__name__)

ROOT = PLINY_ROOT

# ── DB helper ──

def get_db_conn() -> sqlite3.Connection:
    """Return a raw (non-vector) SQLite connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ── Source domain helpers ──

SEARCH_SOURCES = {
    "x": ("source_url LIKE '%x.com%' OR source_url LIKE '%twitter.com%'", "X/Twitter"),
    "github": ("source_url LIKE '%github.com%'", "GitHub"),
    "reddit": ("source_url LIKE '%reddit.com%'", "Reddit"),
    "youtube": ("source_url LIKE '%youtube.com%' OR source_url LIKE '%youtu.be%'", "YouTube"),
    "hackernews": ("source_url LIKE '%news.ycombinator.com%' OR source_url LIKE '%hn%'", "Hacker News"),
    "arxiv": ("source_url LIKE '%arxiv.org%'", "arXiv"),
    "medium": ("source_url LIKE '%medium.com%'", "Medium"),
    "substack": ("source_url LIKE '%substack.com%'", "Substack"),
}


# ── File paths ──

COMMAND_QUEUE = ROOT / "data" / "queues" / "command_queue.json"
SAVED_QUERIES_PATH = ROOT / "data" / "user" / "saved_queries.json"
SAVED_QUERIES_CHECK_PATH = ROOT / "data" / "user" / "saved_query_last_check.json"


# ── WebSocket broadcast ──

connected_websockets = set()
connected_websockets_lock = asyncio.Lock()


async def broadcast_pipeline_event(event_type: str, data: dict):
    """Send a JSON event to all connected WebSocket clients."""
    message = json.dumps({"type": event_type, **data})
    dead = set()
    async with connected_websockets_lock:
        for ws in connected_websockets:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        connected_websockets.difference_update(dead)
