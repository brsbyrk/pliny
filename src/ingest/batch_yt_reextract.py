"""
batch_yt_reextract.py — Re-extract thin YouTube entries with Whisper fallback.

Usage: python3 src/ingest/batch_yt_reextract.py [--dry-run]
"""

import sqlite3
import sys
import time
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SRC.parent))  # project root

from lib.paths import DB_PATH
from lib.embed import embed_json
from ingest.url_ingest import extract_youtube, _extract_video_id

DRY_RUN = "--dry-run" in sys.argv


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Find thin YouTube entries (likely no transcript)
    rows = conn.execute("""
        SELECT id, title, source_url, LENGTH(content) as clen
        FROM entries
        WHERE (source_url LIKE '%youtube.com%' OR source_url LIKE '%youtu.be%')
          AND LENGTH(content) < 500
        ORDER BY created_at DESC
    """).fetchall()

    print(f"Found {len(rows)} thin YouTube entries to re-extract\n")

    ok = 0
    failed = 0
    skipped = 0
    whisper = 0

    for i, row in enumerate(rows, 1):
        eid = row["id"]
        url = row["source_url"]
        vid = _extract_video_id(url)
        old_clen = row["clen"]
        old_title = row["title"] or ""

        print(f"  [{i}/{len(rows)}] {eid[:36]} | {old_clen:>4}B | {str(old_title)[:50]}")

        if not vid:
            print("    → skipped (no video ID)")
            skipped += 1
            continue

        if DRY_RUN:
            print(f"    → would extract (video_id={vid})")
            continue

        try:
            result = extract_youtube(url)
            new_title = result.get("title") or old_title
            new_content = result.get("content")
            status = result.get("status", "")

            if not new_content or len(new_content.strip()) < 50:
                print(f"    → {status} — no content extracted")
                skipped += 1
                continue

            new_clen = len(new_content)
            media_path = result.get("media_path")

            # Update DB
            conn.execute(
                "UPDATE entries SET title = ?, content = ?, media_path = ? WHERE id = ?",
                (new_title, new_content, media_path, eid),
            )

            # Recompute vec0 embedding
            vec = embed_json(new_title + "\n\n" + new_content)
            rowid = conn.execute("SELECT rowid FROM entries WHERE id = ?", (eid,)).fetchone()[0]
            conn.execute("DELETE FROM entries_v0 WHERE rowid = ?", (rowid,))
            conn.execute("INSERT INTO entries_v0 (rowid, embedding) VALUES (?, ?)", (rowid, vec))

            conn.commit()

            change = new_clen - old_clen
            arrow = "🚀" if "whisper" in status else "📝"
            print(f"    → {arrow} {status} — {old_clen}B → {new_clen}B (+{change}B)")
            if "whisper" in status:
                whisper += 1
            ok += 1

        except Exception as e:
            print(f"    → ❌ error: {e}")
            failed += 1

        # Delay to be gentle
        time.sleep(3)

    print(f"\n{'='*50}")
    print(f"Done: {ok} extracted ({whisper} via Whisper), {skipped} skipped, {failed} failed")
    conn.close()


if __name__ == "__main__":
    main()
