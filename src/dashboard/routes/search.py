"""Search and Q&A routes — entry listing, full-text search, and Ask Pliny."""

import json
import logging
import urllib.parse
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from lib.llm import call_llm

from .shared import get_db_conn, SEARCH_SOURCES, log, SAVED_QUERIES_PATH, SAVED_QUERIES_CHECK_PATH, ROOT, connected_websockets, connected_websockets_lock

router = APIRouter()


# ──────────────────────────────────────────────
# GET /api/entries  — main search/list endpoint
# ──────────────────────────────────────────────

@router.get("/api/entries")
async def search_entries(
    q: str = Query(default="", max_length=500),
    tags: str = Query(default="", max_length=500),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=24, ge=1, le=100),
    starred: str = Query(default="", max_length=10),
    source: str = Query(default="", max_length=50),
    date_from: str = Query(default="", max_length=20),
    date_to: str = Query(default="", max_length=20),
    content: str = Query(default="all", max_length=20),
    sort: str = Query(default="date_desc", max_length=20),
    mode: str = Query(default="fts", max_length=10),
    entry_type: str = Query(default="", max_length=30),
):
    """Search entries by text query, tags, source, date range, content size and more."""
    conn = get_db_conn()
    try:
        selected_tags = [t.strip().lower() for t in tags.split(",") if t.strip()]

        base_query = """\
            SELECT e.id, e.title, e.source_url, e.auto_tags,
                   e.created_at, e.content, e.starred,
                   e.entry_type, e.extraction_status,
                   LENGTH(e.content) as content_len
            FROM entries e\
        """
        count_query = "SELECT COUNT(*) FROM entries e"
        where_parts = []
        params = []

        if q:
            fts_query = q.replace('"', '""')
            where_parts.append(
                "e.rowid IN (SELECT rowid FROM entries_fts WHERE entries_fts MATCH ?)"
            )
            params.append(fts_query)

        if selected_tags:
            for tag in selected_tags:
                where_parts.append("e.auto_tags LIKE ?")
                params.append(f'%"{tag}"%')

        if starred == "1":
            where_parts.append("e.starred = 1")

        if source and source in SEARCH_SOURCES:
            where_parts.append(SEARCH_SOURCES[source][0])

        if date_from:
            where_parts.append("e.created_at >= ?")
            params.append(date_from)
        if date_to:
            where_parts.append("e.created_at <= ?")
            params.append(date_to + "T23:59:59Z")

        if content == "thin":
            where_parts.append("LENGTH(e.content) < 200")
        elif content == "enriched":
            where_parts.append("LENGTH(e.content) > 10000")
        elif content == "normal":
            where_parts.append("LENGTH(e.content) >= 200 AND LENGTH(e.content) <= 10000")

        if entry_type:
            where_parts.append("e.entry_type = ?")
            params.append(entry_type)

        if where_parts:
            where_clause = " WHERE " + " AND ".join(where_parts)
            base_query += where_clause
            count_query += where_clause

        total = conn.execute(count_query, params).fetchone()[0]

        offset = (page - 1) * per_page

        if sort == "date_asc":
            base_query += " ORDER BY e.created_at ASC"
        elif sort == "size_desc":
            base_query += " ORDER BY content_len DESC"
        elif sort == "size_asc":
            base_query += " ORDER BY content_len ASC"
        elif sort == "title_asc":
            base_query += " ORDER BY e.title ASC"
        else:
            base_query += " ORDER BY e.created_at DESC"

        base_query += " LIMIT ? OFFSET ?"
        params.extend([per_page, offset])

        rows = conn.execute(base_query, params).fetchall()

        entries = []
        for r in rows:
            try:
                tag_list = json.loads(r["auto_tags"]) if r["auto_tags"] else []
            except (json.JSONDecodeError, TypeError):
                tag_list = []

            content = r["content"] or ""
            preview = content[:200] if len(content) > 200 else content

            url = r["source_url"] or ""
            domain = "other"
            for key, (clause, label) in SEARCH_SOURCES.items():
                if "source_url LIKE" in clause:
                    if f".{key}" in url or f"://{key}" in url or f"/{key}" in url:
                        domain = label
                        break

            entries.append({
                "id": r["id"],
                "title": r["title"],
                "source_url": url,
                "tags": tag_list,
                "summary": (r["content"] or "")[:200],
                "content_len": r["content_len"],
                "domain": domain,
                "created_at": r["created_at"],
                "starred": bool(r["starred"]),
                "preview": preview,
                "entry_type": r["entry_type"] or "bookmark",
                "extraction_status": r["extraction_status"] or "pending",
            })

        total_pages = max(1, (total + per_page - 1) // per_page)

        return {
            "entries": entries,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────
# GET /api/search  — deprecated, delegates to /api/entries
# ──────────────────────────────────────────────

@router.get("/api/search")
async def search_advanced(
    q: str = Query(default="", max_length=500),
    tags: str = Query(default="", max_length=500),
    source: str = Query(default="", max_length=50),
    date_from: str = Query(default="", max_length=20),
    date_to: str = Query(default="", max_length=20),
    content: str = Query(default="all", max_length=20),
    sort: str = Query(default="date_desc", max_length=20),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=30, ge=1, le=100),
):
    """DEPRECATED: Delegates to /api/entries."""
    return await search_entries(
        q=q, tags=tags, page=page, per_page=per_page,
        source=source, date_from=date_from, date_to=date_to,
        content=content, sort=sort, mode="fts",
    )


# ──────────────────────────────────────────────
# POST /api/search/fts
# ──────────────────────────────────────────────

@router.post("/api/search/fts")
async def search_fts(request: Request):
    """FTS5 full-text search."""
    body = await request.json()
    q = body.get("q", "").strip()
    limit = body.get("limit", 30)

    conn = get_db_conn()
    try:
        if q:
            fts_query = q.replace('"', '""')
            rows = conn.execute("""\
                SELECT e.id, e.title, e.source_url, e.auto_tags,
                       e.content, e.created_at, e.starred
                FROM entries e
                WHERE e.rowid IN (SELECT rowid FROM entries_fts WHERE entries_fts MATCH ?)
                ORDER BY e.created_at DESC
                LIMIT ?\
            """, (fts_query, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT id, title, source_url, auto_tags,
                       content, created_at, starred
                FROM entries
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,)).fetchall()

        results = []
        for r in rows:
            try:
                tag_list = json.loads(r["auto_tags"]) if r["auto_tags"] else []
            except (json.JSONDecodeError, TypeError):
                tag_list = []
            content = r["content"] or ""
            results.append({
                "id": r["id"],
                "title": r["title"],
                "source_url": r["source_url"],
                "tags": tag_list,
                "summary": (r["content"] or "")[:200],
                "content_preview": content[:300] if len(content) > 300 else content,
                "created_at": r["created_at"],
                "starred": bool(r["starred"]),
            })

        return {"results": results, "mode": "fts"}
    finally:
        conn.close()


# ──────────────────────────────────────────────
# POST /api/ask — LLM-powered Q&A
# ──────────────────────────────────────────────


@router.post("/api/ask")
async def ask_pliny(body: dict):
    """Ask a natural-language question about your saved knowledge.

    Request: {"q": "what do I know about AI agents?"}
    Response: {"answer": "...", "sources": [...]}
    """
    question = body.get("q", "").strip()
    if not question or len(question) > 1000:
        return JSONResponse({"error": "empty or too long"}, status_code=400)

    # 1. Search — use simple LIKE for robustness, since LLM handles synthesis
    conn = get_db_conn()
    try:
        keywords = [w.strip().lower() for w in question.split() if len(w.strip()) > 2]
        if not keywords:
            keywords = [question[:50]]
        like_clauses = " OR ".join(
            ["(e.title LIKE ? OR e.content LIKE ?)" for _ in keywords]
        )
        params = []
        for kw in keywords:
            params.extend([f"%{kw}%", f"%{kw}%"])
        fts_rows = conn.execute(
            f"SELECT e.id, e.title, e.source_url, e.auto_tags, e.content "
            f"FROM entries e WHERE {like_clauses} "
            f"ORDER BY e.created_at DESC LIMIT 12",
            params,
        ).fetchall()
    finally:
        conn.close()

    if not fts_rows:
        return {"answer": "I couldn't find anything relevant in your saved bookmarks. Try rephrasing or saving more content on this topic.", "sources": []}

    # 2. Build context
    context_parts = []
    sources = []
    for r in fts_rows:
        try:
            tags = json.loads(r["auto_tags"]) if r["auto_tags"] else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        tag_str = ", ".join(tags) if tags else "(no tags)"
        content = r["content"] or ""
        summary = (r["content"] or "")[:200]
        preview = content[:1500] if len(content) > 1500 else content

        context_parts.append(
            f"## Source: {r['title']}\n"
            f"URL: {r['source_url']}\n"
            f"Tags: {tag_str}\n"
            f"Summary: {summary}\n"
            f"Content excerpt: {preview}\n"
        )
        sources.append({
            "id": r["id"],
            "title": r["title"],
            "url": r["source_url"],
            "tags": tags,
            "summary": summary,
        })

    context = "\n---\n".join(context_parts)

    # 3. Call LLM for synthesis
    system_prompt = (
        "You are an analytical assistant reviewing the user's personal knowledge base. "
        "You have been given excerpts from their saved bookmarks, articles, and notes. "
        "Answer their question based SOLELY on these sources. "
        "If the sources don't contain enough information, say so clearly. "
        "Cite specific sources by title when making claims. "
        "Be concise and direct — no fluff."
    )

    user_prompt = f"""Here are the relevant entries from my knowledge base:

{context}

Based on these sources, please answer: {question}"""

    try:
        answer = call_llm(system_prompt, user_prompt, max_tokens=1024, temperature=0.3)
        if not answer:
            answer = "Sorry, I couldn't generate an answer."
    except Exception as e:
        answer = f"Error contacting DeepSeek: {e}"

    return {"answer": answer, "sources": sources}


# ──────────────────────────────────────────────
# Saved queries endpoints
# ──────────────────────────────────────────────

@router.post("/api/saved-queries/sync")
async def sync_saved_queries(request: Request):
    """Sync saved queries from client to server."""
    body = await request.json()
    SAVED_QUERIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAVED_QUERIES_PATH.write_text(json.dumps(body, indent=2))
    return {"status": "synced", "count": len(body)}


@router.get("/api/saved-queries")
async def get_saved_queries():
    """Get saved queries from server."""
    if SAVED_QUERIES_PATH.exists():
        return json.loads(SAVED_QUERIES_PATH.read_text())
    return {}


@router.get("/api/saved-queries/check/{name}")
async def check_saved_query(name: str):
    """Check a saved query for new entries since last check."""
    path = SAVED_QUERIES_CHECK_PATH
    last_checks = {}
    if path.exists():
        last_checks = json.loads(path.read_text())
    last_check = last_checks.get(name, datetime.now(timezone.utc).isoformat())

    if SAVED_QUERIES_PATH.exists():
        all_queries = json.loads(SAVED_QUERIES_PATH.read_text())
    else:
        return {"new": 0, "entries": []}

    q = all_queries.get(name)
    if not q:
        return {"error": "query not found", "new": 0, "entries": []}

    conn = get_db_conn()
    try:
        where = []
        params = []
        if q.get("q"):
            where.append("id LIKE ?")
            params.append(f"%{q['q']}%")
        if q.get("tags") and len(q["tags"]) > 0:
            placeholders = ",".join("?" for _ in q["tags"])
            where.append(f"EXISTS (SELECT 1 FROM json_each(auto_tags) WHERE value IN ({placeholders}))")
            params.extend(q["tags"])
        if q.get("source"):
            where.append("source_url LIKE ?")
            params.append(f"%{q['source']}%")

        where.append("created_at > ?")
        params.append(last_check)

        sql = "SELECT id, title, source_url, created_at FROM entries"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT 20"

        rows = conn.execute(sql, params).fetchall()
        entries = [dict(r) for r in rows]
        new_count = len(entries)

        # Update last check time
        last_checks[name] = datetime.now(timezone.utc).isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(last_checks, indent=2))

        # Broadcast via WebSocket if new entries found
        if new_count > 0:
            msg = json.dumps({
                "type": "query_alert",
                "query_name": name,
                "new": new_count,
                "entries": entries,
            })
            dead = set()
            async with connected_websockets_lock:
                for ws in connected_websockets:
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.add(ws)
                connected_websockets.difference_update(dead)

        return {"new": new_count, "entries": entries}
    finally:
        conn.close()


@router.get("/api/saved-queries/check-all")
async def check_all_saved_queries():
    """Check all alerted saved queries for new entries."""
    if SAVED_QUERIES_PATH.exists():
        all_queries = json.loads(SAVED_QUERIES_PATH.read_text())
    else:
        return {"results": {}}

    results = {}
    for name, q in all_queries.items():
        if q.get("alert"):
            check_path = SAVED_QUERIES_CHECK_PATH
            last_checks = {}
            if check_path.exists():
                last_checks = json.loads(check_path.read_text())
            last_check = last_checks.get(name, datetime.now(timezone.utc).isoformat())

            conn = get_db_conn()
            try:
                where = ["created_at > ?"]
                params = [last_check]
                if q.get("q"):
                    where.append("id LIKE ?")
                    params.append(f"%{q['q']}%")
                if q.get("tags") and len(q["tags"]) > 0:
                    placeholders = ",".join("?" for _ in q["tags"])
                    where.append(f"EXISTS (SELECT 1 FROM json_each(auto_tags) WHERE value IN ({placeholders}))")
                    params.extend(q["tags"])

                rows = conn.execute(
                    "SELECT id, title, source_url, created_at FROM entries WHERE " + " AND ".join(where) + " ORDER BY created_at DESC LIMIT 10",
                    params
                ).fetchall()
                new_count = len(rows)
                if new_count > 0:
                    results[name] = {"new": new_count, "entries": [dict(r) for r in rows]}
                last_checks[name] = datetime.now(timezone.utc).isoformat()
            finally:
                conn.close()

        check_path = SAVED_QUERIES_CHECK_PATH
        check_path.parent.mkdir(parents=True, exist_ok=True)
        check_path.write_text(json.dumps(last_checks, indent=2))

    return {"results": results}
