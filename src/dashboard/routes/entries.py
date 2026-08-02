"""Entry CRUD routes — individual entry operations."""

import json
import logging
import sqlite3
import urllib.parse

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

import sqlite_vec
from lib.paths import DB_PATH

from .shared import get_db_conn, SEARCH_SOURCES, log

router = APIRouter()


# ──────────────────────────────────────────────
# GET /api/entry/{entry_id}
# ──────────────────────────────────────────────

@router.get("/api/entry/{entry_id}")
async def get_entry(entry_id: str):
    """Get full details of a single entry."""
    conn = get_db_conn()
    try:
        row = conn.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)

        try:
            tag_list = json.loads(row["auto_tags"]) if row["auto_tags"] else []
        except (json.JSONDecodeError, TypeError):
            tag_list = []

        try:
            refs = json.loads(row["source_refs"]) if row["source_refs"] else []
        except (json.JSONDecodeError, TypeError):
            refs = []

        return {
            "id": row["id"],
            "title": row["title"],
            "source_url": row["source_url"],
            "content": row["content"],
            "tags": tag_list,
            "entry_type": row["entry_type"],
            "source_refs": refs,
            "summary": (row["content"] or "")[:200],
            "created_at": row["created_at"],
            "starred": bool(row["starred"]),
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────
# POST /api/entry/{entry_id}/star
# ──────────────────────────────────────────────

@router.post("/api/entry/{entry_id}/star")
async def toggle_star(entry_id: str):
    conn = get_db_conn()
    try:
        row = conn.execute("SELECT starred FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        new_val = 0 if row["starred"] else 1
        conn.execute("UPDATE entries SET starred = ? WHERE id = ?", (new_val, entry_id))
        conn.commit()
        return {"starred": bool(new_val), "id": entry_id}
    finally:
        conn.close()


# ──────────────────────────────────────────────
# GET /api/entries/starred
# ──────────────────────────────────────────────

@router.get("/api/entries/starred")
async def get_starred(page: int = Query(default=1, ge=1), per_page: int = Query(default=30, ge=1, le=100)):
    conn = get_db_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM entries WHERE starred = 1").fetchone()[0]
        offset = (page - 1) * per_page
        rows = conn.execute(
            "SELECT id, title, source_url, auto_tags, content, LENGTH(content) as content_len, created_at FROM entries WHERE starred = 1 ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        ).fetchall()
        entries = []
        for r in rows:
            try:
                tag_list = json.loads(r["auto_tags"]) if r["auto_tags"] else []
            except (json.JSONDecodeError, TypeError):
                tag_list = []
            domain = ""
            try:
                domain = urllib.parse.urlparse(r["source_url"] or "").netloc
            except (AttributeError, ValueError):
                domain = ""
            entries.append({
                "id": r["id"], "title": r["title"] or "(no title)",
                "source_url": r["source_url"] or "", "tags": tag_list,
                "summary": (r["content"] or "")[:200], "content_len": r["content_len"],
                "created_at": r["created_at"], "domain": domain,
            })
        return {"entries": entries, "total": total, "page": page, "total_pages": max(1, (total + per_page - 1) // per_page)}
    finally:
        conn.close()


# ──────────────────────────────────────────────
# GET /api/entry/{entry_id}/related
# ──────────────────────────────────────────────

@router.get("/api/entry/{entry_id}/related")
async def get_related_entries(entry_id: str):
    """Return similar entries by vector similarity (or tag overlap fallback)."""
    # Find the entry's rowid and tags
    conn = get_db_conn()
    try:
        row = conn.execute(
            "SELECT rowid FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return JSONResponse({"error": "not found"}, status_code=404)
        entry_rowid = row["rowid"]

        entry_tags_raw = conn.execute(
            "SELECT auto_tags FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        try:
            entry_tags = (
                set(json.loads(entry_tags_raw["auto_tags"]))
                if entry_tags_raw and entry_tags_raw["auto_tags"]
                else set()
            )
        except (json.JSONDecodeError, TypeError):
            entry_tags = set()
    finally:
        conn.close()

    # Try vector similarity via sqlite-vec vec0
    try:
        vec_db = sqlite3.connect(str(DB_PATH))
        vec_db.enable_load_extension(True)
        sqlite_vec.load(vec_db)
        vec_db.enable_load_extension(False)
        try:
            similar = vec_db.execute(
                """
                SELECT rowid, distance
                FROM entries_v0
                WHERE v0 MATCH (
                    SELECT embedding FROM entries_v0 WHERE rowid = ?
                ) AND rowid != ?
                ORDER BY distance
                LIMIT 10
                """,
                (entry_rowid, entry_rowid),
            ).fetchall()
        finally:
            vec_db.close()

        if not similar:
            return []

        # Fetch matching entry details
        conn = get_db_conn()
        try:
            rowids = [r["rowid"] for r in similar]
            placeholders = ",".join("?" * len(rowids))
            rows = conn.execute(
                f"""
                SELECT rowid, id, title, source_url, auto_tags, content
                FROM entries
                WHERE rowid IN ({placeholders})
                """,
                rowids,
            ).fetchall()

            row_map = {r["rowid"]: r for r in rows}
            results = []
            for sr in similar:
                r = row_map.get(sr["rowid"])
                if r:
                    try:
                        tag_list = json.loads(r["auto_tags"]) if r["auto_tags"] else []
                    except (json.JSONDecodeError, TypeError):
                        tag_list = []
                    similarity = max(0, round((1 - sr["distance"]) * 100, 1))
                    # Compute shared concepts via tag intersection
                    related_tags = set(tag_list)
                    shared = list(entry_tags & related_tags)
                    results.append({
                        "id": r["id"],
                        "title": r["title"],
                        "tags": tag_list,
                        "summary": (r["content"] or "")[:200],
                        "similarity": similarity,
                        "url": r["source_url"] or "",
                        "shared_concepts": shared,
                    })
            return results
        finally:
            conn.close()

    except Exception as e:
        log.warning(f"Vector similarity failed for {entry_id}: {e}")
        # Fallback: tag overlap
        if not entry_tags:
            return []

        conn = get_db_conn()
        try:
            tag_conditions = " OR ".join(
                ["EXISTS (SELECT 1 FROM json_each(auto_tags) WHERE value = ?)" for _ in entry_tags]
            )
            params = list(entry_tags)
            params.append(entry_id)

            rows = conn.execute(
                f"""\n                SELECT id, title, source_url, auto_tags, content
                FROM entries
                WHERE ({tag_conditions})
                  AND id != ?
                ORDER BY created_at DESC
                LIMIT 10
                """,
                params,
            ).fetchall()

            results = []
            for r in rows:
                try:
                    tag_list = json.loads(r["auto_tags"]) if r["auto_tags"] else []
                except (json.JSONDecodeError, TypeError):
                    tag_list = []
                r_tags = set(tag_list)
                overlap = len(entry_tags & r_tags)
                shared_tags = list(entry_tags & r_tags)
                similarity = min(
                    100, round((overlap / max(len(entry_tags), 1)) * 100, 1)
                )
                results.append({
                    "id": r["id"],
                    "title": r["title"],
                    "tags": tag_list,
                    "summary": (r["content"] or "")[:200],
                    "similarity": similarity,
                    "url": r["source_url"] or "",
                    "shared_concepts": shared_tags,
                })

            results.sort(key=lambda x: -x["similarity"])
            return results
        finally:
            conn.close()


# ──────────────────────────────────────────────
# GET /api/similarity/search
# ──────────────────────────────────────────────

@router.get("/api/similarity/search")
async def similarity_search(q: str = Query(default="", max_length=500)):
    """Search entries by title (FTS) for the Similarity Explorer picker."""
    if not q:
        return {"entries": [], "total": 0}
    conn = get_db_conn()
    try:
        fts_query = q.replace('"', '""')
        rows = conn.execute(
            """SELECT e.id, e.title, e.source_url, e.auto_tags, e.content,
                      LENGTH(e.content) as content_len, e.created_at, e.starred
               FROM entries e
               WHERE e.rowid IN (SELECT rowid FROM entries_fts WHERE entries_fts MATCH ?)
               ORDER BY e.created_at DESC
               LIMIT 20""",
            (fts_query,),
        ).fetchall()
        entries = []
        for r in rows:
            try:
                tag_list = json.loads(r["auto_tags"]) if r["auto_tags"] else []
            except (json.JSONDecodeError, TypeError):
                tag_list = []
            entries.append({
                "id": r["id"],
                "title": r["title"] or "(no title)",
                "source_url": r["source_url"] or "",
                "tags": tag_list,
                "summary": (r["content"] or "")[:200],
                "content_len": r["content_len"],
                "created_at": r["created_at"],
                "starred": bool(r["starred"]),
            })
        return {
            "entries": entries,
            "total": len(entries),
        }
    finally:
        conn.close()
