#!/usr/bin/env python3
"""query.py — Query Pliny's index.

Usage:
    python3 src/query.py search "trading quant" [--limit N] [--after YYYY-MM-DD] [--before YYYY-MM-DD] [--json]
    python3 src/query.py search-vec "concept" [--limit N] [--after YYYY-MM-DD] [--before YYYY-MM-DD] [--json]
    python3 src/query.py hybrid "query" [--limit N] [--after YYYY-MM-DD] [--before YYYY-MM-DD] [--json]
    python3 src/query.py list
    python3 src/query.py recent [N]
    python3 src/query.py get <entry-id>
    python3 src/query.py tags [--json]
    python3 src/query.py tag <entry-id> <tag>
    python3 src/query.py delete <entry-id>
    python3 src/query.py archive <entry-id>

Programmatic use:
    from query import QueryEngine
    engine = QueryEngine()
    engine.search("trading quant")
    engine.hybrid("concept", limit=10)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

# Make src/ importable (works both as script and as imported module)
if (p := str(Path(__file__).resolve().parent)) not in sys.path:
    sys.path.insert(0, p)

from lib.paths import DB_PATH
from lib.schema import get_db
from lib.search import (
    QueryEngine,
    add_tag,
    archive_entry,
    count,
    delete_entry,
    entry_by_id,
    list_all,
    list_tags,
    recent_entries,
    search,
    search_hybrid,
    tag_entries,
)


# ── CLI formatters ──────────────────────────────────────────────────────


def _fmt(r: dict[str, Any]) -> str:
    tags_str = _tags_display(r.get("tags"))
    snippet = r.get("snippet", r.get("content", ""))
    if snippet:
        snippet_short = snippet[:80].replace("\n", " ")
        return (
            f"--- {r['id']}  {r['title']}  {r['source_url']}  {r['created_at']}"
            f"{tags_str}\n   {snippet_short}"
        )
    return (
        f"--- {r['id']}  {r['title']}  {r['source_url']}  {r['created_at']}"
        f"{tags_str}"
    )


def _fmt_detailed(r: dict[str, Any]) -> str:
    tags_str = _tags_display(r.get("tags"))
    lines = [
        f"--- {r['id']}",
        f"   {r['title']}",
        f"   {r['source_url']}",
        f"   {r['created_at']}",
    ]
    if tags_str:
        lines.append(f"   tags:{tags_str}")
    snippet = r.get("snippet", r.get("content", ""))
    if snippet:
        lines.append(f"   {snippet}")
    return "\n".join(lines)


def _tags_display(raw_tags: Any) -> str:
    if not raw_tags:
        return ""
    try:
        tag_list = json.loads(raw_tags)
        if tag_list:
            return "  " + ", ".join(tag_list)
    except (json.JSONDecodeError, TypeError):
        pass
    return ""


def _json_output(results: list[dict[str, Any]]) -> str:
    out: list[dict[str, Any]] = []
    for r in results:
        item: dict[str, Any] = {
            "id": r.get("id"),
            "title": r.get("title"),
            "source_url": r.get("source_url"),
            "created_at": r.get("created_at"),
            "tags": _parse_tags(r.get("tags")),
        }
        media_path = r.get("media_path")
        if media_path:
            item["media_path"] = media_path
        content = r.get("content")
        if content:
            item["content"] = content
        snippet = r.get("snippet")
        if snippet:
            item["snippet"] = snippet
        distance = r.get("distance")
        if distance is not None:
            item["distance"] = distance
        out.append(item)
    return json.dumps(out, indent=2)


def _parse_tags(raw_tags: Any) -> list[str]:
    if not raw_tags:
        return []
    try:
        result = json.loads(raw_tags)
        if isinstance(result, list):
            return result
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_common_args(args: list[str]) -> tuple[list[str], dict[str, Any]]:
    kwargs: dict[str, Any] = {}
    remaining: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--limit" and i + 1 < len(args):
            try:
                kwargs["limit"] = int(args[i + 1])
            except (ValueError, IndexError):
                print(f"Error: --limit requires a number, got '{args[i + 1] if i + 1 < len(args) else '?'}'")
                return [], {}
            i += 2
        elif arg == "--after" and i + 1 < len(args):
            kwargs["after"] = args[i + 1]
            i += 2
        elif arg == "--before" and i + 1 < len(args):
            kwargs["before"] = args[i + 1]
            i += 2
        elif arg == "--json":
            kwargs["json"] = True
            i += 1
        else:
            remaining.append(arg)
            i += 1
    return remaining, kwargs


# ── CLI ─────────────────────────────────────────────────────────────────


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__.strip())
        return

    remaining, common_kw = _parse_common_args(args)
    if not remaining:
        print(__doc__.strip())
        return

    cmd = remaining[0]
    use_json = common_kw.get("json", False)
    limit = common_kw.get("limit", 20)
    after = common_kw.get("after")
    before = common_kw.get("before")

    db = get_db(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        # ── search ──────────────────────────────────────────────────────
        if cmd == "search":
            q = " ".join(remaining[1:])
            if after is not None or before is not None:
                results = search(db, q=q, mode="fts", per_page=limit, date_from=after, date_to=before)
            else:
                results = search(db, q=q, mode="fts", per_page=limit)
            if not results:
                print("No results.")
                return
            if use_json:
                print(_json_output(results))
            else:
                for r in results:
                    print(_fmt(r))

        # ── search-vec ──────────────────────────────────────────────────
        elif cmd == "search-vec":
            q = " ".join(remaining[1:])
            from lib.search import QueryEngine

            with QueryEngine(DB_PATH) as qe:
                if after is not None or before is not None:
                    results = qe._search_vec_filtered(q, limit=limit, after=after, before=before)
                else:
                    results = qe.search_vec(q, limit=limit)
            if not results:
                print("No results.")
                return
            if use_json:
                print(_json_output(results))
            else:
                for r in results:
                    dist = f"  (dist: {r['distance']:.4f})" if "distance" in r else ""
                    print(f"--- {r['id']}{dist}")
                    print(f"   {r['title']}")
                    print(f"   {r['source_url']}")
                    print(f"   {r['created_at']}")
                    print()

        # ── hybrid ──────────────────────────────────────────────────────
        elif cmd == "hybrid":
            q = " ".join(remaining[1:])
            results = search(db, q=q, mode="hybrid", per_page=limit, date_from=after, date_to=before)
            if not results:
                print("No results.")
                return
            if use_json:
                print(_json_output(results))
            else:
                for r in results:
                    print(_fmt_detailed(r))
                    print()

        # ── list ────────────────────────────────────────────────────────
        elif cmd == "list":
            entries = list_all(db, limit=limit)
            for e in entries:
                print(f"  {e['id']:30s}  {e['created_at'][:10]}  {e['title'][:50]}")

        # ── recent ──────────────────────────────────────────────────────
        elif cmd == "recent":
            n = int(remaining[1]) if len(remaining) > 1 else 10
            entries = recent_entries(db, limit=n)
            for e in entries:
                print(f"  {e['id']:30s}  {e['created_at'][:10]}  {e['title'][:50]}")

        # ── get ─────────────────────────────────────────────────────────
        elif cmd == "get":
            if len(remaining) < 2:
                print("Usage: query.py get <entry-id>")
                return
            entry = entry_by_id(db, remaining[1])
            if not entry:
                print(f"No entry: {remaining[1]}")
                return
            print(f"# {entry['title']}")
            print(f"URL: {entry['source_url']}")
            if entry.get('archived'):
                print(f"Archived: {entry['archived']}")
            print(f"Created: {entry['created_at']}")
            print(f"Modified: {entry['modified_at']}")
            tags_disp = _tags_display(entry.get("tags"))
            if tags_disp:
                print(f"Tags:{tags_disp}")
            print()
            print(entry["content"])

        # ── tags ────────────────────────────────────────────────────────
        elif cmd == "tags":
            tags = list_tags(db)
            if not tags:
                print("No tags found.")
                return
            if use_json:
                print(json.dumps(tags, indent=2))
            else:
                for t in tags:
                    print(f"  {t['tag']:25s}  {t['count']}")

        # ── tag ─────────────────────────────────────────────────────────
        elif cmd == "tag":
            if len(remaining) < 3:
                print("Usage: query.py tag <entry-id> <tag>")
                return
            entry_id = remaining[1]
            tag = remaining[2]
            if add_tag(db, entry_id, tag):
                print(f"Tag '{tag}' added to {entry_id}.")
            else:
                print(f"No entry: {entry_id}")

        # ── delete ──────────────────────────────────────────────────────
        elif cmd == "delete":
            if len(remaining) < 2:
                print("Usage: query.py delete <entry-id>")
                return
            entry_id = remaining[1]
            if delete_entry(db, entry_id):
                print(f"Deleted {entry_id}.")
            else:
                print(f"No entry: {entry_id}")

        # ── archive ─────────────────────────────────────────────────────
        elif cmd == "archive":
            if len(remaining) < 2:
                print("Usage: query.py archive <entry-id>")
                return
            entry_id = remaining[1]
            if archive_entry(db, entry_id):
                print(f"Archived {entry_id}.")
            else:
                print(f"No entry: {entry_id}")

        else:
            print(f"Unknown command: {cmd}")
            print(__doc__.strip())
    finally:
        db.close()


if __name__ == "__main__":
    main()
