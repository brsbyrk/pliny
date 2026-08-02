#!/usr/bin/env python3
"""reprocess.py — Re-run extractors on existing entries to upgrade content quality.

Usage:
    python3 src/reprocess.py --source youtube    # Re-extract all YouTube entries
    python3 src/reprocess.py --source reddit     # Re-extract all Reddit entries
    python3 src/reprocess.py --source x          # Re-extract all X entries
    python3 src/reprocess.py --all               # All sources
    python3 src/reprocess.py --source youtube --dry-run  # Preview only, no writes
    python3 src/reprocess.py --source youtube --limit 5  # Only first 5 entries
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Add src/ to sys.path so we can import lib.* and ingest.* modules
_SRC = Path(__file__).resolve().parent
sys.path.insert(0, str(_SRC.parent))

from lib.paths import DB_PATH
from lib.schema import get_db
from ingest.url_ingest import extract_youtube, extract_reddit, extract_x

# ---------------------------------------------------------------------------
# Source → URL pattern matching
# ---------------------------------------------------------------------------

SOURCE_CONFIG = {
    "youtube": {
        "patterns": ("%youtube.com%", "%youtu.be%"),
        "extractor": extract_youtube,
        "label": "YouTube",
    },
    "reddit": {
        "patterns": ("%reddit.com%",),
        "extractor": extract_reddit,
        "label": "Reddit",
    },
    "x": {
        "patterns": ("%x.com%", "%twitter.com%"),
        "extractor": extract_x,
        "label": "X",
    },
}


def _build_source_sql(sources: list[str]) -> tuple[str, list[str]]:
    """Build SQL WHERE clause matching source_url patterns for given sources.

    Returns (where_clause, params_list).
    """
    clauses: list[str] = []
    params: list[str] = []
    for src in sources:
        cfg = SOURCE_CONFIG[src]
        src_clauses: list[str] = []
        for pat in cfg["patterns"]:
            src_clauses.append("source_url LIKE ?")
            params.append(pat)
        clauses.append("(" + " OR ".join(src_clauses) + ")")
    where = " OR ".join(clauses) if clauses else "1=1"
    return where, params


def _should_update(
    old_content: str | None,
    new_content: str | None,
    old_title: str | None,
    new_title: str | None,
) -> tuple[bool, bool]:
    """Determine whether to update content and/or title.

    Returns (update_content, update_title).
    """
    old_content = old_content or ""
    new_content = new_content or ""

    # Content decision
    update_content = False
    if not new_content.strip():
        # Extractor returned nothing useful
        pass
    elif len(old_content) < 100:
        # Old content was minimal — always upgrade
        update_content = True
    elif len(new_content) >= 2 * len(old_content):
        # New content is at least 2x the old content
        update_content = True

    # Title decision: update if extractor returned a real title that differs
    update_title = False
    if new_title and new_title.strip() and new_title != old_title:
        # Only update if the old title was empty/trivial OR the new one is
        # substantially better (not just a different auto-generated preview)
        if not old_title or len(old_title) < 10:
            update_title = True
        elif new_title != old_title and len(new_title) > len(old_title):
            update_title = True

    return update_content, update_title


def reprocess(
    sources: list[str],
    dry_run: bool = False,
    limit: int | None = None,
) -> None:
    """Main reprocessing logic."""
    import sqlite3
    db = get_db(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # Check if tags column exists (for optional update)
    cols = [row[1] for row in db.execute("PRAGMA table_info(entries)").fetchall()]
    has_media_path = "media_path" in cols

    # Build and run query
    where_clause, params = _build_source_sql(sources)
    query = f"SELECT id, source_url, title, content FROM entries WHERE {where_clause} ORDER BY created_at ASC"
    if limit is not None:
        query += f" LIMIT {limit}"

    entries = db.execute(query, params).fetchall()
    total = len(entries)

    if total == 0:
        src_labels = [SOURCE_CONFIG[s]["label"] for s in sources]
        print(f"No entries found for: {', '.join(src_labels)}")
        db.close()
        return

    print(f"Found {total} {'entry' if total == 1 else 'entries'} to reprocess")
    if dry_run:
        print("  (dry-run mode — no changes will be written)")
    print()

    # Stats
    total_updated = 0
    total_skipped = 0
    total_errors = 0
    errors: list[str] = []
    start_time = time.time()

    for idx, row in enumerate(entries):
        entry_id = row["id"]
        source_url = row["source_url"]
        old_content = row["content"] or ""
        old_title = row["title"] or ""

        # Determine which extractor to use
        source_type = None
        for src_name, cfg in SOURCE_CONFIG.items():
            for pat in cfg["patterns"]:
                like_pat = pat.replace("%", "")
                if like_pat in source_url:
                    source_type = src_name
                    break
            if source_type:
                break

        if not source_type:
            print(f"  {entry_id:40s} | could not determine extractor for {source_url}")
            total_errors += 1
            continue

        extractor = SOURCE_CONFIG[source_type]["extractor"]
        result = None
        try:
            result = extractor(source_url)
        except Exception as e:
            total_errors += 1
            msg = f"[{entry_id}] extractor raised: {e}"
            errors.append(msg)
            print(f"  {entry_id:40s} | ERROR: {e}")
            continue

        if result is None:
            total_errors += 1
            msg = f"[{entry_id}] extractor returned None"
            errors.append(msg)
            print(f"  {entry_id:40s} | ERROR: extractor returned None")
            continue

        new_content = result.get("content") or ""
        new_title = result.get("title") or ""
        status = result.get("status", "unknown")

        # Decide whether to update
        do_update_content, do_update_title = _should_update(
            old_content, new_content, old_title, new_title,
        )

        old_len = len(old_content)
        new_len = len(new_content)

        if not do_update_content and not do_update_title:
            print(
                f"  {entry_id:40s} | old: {old_len:6d} chars → new: {new_len:6d} chars | "
                f"SKIPPED  (status: {status})"
            )
            total_skipped += 1
            continue

        # Perform the update (or preview it in dry-run mode)
        if dry_run:
            actions = []
            if do_update_content:
                actions.append(f"content ({old_len} → {new_len})")
            if do_update_title:
                old_t = old_title[:40] + "..." if len(old_title) > 40 else old_title
                new_t = new_title[:40] + "..." if len(new_title) > 40 else new_title
                actions.append(f"title ({old_t!r} → {new_t!r})")
            print(
                f"  {entry_id:40s} | old: {old_len:6d} chars → new: {new_len:6d} chars | "
                f"WOULD UPDATE ({'; '.join(actions)}, status: {status})"
            )
            total_updated += 1
            continue

        # Actually write to DB
        try:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            if do_update_content and do_update_title:
                db.execute(
                    "UPDATE entries SET content = ?, title = ?, modified_at = ? WHERE id = ?",
                    (new_content, new_title, now, entry_id),
                )
            elif do_update_content:
                db.execute(
                    "UPDATE entries SET content = ?, modified_at = ? WHERE id = ?",
                    (new_content, now, entry_id),
                )
            elif do_update_title:
                db.execute(
                    "UPDATE entries SET title = ?, modified_at = ? WHERE id = ?",
                    (new_title, now, entry_id),
                )

            # Also update media_path if extractor returned one and column exists
            new_media = result.get("media_path")
            if new_media and has_media_path:
                db.execute(
                    "UPDATE entries SET media_path = ? WHERE id = ?",
                    (new_media, entry_id),
                )

            # Rebuild FTS index (triggers handle entries_fts automatically on UPDATE)
            db.commit()

            actions = []
            if do_update_content:
                actions.append(f"content ({old_len} → {new_len})")
            if do_update_title:
                actions.append("title")
            print(
                f"  {entry_id:40s} | old: {old_len:6d} chars → new: {new_len:6d} chars | "
                f"UPDATED  ({'; '.join(actions)}, status: {status})"
            )
            total_updated += 1

        except Exception as e:
            db.rollback()
            total_errors += 1
            msg = f"[{entry_id}] DB update failed: {e}"
            errors.append(msg)
            print(f"  {entry_id:40s} | ERROR: DB update failed: {e}")

        # Periodic commit every 50 entries
        if (idx + 1) % 50 == 0:
            db.commit()

    db.commit()
    db.close()
    elapsed = time.time() - start_time

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print()
    print("=" * 60)
    src_labels = [SOURCE_CONFIG[s]["label"] for s in sources]
    mode = " (DRY RUN)" if dry_run else ""
    print(f"Reprocessing complete{mode}")
    print(f"  Source(s):          {', '.join(src_labels)}")
    print(f"  Total entries:      {total}")
    print(f"  Updated (or WOULD): {total_updated}")
    print(f"  Skipped:            {total_skipped}")
    print(f"  Errors:             {total_errors}")
    print(f"  Time taken:         {elapsed:.2f}s")
    if errors:
        print("\n  Error details (first 10):")
        for e in errors[:10]:
            print(f"    - {e}")
        if len(errors) > 10:
            print(f"    ... and {len(errors) - 10} more")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-run extractors on existing entries to upgrade content quality.",
    )
    parser.add_argument(
        "--source",
        choices=list(SOURCE_CONFIG.keys()),
        action="append",
        dest="sources",
        help="Source type to reprocess (can specify multiple)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Reprocess all supported source types",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be updated without writing any changes",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N entries (useful for testing)",
    )
    args = parser.parse_args()

    if args.all:
        sources = list(SOURCE_CONFIG.keys())
    elif args.sources:
        sources = args.sources
    else:
        parser.print_help()
        print("\nError: specify --source or --all")
        sys.exit(1)

    reprocess(sources=sources, dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
