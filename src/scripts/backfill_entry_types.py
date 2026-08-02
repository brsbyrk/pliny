#!/usr/bin/env python3
"""One-shot: classify all existing entries with entry_type and extraction_status.

Usage:
    .venv/bin/python src/backfill_entry_types.py [--dry-run]

Classification rules for entry_type:
  - x.com / twitter.com + content < 200 chars → 'x_observation'
  - x.com / twitter.com + content >= 200 chars → 'x_thread'
  - youtube.com / youtu.be → 'youtube'
  - reddit.com → 'reddit'
  - github.com → 'github'
  - arxiv.org → 'arxiv'
  - Everything else → 'bookmark'

Classification rules for extraction_status:
  - content < 200 chars → 'pending' (needs retry)
  - content >= 200 chars → 'extracted' (success)
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lib.paths import DB_PATH


def classify_entry_type(source_url: str, content_len: int, extraction_status: str = "") -> str:
    url = (source_url or "").lower()
    if "x.com" in url or "twitter.com" in url:
        if extraction_status and "article" in extraction_status:
            return "x_article"
        return "x_observation" if content_len < 200 else "x_thread"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "reddit.com" in url:
        return "reddit"
    if "github.com" in url:
        return "github"
    if "arxiv.org" in url:
        return "arxiv"
    return "bookmark"


def classify_extraction_status(content_len: int) -> str:
    return "extracted" if content_len >= 200 else "pending"


def main():
    dry_run = "--dry-run" in sys.argv

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, source_url, LENGTH(COALESCE(content, '')) as clen, "
        "entry_type, extraction_status, retry_count FROM entries"
    ).fetchall()

    updates_entry_type = []
    updates_extraction = []
    updates_retry = []

    for r in rows:
        etype = classify_entry_type(r["source_url"], r["clen"], r["extraction_status"])
        estatus = classify_extraction_status(r["clen"])

        if r["entry_type"] != etype:
            updates_entry_type.append((etype, r["id"]))
        if r["extraction_status"] != estatus:
            updates_extraction.append((estatus, r["id"]))
        if r["retry_count"] is None:
            updates_retry.append(r["id"])

    print(f"Total entries: {len(rows)}")
    print(f"Entry type updates: {len(updates_entry_type)}")
    print(f"Extraction status updates: {len(updates_extraction)}")
    print(f"Retry count NULL→0: {len(updates_retry)}")

    # Summary by type
    type_counts = {}
    for r in rows:
        t = r["entry_type"] or "unset"
        type_counts[t] = type_counts.get(t, 0) + 1
    print("\nCurrent entry_type distribution:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t:20s} {c}")

    # Show what will change
    if updates_entry_type and dry_run:
        print("\n[Dry-run] Entry type changes (showing first 10):")
        conn2 = sqlite3.connect(str(DB_PATH))
        for etype, eid in updates_entry_type[:10]:
            row = conn2.execute(
                "SELECT title, source_url FROM entries WHERE id = ?", (eid,)
            ).fetchone()
            title = (row[0] or "(no title)")[:50] if row else "?"
            etype = row[2][:15] if row else "?"
            print(f"  {eid[:40]:40s} → {etype:15s} ({title})")

    if dry_run:
        conn.close()
        return

    # Apply updates
    conn.execute("BEGIN TRANSACTION")
    try:
        if updates_entry_type:
            conn.executemany(
                "UPDATE entries SET entry_type = ? WHERE id = ?",
                updates_entry_type,
            )
        if updates_extraction:
            conn.executemany(
                "UPDATE entries SET extraction_status = ? WHERE id = ?",
                updates_extraction,
            )
        for eid in updates_retry:
            conn.execute(
                "UPDATE entries SET retry_count = 0 WHERE id = ?", (eid,)
            )
        conn.commit()
        print(f"\n✅ Applied: {len(updates_entry_type)} type, {len(updates_extraction)} status, {len(updates_retry)} retry")
    except Exception as e:
        conn.rollback()
        print(f"❌ Failed: {e}")
        sys.exit(1)
    finally:
        conn.close()

    # Final distribution
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT entry_type, COUNT(*) FROM entries GROUP BY entry_type ORDER BY COUNT(*) DESC"
    ).fetchall()
    print("\nFinal entry_type distribution:")
    for t, c in rows:
        print(f"  {t:20s} {c}")

    status_rows = conn.execute(
        "SELECT extraction_status, COUNT(*) FROM entries GROUP BY extraction_status ORDER BY COUNT(*) DESC"
    ).fetchall()
    print("\nExtraction status distribution:")
    for s, c in status_rows:
        print(f"  {s:20s} {c}")
    conn.close()


if __name__ == "__main__":
    main()
