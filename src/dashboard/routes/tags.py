"""Tag routes — listing tags, tag entries, tag graph, related tags."""

import json
import logging
import sqlite3

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from .shared import get_db_conn, log

router = APIRouter()


# ──────────────────────────────────────────────
# GET /api/tags
# ──────────────────────────────────────────────

@router.get("/api/tags")
async def get_tags(query: str = Query(default="", max_length=200)):
    """Return all unique tags with their frequency counts."""
    conn = get_db_conn()
    try:
        if query:
            rows = conn.execute(
                """
                SELECT value AS tag, COUNT(*) AS count
                FROM entries, json_each(auto_tags)
                WHERE auto_tags IS NOT NULL AND auto_tags != '[]' AND auto_tags != ''
                  AND value LIKE ?
                GROUP BY value
                ORDER BY count DESC
                """,
                (f"%{query}%",),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT value AS tag, COUNT(*) AS count
                FROM entries, json_each(auto_tags)
                WHERE auto_tags IS NOT NULL AND auto_tags != '[]' AND auto_tags != ''
                GROUP BY value
                ORDER BY count DESC
                """
            ).fetchall()

        sorted_tags = [(r["tag"], r["count"]) for r in rows]
        return {
            "tags": [{"tag": t, "count": c} for t, c in sorted_tags],
            "total": len(sorted_tags),
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────
# GET /api/tags/related/{tag}
# ──────────────────────────────────────────────

@router.get("/api/tags/related/{tag}")
async def get_related_tags(tag: str, limit: int = Query(default=40, ge=1, le=100)):
    """Return tags that co-occur with the given tag, weighted by frequency."""
    conn = get_db_conn()
    try:
        rows = conn.execute("""
            SELECT t2.value AS tag, COUNT(*) AS weight
            FROM entries e
            CROSS JOIN json_each(e.auto_tags) AS t1
            CROSS JOIN json_each(e.auto_tags) AS t2
            WHERE t1.value = ?
              AND t2.value != ?
              AND e.auto_tags IS NOT NULL AND e.auto_tags != '[]'
            GROUP BY t2.value
            ORDER BY weight DESC
            LIMIT ?
        """, (tag, tag, limit)).fetchall()

        related = [{"tag": r["tag"], "weight": r["weight"]} for r in rows]
        tag_count = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE auto_tags LIKE ?",
            (f'%"{tag}"%',)
        ).fetchone()[0]

        return {"tag": tag, "count": tag_count, "related": related}
    finally:
        conn.close()


# ──────────────────────────────────────────────
# GET /api/tags/graph
# ──────────────────────────────────────────────

@router.get("/api/tags/graph")
async def get_tag_graph(
    min_count: int = Query(default=2, ge=1, le=100),
    max_edges: int = Query(default=500, ge=10, le=2000),
):
    """Return nodes and edges for the tag co-occurrence graph.

    Nodes are tags with frequency >= min_count.
    Edges are co-occurrence pairs (top max_edges by weight).
    """
    conn = get_db_conn()
    try:
        nodes_raw = conn.execute("""
            SELECT value AS tag, COUNT(*) AS count
            FROM entries, json_each(auto_tags)
            WHERE auto_tags IS NOT NULL AND auto_tags != '[]'
            GROUP BY value
            HAVING count >= ?
            ORDER BY count DESC
        """, (min_count,)).fetchall()

        nodes = [{"id": r["tag"], "count": r["count"]} for r in nodes_raw]

        edges_raw = conn.execute("""
            SELECT t1.value AS source, t2.value AS target, COUNT(*) AS weight
            FROM entries e
            CROSS JOIN json_each(e.auto_tags) AS t1
            CROSS JOIN json_each(e.auto_tags) AS t2
            WHERE t1.value < t2.value
              AND t1.value IN (SELECT value FROM (SELECT value, COUNT(*) AS c FROM entries, json_each(auto_tags) GROUP BY value) WHERE c >= ?)
              AND t2.value IN (SELECT value FROM (SELECT value, COUNT(*) AS c FROM entries, json_each(auto_tags) GROUP BY value) WHERE c >= ?)
            GROUP BY t1.value, t2.value
            ORDER BY weight DESC
            LIMIT ?
        """, (min_count, min_count, max_edges)).fetchall()

        edges = [
            {"source": r["source"], "target": r["target"], "weight": r["weight"]}
            for r in edges_raw
        ]

        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
    finally:
        conn.close()
