"""Pipeline, batch actions, command queue, and WebSocket routes."""

import json
import logging
import subprocess
import asyncio
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from pathlib import Path

from .shared import (
    get_db_conn, log, COMMAND_QUEUE, ROOT,
    connected_websockets, connected_websockets_lock,
    broadcast_pipeline_event,
)

router = APIRouter()


# ──────────────────────────────────────────────
# GET /api/pipeline
# ──────────────────────────────────────────────

@router.get("/api/pipeline")
async def get_pipeline():
    """Pipeline health status — imports, enrichment, errors."""
    conn = get_db_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

        x_count = conn.execute("""
            SELECT COUNT(*) FROM entries
            WHERE (source_url LIKE '%x.com%' OR source_url LIKE '%twitter.com%')
        """).fetchone()[0]

        enriched_x = conn.execute("""
            SELECT COUNT(*) FROM entries
            WHERE (source_url LIKE '%x.com%' OR source_url LIKE '%twitter.com%')
              AND LENGTH(content) > 10000
        """).fetchone()[0]

        pending_x = conn.execute("""
            SELECT COUNT(*) FROM entries
            WHERE (source_url LIKE '%x.com%' OR source_url LIKE '%twitter.com%')
              AND LENGTH(content) < 200
        """).fetchone()[0]

        dead = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE LENGTH(content) < 50 AND LENGTH(title) < 20"
        ).fetchone()[0]

        last_import = conn.execute(
            "SELECT created_at FROM entries ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        last_import_time = last_import["created_at"] if last_import else None

        thirty_day = conn.execute("""
            SELECT COUNT(*) as cnt FROM entries
            WHERE created_at >= DATE('now', '-30 days')
        """).fetchone()[0]
        daily_avg = round(thirty_day / 30, 1) if thirty_day else 0

        return {
            "total_entries": total,
            "x_entries_total": x_count,
            "x_enriched": enriched_x,
            "x_pending": pending_x,
            "dead_entries": dead,
            "last_import_time": last_import_time,
            "daily_avg_30d": daily_avg,
            "entries_last_30d": thirty_day,
            "enrichment_cron": "daily at 09:00 UTC",
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Pipeline action endpoints
# ──────────────────────────────────────────────

@router.post("/api/pipeline/run-enrich")
async def pipeline_run_enrich():
    """Run the enrichment pipeline as a subprocess."""
    await broadcast_pipeline_event("pipeline_start", {"action": "enrich"})
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                ["python3", "src/ingest/batch_enrich_v2.py"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=600,
            )
        )
        await broadcast_pipeline_event("pipeline_complete", {"action": "enrich", "output": result.stdout[:500]})
        return {"status": "started", "output": result.stdout + result.stderr}
    except Exception as e:
        await broadcast_pipeline_event("pipeline_error", {"action": "enrich", "error": str(e)})
        raise


@router.post("/api/pipeline/re-embed")
async def pipeline_re_embed():
    """Run the re-embedding script."""
    await broadcast_pipeline_event("pipeline_start", {"action": "re-embed"})
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                ["python3", "src/cli/reembed.py"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=600,
            )
        )
        await broadcast_pipeline_event("pipeline_complete", {"action": "re-embed", "output": result.stdout[:500]})
        return {"status": "started", "output": result.stdout + result.stderr}
    except Exception as e:
        await broadcast_pipeline_event("pipeline_error", {"action": "re-embed", "error": str(e)})
        raise


@router.post("/api/pipeline/retag")
async def pipeline_retag():
    """Run the auto-tagging script."""
    await broadcast_pipeline_event("pipeline_start", {"action": "retag"})
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                ["python3", "src/cli/auto_tag.py"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=600,
            )
        )
        await broadcast_pipeline_event("pipeline_complete", {"action": "retag", "output": result.stdout[:500]})
        return {"status": "started", "output": result.stdout + result.stderr}
    except Exception as e:
        await broadcast_pipeline_event("pipeline_error", {"action": "retag", "error": str(e)})
        raise


@router.post("/api/pipeline/cleanup-dead")
async def pipeline_cleanup_dead():
    """Find and delete dead entries (NULL/empty content, short source_url)."""
    await broadcast_pipeline_event("pipeline_start", {"action": "cleanup-dead"})
    conn = get_db_conn()
    try:
        rows = conn.execute("""
            SELECT id, title, source_url FROM entries
            WHERE (content IS NULL OR content = '')
              AND length(source_url) < 10
            LIMIT 100
        """).fetchall()
        entries = [{"id": r["id"], "title": r["title"], "source_url": r["source_url"]} for r in rows]
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM entries WHERE id IN ({placeholders})", ids)
            conn.commit()
        await broadcast_pipeline_event("pipeline_complete", {"action": "cleanup-dead", "deleted": len(ids), "entries": entries})
        return {"deleted": len(ids), "entries": entries}
    except Exception as e:
        await broadcast_pipeline_event("pipeline_error", {"action": "cleanup-dead", "error": str(e)})
        raise
    finally:
        conn.close()


@router.post("/api/pipeline/re-extract-thin")
async def pipeline_re_extract_thin():
    """Queue thin entries for re-extraction by clearing their content."""
    await broadcast_pipeline_event("pipeline_start", {"action": "re-extract-thin"})
    conn = get_db_conn()
    try:
        rows = conn.execute("""
            SELECT id FROM entries
            WHERE (content IS NULL OR content = '')
              AND length(source_url) > 10
            LIMIT 50
        """).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE entries SET content = '' WHERE id IN ({placeholders})",
                ids,
            )
            conn.commit()
        await broadcast_pipeline_event("pipeline_complete", {"action": "re-extract-thin", "queued": len(ids)})
        return {"queued": len(ids)}
    except Exception as e:
        await broadcast_pipeline_event("pipeline_error", {"action": "re-extract-thin", "error": str(e)})
        raise
    finally:
        conn.close()


@router.post("/api/pipeline/synthesize")
async def pipeline_synthesize():
    """Run the cross-pollination synthesis agent as a subprocess."""
    await broadcast_pipeline_event("pipeline_start", {"action": "synthesize"})
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                ["python3", "src/cron/synthesize.py", "--days", "7"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=600,
            )
        )
        output = result.stdout + result.stderr
        out_lines = [l for l in output.split("\n") if l.strip()][-20:]
        summary = "\n".join(out_lines)
        await broadcast_pipeline_event("pipeline_complete", {"action": "synthesize", "output": summary[:500]})
        return {"status": "completed", "output": summary}
    except Exception as e:
        await broadcast_pipeline_event("pipeline_error", {"action": "synthesize", "error": str(e)})
        return {"status": "error", "error": str(e)}


# ──────────────────────────────────────────────
# Command queue endpoints
# ──────────────────────────────────────────────

@router.post("/api/command")
async def receive_command(request: Request):
    """Accept a command from the UI command bar and queue it for Pliny to process."""
    try:
        body = await request.json()
        command = body.get("command", "").strip()
        context = body.get("context", {})
        timestamp = body.get("timestamp", datetime.now(timezone.utc).isoformat())

        if not command:
            return JSONResponse({"error": "empty command"}, status_code=400)

        queue = []
        if COMMAND_QUEUE.exists():
            try:
                queue = json.loads(COMMAND_QUEUE.read_text())
            except (json.JSONDecodeError, IOError):
                queue = []

        queue.append({
            "command": command,
            "context": context,
            "timestamp": timestamp,
            "received_at": datetime.now(timezone.utc).isoformat(),
        })

        queue = queue[-50:]

        COMMAND_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        COMMAND_QUEUE.write_text(json.dumps(queue, indent=2))

        return {"status": "queued", "position": len(queue)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/command/queue")
async def read_command_queue():
    """Read queued commands (for Pliny to consume)."""
    if not COMMAND_QUEUE.exists():
        return {"commands": [], "count": 0}
    try:
        queue = json.loads(COMMAND_QUEUE.read_text())
        return {"commands": queue, "count": len(queue)}
    except (json.JSONDecodeError, IOError):
        return {"commands": [], "count": 0}


@router.post("/api/command/clear")
async def clear_command_queue():
    """Clear the command queue after Pliny has processed it."""
    COMMAND_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    COMMAND_QUEUE.write_text("[]")
    return {"status": "cleared"}


# ──────────────────────────────────────────────
# Batch action endpoints
# ──────────────────────────────────────────────

@router.post("/api/batch/summarize")
async def batch_summarize(request: Request):
    """Generate or return summaries for a batch of entries."""
    body = await request.json()
    ids = body.get("ids", [])
    if not ids:
        return JSONResponse({"error": "no ids"}, status_code=400)

    conn = get_db_conn()
    try:
        summaries = []
        for eid in ids[:50]:
            row = conn.execute(
                "SELECT id, title, content FROM entries WHERE id = ?",
                (eid,)
            ).fetchone()
            if row:
                summary = (row["content"] or "")[:200]
                summaries.append({
                    "id": row["id"],
                    "title": row["title"],
                    "summary": summary,
                })
        return {"summaries": summaries, "count": len(summaries)}
    finally:
        conn.close()


@router.post("/api/batch/queue-re-extraction")
async def queue_re_extraction(request: Request):
    """Queue entries for re-extraction (clears content, cron picks it up)."""
    body = await request.json()
    ids = body.get("ids", [])
    if not ids:
        return JSONResponse({"error": "no ids"}, status_code=400)

    conn = get_db_conn()
    try:
        processed = 0
        errors = 0
        for eid in ids[:30]:
            row = conn.execute(
                "SELECT id FROM entries WHERE id = ?",
                (eid,)
            ).fetchone()
            if row:
                try:
                    conn.execute(
                        "UPDATE entries SET content = '' WHERE id = ?",
                        (eid,)
                    )
                    processed += 1
                except Exception as e:
                    errors += 1
                    print(f"Re-extract error {eid}: {e}")
        conn.commit()
        return {"processed": processed, "errors": errors, "total": len(ids), "status": "queued for re-extraction"}
    finally:
        conn.close()


@router.post("/api/batch/tag")
async def batch_tag(request: Request):
    """Add a tag to a batch of entries."""
    body = await request.json()
    ids = body.get("ids", [])
    tag = body.get("tag", "").strip().lower()
    if not ids or not tag:
        return JSONResponse({"error": "ids and tag required"}, status_code=400)

    conn = get_db_conn()
    try:
        tagged = 0
        for eid in ids[:100]:
            row = conn.execute(
                "SELECT auto_tags FROM entries WHERE id = ?", (eid,)
            ).fetchone()
            if row:
                try:
                    tags = json.loads(row["auto_tags"]) if row["auto_tags"] else []
                except (json.JSONDecodeError, TypeError):
                    tags = []
                if tag not in tags:
                    tags.append(tag)
                    conn.execute(
                        "UPDATE entries SET auto_tags = ? WHERE id = ?",
                        (json.dumps(tags), eid),
                    )
                    tagged += 1
        conn.commit()
        return {"tagged": tagged, "tag": tag, "total": len(ids)}
    finally:
        conn.close()


# ──────────────────────────────────────────────
# WebSocket endpoint
# ──────────────────────────────────────────────

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time pipeline event broadcasting."""
    await websocket.accept()
    async with connected_websockets_lock:
        connected_websockets.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except (json.JSONDecodeError, Exception):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        async with connected_websockets_lock:
            connected_websockets.discard(websocket)
