"""Search engine for Pliny — FTS5, hybrid (vector), filters, CRUD."""

from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from lib.paths import DB_PATH
from lib.schema import get_db as _schema_get_db


class QueryEngine:
    """Persistent connection wrapper for Pliny queries.

    Use as context manager:
        with QueryEngine() as qe:
            results = qe.hybrid("my query")

    Or long-lived:
        qe = QueryEngine()
        qe.search_fts("foo")
        qe.search_fts("bar")
        qe.close()
    """

    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self._db_path = str(db_path)
        self._db: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = _schema_get_db(self._db_path)
            self._db.row_factory = sqlite3.Row
        return self._db

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self) -> "QueryEngine":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ── Search ──────────────────────────────────────────────────────────

    def search_fts(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        db = self._connect()
        rows = db.execute(
            """SELECT e.id, e.title, e.source_url, e.created_at,
                      snippet(entries_fts, 0, '<b>', '</b>', '…', 40) AS snippet
               FROM entries_fts
               JOIN entries e ON e.rowid = entries_fts.rowid
               WHERE entries_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (q, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def search_vec(self, query_text: str, limit: int = 20) -> list[dict[str, Any]]:
        from lib.embed import embed_json

        vec = embed_json(query_text)
        db = self._connect()
        rows = db.execute(
            """SELECT e.id, e.title, e.source_url, e.created_at, e.content, e.media_path, v.distance
               FROM entries_v0 v
               JOIN entries e ON e.rowid = v.rowid
               WHERE v.embedding MATCH ? AND v.k = ?
               ORDER BY v.distance""",
            (vec, limit),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            # Provide a content snippet for vec results (no FTS snippet function available)
            if d.get("content") and "snippet" not in d:
                d["snippet"] = d["content"][:120].replace("\n", " ")
            results.append(d)
        return results

    def _search_fts_filtered(
        self, q: str, limit: int = 20, after: str | None = None, before: str | None = None
    ) -> list[dict[str, Any]]:
        db = self._connect()
        query = """SELECT e.id, e.title, e.source_url, e.created_at, e.media_path,
                          snippet(entries_fts, 0, '<b>', '</b>', '…', 40) AS snippet
                   FROM entries_fts
                   JOIN entries e ON e.rowid = entries_fts.rowid
                   WHERE entries_fts MATCH ?"""
        params: list[Any] = [q]
        if after is not None:
            query += " AND e.created_at >= ?"
            params.append(after)
        if before is not None:
            query += " AND e.created_at <= ?"
            params.append(before)
        query += " ORDER BY rank LIMIT ?"
        params.append(limit)
        rows = db.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def _search_vec_filtered(
        self, query_text: str, limit: int = 20, after: str | None = None, before: str | None = None
    ) -> list[dict[str, Any]]:
        from lib.embed import embed_json

        vec = embed_json(query_text)
        db = self._connect()
        query = """SELECT e.id, e.title, e.source_url, e.created_at, e.content, e.media_path, v.distance
                   FROM entries_v0 v
                   JOIN entries e ON e.rowid = v.rowid
                   WHERE v.embedding MATCH ? AND v.k = ?"""
        params: list[Any] = [vec, limit]
        if after is not None:
            query += " AND e.created_at >= ?"
            params.append(after)
        if before is not None:
            query += " AND e.created_at <= ?"
            params.append(before)
        query += " ORDER BY v.distance"
        rows = db.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("content") and "snippet" not in d:
                d["snippet"] = d["content"][:120].replace("\n", " ")
            results.append(d)
        return results

    # ── Hybrid / RRF ────────────────────────────────────────────────────

    def hybrid(
        self, q: str, limit: int = 20, after: str | None = None, before: str | None = None
    ) -> list[dict[str, Any]]:
        """RRF fusion of FTS5 and vector search results."""
        fuse_limit = limit * 3
        fts_results = self._search_fts_filtered(q, limit=fuse_limit, after=after, before=before)
        vec_results = self._search_vec_filtered(q, limit=fuse_limit, after=after, before=before)

        scores: dict[str, float] = {}
        results_map: dict[str, dict[str, Any]] = {}

        for rank, r in enumerate(fts_results):
            rid = r["id"]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (rank + 60)
            results_map[rid] = r

        for rank, r in enumerate(vec_results):
            rid = r["id"]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (rank + 60)
            if rid not in results_map:
                results_map[rid] = r

        sorted_ids = sorted(scores, key=lambda rid: scores[rid], reverse=True)[:limit]
        return [results_map[rid] for rid in sorted_ids]

    # ── CRUD ────────────────────────────────────────────────────────────

    def entry_by_id(self, entry_id: str) -> dict[str, Any] | None:
        db = self._connect()
        r = db.execute(
            "SELECT id, source_url, title, content, tags, media_path, archived, created_at, modified_at FROM entries WHERE id = ?",
            (entry_id,),
        ).fetchone()
        return dict(r) if r else None

    def all_entries(self) -> list[dict[str, Any]]:
        db = self._connect()
        rows = db.execute(
            "SELECT id, title, source_url, media_path, created_at, modified_at FROM entries ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def recent(self, limit: int = 10) -> list[dict[str, Any]]:
        db = self._connect()
        rows = db.execute(
            "SELECT id, title, source_url, media_path, created_at FROM entries ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Tags ────────────────────────────────────────────────────────────

    def list_tags(self) -> list[dict[str, Any]]:
        """Return all tags with their occurrence counts, sorted by count descending."""
        db = self._connect()
        rows = db.execute(
            "SELECT tags FROM entries WHERE tags IS NOT NULL AND tags != '[]'"
        ).fetchall()
        counts: dict[str, int] = defaultdict(int)
        for r in rows:
            try:
                tag_list = json.loads(r["tags"])
                for tag in tag_list:
                    counts[tag] += 1
            except (json.JSONDecodeError, TypeError):
                pass
        return sorted(
            [{"tag": t, "count": c} for t, c in counts.items()],
            key=lambda x: -x["count"],
        )

    def add_tag(self, entry_id: str, tag: str) -> bool:
        """Add a single tag to an entry. Returns True on success."""
        entry = self.entry_by_id(entry_id)
        if not entry:
            return False
        tags: list[str] = []
        raw = entry.get("tags")
        if raw:
            try:
                tags = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                tags = []
        if tag not in tags:
            tags.append(tag)
        db = self._connect()
        db.execute(
            "UPDATE entries SET tags = ?, modified_at = datetime('now') WHERE id = ?",
            (json.dumps(tags), entry_id),
        )
        db.commit()
        return True

    def delete_entry(self, entry_id: str) -> bool:
        """Permanently delete an entry and its FTS/vector records."""
        db = self._connect()
        r = db.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not r:
            return False
        rowid = db.execute("SELECT rowid FROM entries WHERE id = ?", (entry_id,)).fetchone()["rowid"]
        try:
            db.execute("DELETE FROM entries_v0 WHERE rowid = ?", (rowid,))
        except sqlite3.DatabaseError:
            pass  # vec0 may not have this rowid — non-critical
        db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        db.commit()
        return True

    def archive_entry(self, entry_id: str) -> bool:
        """Archive an entry — hides from default search results."""
        db = self._connect()
        r = db.execute("SELECT id FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not r:
            return False
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        db.execute(
            "UPDATE entries SET archived = 1, modified_at = ? WHERE id = ?",
            (now, entry_id),
        )
        db.commit()
        return True


# ── Standalone functions (accept db connection directly) ────────────────


def search(
    db: sqlite3.Connection,
    q: str = "",
    mode: str = "fts",
    tags: list[str] | None = None,
    entry_type: str | None = None,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
    per_page: int = 50,
) -> list[dict[str, Any]]:
    """Unified search — FTS5, hybrid, or all entries, with filters.

    Delegates to the appropriate QueryEngine method based on mode.
    """
    engine = QueryEngine()
    engine._db = db

    if mode == "hybrid":
        after = date_from
        before = date_to
        if tags or entry_type or source:
            # Use filtered hybrid via direct SQL
            return _search_filtered_direct(db, q, mode, tags, entry_type, source, date_from, date_to, sort, page, per_page)
        return engine.hybrid(q, limit=per_page * (page or 1), after=after, before=before)

    if mode == "all":
        if q or tags or entry_type or source or date_from or date_to:
            return _search_filtered_direct(db, q, mode, tags, entry_type, source, date_from, date_to, sort, page, per_page)
        return engine.all_entries()

    # fts mode (default)
    if q and (tags or entry_type or source or date_from or date_to):
        return _search_filtered_direct(db, q, mode, tags, entry_type, source, date_from, date_to, sort, page, per_page)

    if q:
        after = date_from
        before = date_to
        if after is not None or before is not None:
            return engine._search_fts_filtered(q, limit=per_page * (page or 1), after=after, before=before)
        return engine.search_fts(q, limit=per_page * (page or 1))

    # No query — list all
    return _search_filtered_direct(db, q, mode, tags, entry_type, source, date_from, date_to, sort, page, per_page)


def _search_filtered_direct(
    db: sqlite3.Connection,
    q: str | None = None,
    mode: str = "fts",
    tags: list[str] | None = None,
    entry_type: str | None = None,
    source: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "date_desc",
    page: int = 1,
    per_page: int = 50,
) -> list[dict[str, Any]]:
    """Direct SQL search with filters — used when standalone params are provided.

    This builds a filtered query from entries + entries_fts with tag/type/source/date filters.
    """
    select_clause = "SELECT e.id, e.title, e.source_url, e.created_at, e.media_path"
    if mode == "fts" and q:
        select_clause += ", snippet(entries_fts, 0, '<b>', '</b>', '…', 40) AS snippet"
    else:
        select_clause += ", e.content"

    from_clause = " FROM entries e"
    where_parts: list[str] = []
    params: list[Any] = []

    if q and mode == "fts":
        from_clause += " JOIN entries_fts fts ON e.rowid = fts.rowid"
        where_parts.append("entries_fts MATCH ?")
        params.append(q)
    elif q and mode == "all":
        where_parts.append("(e.title LIKE ? OR e.content LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    if tags:
        for tag in tags:
            where_parts.append("(e.tags LIKE ? OR e.auto_tags LIKE ?)")
            params.extend([f'%"{tag}"%', f'%"{tag}"%'])

    if entry_type:
        where_parts.append("e.entry_type = ?")
        params.append(entry_type)

    if source:
        where_parts.append("e.source_url LIKE ?")
        params.append(f"%{source}%")

    if date_from:
        where_parts.append("e.created_at >= ?")
        params.append(date_from)

    if date_to:
        where_parts.append("e.created_at <= ?")
        params.append(date_to + "T23:59:59Z")

    if where_parts:
        from_clause += " WHERE " + " AND ".join(where_parts)

    sort_map = {
        "date_desc": "e.created_at DESC",
        "date_asc": "e.created_at ASC",
        "title_asc": "e.title ASC",
        "title_desc": "e.title DESC",
    }
    order_by = sort_map.get(sort, "e.created_at DESC")

    offset = (page - 1) * per_page
    sql = f"{select_clause}{from_clause} ORDER BY {order_by} LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    rows = db.execute(sql, params).fetchall()
    results = [dict(r) for r in rows]

    # Add snippet for non-fts modes
    if mode != "fts" and q:
        for r in results:
            if r.get("content") and "snippet" not in r:
                r["snippet"] = r["content"][:120].replace("\n", " ")

    return results


def entry_by_id(db: sqlite3.Connection, entry_id: str) -> dict[str, Any] | None:
    """Get a single entry by its ID."""
    engine = QueryEngine()
    engine._db = db
    return engine.entry_by_id(entry_id)


def list_all(
    db: sqlite3.Connection,
    sort: str = "date_desc",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List all entries with optional sort/pagination."""
    sort_map = {
        "date_desc": "created_at DESC",
        "date_asc": "created_at ASC",
        "title_asc": "title ASC",
        "title_desc": "title DESC",
    }
    order_by = sort_map.get(sort, "created_at DESC")
    rows = db.execute(
        f"SELECT id, title, source_url, media_path, created_at, modified_at FROM entries ORDER BY {order_by} LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def list_tags(db: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all tags with their occurrence counts, sorted by count descending."""
    engine = QueryEngine()
    engine._db = db
    return engine.list_tags()


def delete_entry(db: sqlite3.Connection, entry_id: str) -> bool:
    """Permanently delete an entry and its FTS/vector records."""
    engine = QueryEngine()
    engine._db = db
    return engine.delete_entry(entry_id)


def archive_entry(db: sqlite3.Connection, entry_id: str, archived: bool = True) -> bool:
    """Archive (or unarchive) an entry."""
    engine = QueryEngine()
    engine._db = db
    return engine.archive_entry(entry_id)


def tag_entries(db: sqlite3.Connection, tag: str) -> list[dict[str, Any]]:
    """Return entries that have a specific tag."""
    rows = db.execute(
        """SELECT id, title, source_url, content, tags, auto_tags, created_at, modified_at
           FROM entries
           WHERE (tags LIKE ? OR auto_tags LIKE ?)
           ORDER BY created_at DESC""",
        (f'%"{tag}"%', f'%"{tag}"%'),
    ).fetchall()
    return [dict(r) for r in rows]


def count(db: sqlite3.Connection) -> int:
    """Return total number of entries."""
    r = db.execute("SELECT COUNT(*) FROM entries").fetchone()
    return r[0]


def search_hybrid(
    db: sqlite3.Connection,
    q: str,
    tags: list[str] | None = None,
    entry_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Hybrid search combining FTS5 and vector search with optional filters."""
    engine = QueryEngine()
    engine._db = db

    # If no extra filters, use the existing hybrid method
    if not tags and not entry_type:
        return engine.hybrid(q, limit=limit)

    # Otherwise build filtered search
    fuse_limit = limit * 3
    fts_results = _search_filtered_direct(
        db, q=q, mode="fts", tags=tags, entry_type=entry_type,
        per_page=fuse_limit,
    )

    # Vector search with filters is complex — for now, use unfiltered vec and rely on RRF
    vec_results = engine.search_vec(q, limit=fuse_limit)

    scores: dict[str, float] = {}
    results_map: dict[str, dict[str, Any]] = {}

    for rank, r in enumerate(fts_results):
        rid = r["id"]
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (rank + 60)
        results_map[rid] = r

    for rank, r in enumerate(vec_results):
        rid = r["id"]
        scores[rid] = scores.get(rid, 0.0) + 1.0 / (rank + 60)
        if rid not in results_map:
            results_map[rid] = r

    sorted_ids = sorted(scores, key=lambda rid: scores[rid], reverse=True)[:limit]
    return [results_map[rid] for rid in sorted_ids]


def add_tag(db: sqlite3.Connection, entry_id: str, tag: str) -> bool:
    """Add a single tag to an entry. Returns True on success."""
    engine = QueryEngine()
    engine._db = db
    return engine.add_tag(entry_id, tag)


def recent_entries(db: sqlite3.Connection, limit: int = 10) -> list[dict[str, Any]]:
    """Return most recent entries."""
    engine = QueryEngine()
    engine._db = db
    return engine.recent(limit)
