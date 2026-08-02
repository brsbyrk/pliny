"""Ingest routes — URL ingestion and webhook handlers."""

import json
import logging
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .shared import get_db_conn, log, broadcast_pipeline_event

router = APIRouter()


# ──────────────────────────────────────────────
# POST /api/ingest/add-url
# ──────────────────────────────────────────────

@router.post("/api/ingest/add-url")
async def ingest_add_url(request: Request):
    """Ingest a URL into Pliny immediately (no queue)."""
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        return JSONResponse({"error": "url required"}, status_code=400)

    try:
        from ingest.url_ingest import ingest_url
        entry_id = ingest_url(url)
        if entry_id:
            await broadcast_pipeline_event("url_added", {"url": url, "entry_id": entry_id})
            return {"status": "ingested", "entry_id": entry_id, "url": url}
        else:
            return JSONResponse({"error": "extraction failed", "url": url}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": str(e), "url": url}, status_code=500)


# ──────────────────────────────────────────────
# POST /api/webhooks/karakeep
# ──────────────────────────────────────────────

@router.post("/api/webhooks/karakeep")
async def karakeep_webhook(request: Request):
    """Receive webhook events from Karakeep.

    Karakeep sends POST when a bookmark is created/edited/crawled/deleted.
    Pliny extracts the URL and ingests it.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    event = body.get("event", "")
    from cli.sync import handle_karakeep_event
    result = handle_karakeep_event(event, body)
    return result
