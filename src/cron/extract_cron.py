#!/usr/bin/env python3
"""extract_cron.py — Unified daily cron for thin entry extraction recovery.

Handles ALL pending entries across sources.

Strategy:
  - Skip x_observation entries (inherently short, not worth retrying)
  - Process oldest pending entries first
  - Max 50/day, with rate-limit delays between extractions
  - On success: mark extraction_status = 'extracted'
  - On failure: increment retry_count; if >= 3, mark dead
  - Reports summary to stdout for cron delivery

Usage:
    .venv/bin/python src/extract_cron.py [--max N] [--dry-run]
"""

import sqlite3
import sys
import time
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lib.paths import DB_PATH

# ── Config ────────────────────────────────────────────────────
DEFAULT_MAX = 50           # max entries per run
DELAY_BETWEEN = 3.0        # seconds between extractions
MAX_RUN_SECONDS = 480      # safety timeout (8 min)
MAX_RETRIES = 3            # max retries before marking dead

# ── Skip these entry types (inherently short, not worth retrying) ──
# x_article entries ARE included for re-extraction
SKIP_TYPES = {"x_observation", "arxiv"}


def get_pending_entries(db: sqlite3.Connection, limit: int) -> list[dict]:
    """Get oldest pending entries that can be retried."""
    rows = db.execute(
        """SELECT id, source_url, title, entry_type, retry_count,
                  LENGTH(COALESCE(content, '')) as clen
           FROM entries
           WHERE extraction_status = 'pending'
             AND entry_type NOT IN ('x_observation', 'arxiv')
             AND retry_count < ?
           ORDER BY created_at ASC
           LIMIT ?""",
        (MAX_RETRIES, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_dead_candidates(db: sqlite3.Connection, limit: int) -> list[dict]:
    """Get entries that have exhausted retries and should be marked dead."""
    rows = db.execute(
        """SELECT id, source_url, title, entry_type, retry_count,
                  LENGTH(COALESCE(content, '')) as clen
           FROM entries
           WHERE extraction_status = 'pending'
             AND entry_type NOT IN ('x_observation', 'arxiv')
             AND retry_count >= ?
           ORDER BY created_at ASC
           LIMIT ?""",
        (MAX_RETRIES, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def count_summary(db: sqlite3.Connection) -> dict:
    """Return a summary of current extraction state."""
    total = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    pending = db.execute(
        "SELECT COUNT(*) FROM entries WHERE extraction_status = 'pending'"
    ).fetchone()[0]
    extracted = db.execute(
        "SELECT COUNT(*) FROM entries WHERE extraction_status = 'extracted'"
    ).fetchone()[0]
    thin = db.execute(
        "SELECT COUNT(*) FROM entries WHERE extraction_status = 'thin'"
    ).fetchone()[0]
    dead = db.execute(
        "SELECT COUNT(*) FROM entries WHERE extraction_status = 'dead'"
    ).fetchone()[0]

    # By source (non-thin pending only)
    by_source = db.execute(
        """SELECT entry_type, COUNT(*) as cnt
           FROM entries
           WHERE extraction_status = 'pending'
           GROUP BY entry_type
           ORDER BY cnt DESC"""
    ).fetchall()

    return {
        "total": total,
        "pending": pending,
        "extracted": extracted,
        "thin": thin,
        "dead": dead,
        "by_source": [dict(r) for r in by_source],
    }


def re_extract(url: str) -> dict | None:
    """Re-run extraction on a URL. Returns {title, content} or None on failure."""
    from ingest.url_ingest import classify_url, EXTRACTORS

    kind = classify_url(url)
    try:
        result = EXTRACTORS[kind](url)
    except Exception as e:
        return {"error": str(e)}

    if not result:
        return {"error": "extractor returned None"}

    status = result.get("status", "")
    title = result.get("title") or ""
    content = result.get("content")

    dead_statuses = {
        "reddit_deleted", "reddit_resolve_failed",
        "github_not_found", "github_empty", "github_invalid_url",
        "youtube_unavailable", "youtube_no_id",
        "web_dead", "web_blocked", "web_connection_error",
        "x_api_failed",
    }

    if status in dead_statuses or "http_404" in status:
        return {"error": f"dead source: {status}"}

    if not content:
        return {"error": f"no content ({status})"}

    if status.startswith("error"):
        return {"error": status}

    return {"title": title, "content": content}


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Retry thin entry extractions")
    parser.add_argument("--max", type=int, default=DEFAULT_MAX, help=f"Max entries to process (default: {DEFAULT_MAX})")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be processed without doing anything")
    parser.add_argument("--mark-dead", action="store_true", help="Mark over-retried entries as dead without retrying")
    args = parser.parse_args()

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    # ── Pre-run summary ──
    summary = count_summary(db)
    print("=== Extraction Cron ===")
    print(f"Total entries:      {summary['total']}")
    print(f"Extracted:          {summary['extracted']}")
    print(f"Pending:            {summary['pending']}")
    print(f"Thin (inherent):    {summary['thin']}")
    print(f"Dead:               {summary['dead']}")
    if summary["by_source"]:
        print("\nPending by source:")
        for s in summary["by_source"]:
            print(f"  {s['entry_type']:20s} {s['cnt']}")
    print()

    if args.dry_run:
        pending = get_pending_entries(db, args.max)
        print(f"\n[Dry-run] Would process up to {len(pending)} entries:")
        for e in pending:
            print(f"  {e['id'][:40]:40s} {e['entry_type']:15s} retry={e['retry_count']}")
        db.close()
        return

    # ── Mark over-retried entries as dead ──
    if args.mark_dead:
        dead_candidates = get_dead_candidates(db, 200)
        if not dead_candidates:
            print("No entries to mark dead.")
        else:
            ids = [e["id"] for e in dead_candidates]
            db.executemany(
                "UPDATE entries SET extraction_status = 'dead' WHERE id = ?",
                [(eid,) for eid in ids],
            )
            db.commit()
            print(f"✅ Marked {len(ids)} entries as dead (exhausted retries)")
        db.close()
        return

    # ── Process pending entries ──
    pending = get_pending_entries(db, args.max)
    if not pending:
        print("✅ No pending entries to process.")
        db.close()
        return

    start = time.time()
    ok = 0
    fail = 0
    dead_count = 0
    rate_limited = False

    for i, entry in enumerate(pending, 1):
        elapsed = time.time() - start
        if elapsed > MAX_RUN_SECONDS:
            print(f"\n⏱ Time limit ({MAX_RUN_SECONDS}s) reached after {i - 1} entries.")
            break

        eid = entry["id"]
        url = entry["source_url"]
        etype = entry["entry_type"]
        retries = entry["retry_count"]
        short_id = eid[:40] if len(eid) > 40 else eid

        print(f"  [{i}/{len(pending)}] {short_id:42s} ({etype}, retry {retries})", end=" ")
        sys.stdout.flush()

        try:
            result = re_extract(url)

            if result and "error" not in result:
                # Success
                new_content = result.get("content", "")
                new_title = result.get("title", entry["title"])
                clen = len(new_content)

                db.execute(
                    """UPDATE entries
                       SET title = ?, content = ?, extraction_status = 'extracted',
                           retry_count = ?, modified_at = datetime('now')
                       WHERE id = ?""",
                    (new_title, new_content, retries, eid),
                )
                db.commit()
                print(f"✅ [{clen}c]")
                ok += 1
            else:
                error = result.get("error", "unknown error") if result else "extractor returned None"
                new_retries = retries + 1

                if new_retries >= MAX_RETRIES:
                    db.execute(
                        """UPDATE entries
                           SET extraction_status = 'dead', retry_count = ?,
                               modified_at = datetime('now')
                           WHERE id = ?""",
                        (new_retries, eid),
                    )
                    dead_count += 1
                    print(f"💀 retries exhausted ({error[:50]})")
                else:
                    db.execute(
                        """UPDATE entries
                           SET retry_count = ?, modified_at = datetime('now')
                           WHERE id = ?""",
                        (new_retries, eid),
                    )
                    print(f"❌ {error[:60]}")
                db.commit()
                fail += 1

        except Exception as e:
            estr = str(e)
            if "403" in estr or "429" in estr or "rate" in estr.lower():
                print("⛔ RATE LIMITED")
                rate_limited = True
                break
            print(f"⚠️ {estr[:60]}")
            fail += 1

        if i < len(pending) and not rate_limited:
            time.sleep(DELAY_BETWEEN)

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"Done: {ok} extracted, {fail} failed, {dead_count} marked dead in {elapsed:.0f}s")
    if rate_limited:
        print("⚠️ Stopped early due to rate limiting. Will resume next run.")

    # Post-run summary
    summary = count_summary(db)
    print(f"Remaining pending:  {summary['pending']}")
    print(f"Total extracted:    {summary['extracted']}")
    print(f"Total dead:         {summary['dead']}")

    db.close()


if __name__ == "__main__":
    main()
