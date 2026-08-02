"""Stats and activity routes — aggregate statistics and recent activity."""

import json
import logging
import sqlite3

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .shared import get_db_conn, log

router = APIRouter()


# ──────────────────────────────────────────────
# GET /api/stats
# ──────────────────────────────────────────────

@router.get("/api/stats")
async def get_stats():
    """Overall system statistics for the pipeline dashboard."""
    conn = get_db_conn()
    try:
        # Core counts
        total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

        # Content stats
        content_stats = conn.execute("""
            SELECT
                MIN(LENGTH(content)) as min_c,
                MAX(LENGTH(content)) as max_c,
                AVG(LENGTH(content)) as avg_c,
                SUM(LENGTH(content)) as total_c
            FROM entries
        """).fetchone()

        # Entries with enriched content (10K+ chars)
        enriched = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE LENGTH(content) > 10000"
        ).fetchone()[0]

        # Entries with thin content (< 200 chars)
        thin = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE LENGTH(content) < 200"
        ).fetchone()[0]

        # Source domain distribution (from source_url)
        domains_raw = conn.execute("""
            SELECT LOWER(
                CASE
                    WHEN source_url LIKE '%x.com%' OR source_url LIKE '%twitter.com%' THEN 'x/twitter'
                    WHEN source_url LIKE '%github.com%' THEN 'github'
                    WHEN source_url LIKE '%reddit.com%' THEN 'reddit'
                    WHEN source_url LIKE '%youtube.com%' OR source_url LIKE '%youtu.be%' THEN 'youtube'
                    WHEN source_url LIKE '%news.ycombinator.com%' OR source_url LIKE '%hn%' THEN 'hacker news'
                    WHEN source_url LIKE '%arxiv.org%' THEN 'arxiv'
                    WHEN source_url LIKE '%medium.com%' THEN 'medium'
                    WHEN source_url LIKE '%substack.com%' THEN 'substack'
                    ELSE 'other'
                END
            ) as domain,
            COUNT(*) as cnt
            FROM entries
            GROUP BY domain
            ORDER BY cnt DESC
        """).fetchall()

        # Tag stats
        tag_count = conn.execute(
            "SELECT COUNT(DISTINCT value) FROM entries, json_each(auto_tags) WHERE auto_tags IS NOT NULL AND auto_tags != '[]'"
        ).fetchone()[0]

        # Top tags
        top_tags_raw = conn.execute("""
            SELECT value AS tag, COUNT(*) AS cnt
            FROM entries, json_each(auto_tags)
            WHERE auto_tags IS NOT NULL AND auto_tags != '[]'
            GROUP BY value
            ORDER BY cnt DESC
            LIMIT 10
        """).fetchall()

        # Daily activity (last 14 days)
        last_14 = conn.execute("""
            SELECT DATE(created_at) as day, COUNT(*) as cnt
            FROM entries
            WHERE created_at >= DATE('now', '-14 days')
            GROUP BY day
            ORDER BY day
        """).fetchall()

        return {
            "total_entries": total,
            "total_tags": tag_count,
            "content_min": content_stats["min_c"],
            "content_max": content_stats["max_c"],
            "content_avg": round(content_stats["avg_c"]),
            "content_total": content_stats["total_c"],
            "enriched_entries": enriched,
            "thin_entries": thin,
            "domains": {r["domain"]: r["cnt"] for r in domains_raw},
            "top_tags": [{"tag": r["tag"], "count": r["cnt"]} for r in top_tags_raw],
            "daily_activity": [{"day": r["day"], "count": r["cnt"]} for r in last_14],
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────
# GET /api/activity
# ──────────────────────────────────────────────

@router.get("/api/activity")
async def get_activity(limit: int = Query(default=20, ge=1, le=50)):
    """Recent activity — latest entries with enrichment status."""
    conn = get_db_conn()
    try:
        rows = conn.execute("""
            SELECT id, title, source_url, auto_tags, content,
                   LENGTH(content) as content_len, created_at
            FROM entries
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

        entries = []
        for r in rows:
            try:
                tags = json.loads(r["auto_tags"]) if r["auto_tags"] else []
            except (json.JSONDecodeError, TypeError):
                tags = []

            status = "enriched" if r["content_len"] > 10000 else \
                     "thin" if r["content_len"] < 200 else \
                     "normal"

            entries.append({
                "id": r["id"],
                "title": r["title"],
                "source_url": r["source_url"],
                "tags": tags,
                "summary": (r["content"] or "")[:200],
                "content_len": r["content_len"],
                "status": status,
                "created_at": r["created_at"],
            })

        return {"entries": entries, "total": len(entries)}
    finally:
        conn.close()
