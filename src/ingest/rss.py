"""RSS/Atom feed monitor — poll feeds and auto-ingest new entries into Pliny.

Usage:
    python3 src/ingest/rss.py feeds.txt              # one URL per line
    python3 src/ingest/rss.py --url https://example.com/feed.xml
    python3 src/ingest/rss.py --url https://example.com/feed.xml --dry-run

Architecture:
    FeedMonitor class handles polling, dedup, and ingestion. Each feed is
    polled on a configurable interval (default: 1h). New entries are checked
    against the existing DB to avoid duplicates, then passed through Pliny's
    standard ingest pipeline (classify → extract → format → store).

Dependencies:
    feedparser>=6.0 — RSS/Atom parsing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser

# Make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.paths import DB_PATH
from lib.schema import get_db
from ingest.url_ingest import ingest_url, classify_url

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────

DEFAULT_POLL_INTERVAL = 3600   # 1 hour
MAX_ENTRIES_PER_FEED = 50      # cap entries ingested per poll cycle
REQUEST_TIMEOUT = 30           # HTTP timeout for feed fetch
USER_AGENT = "Pliny/0.2 RSS Monitor (+https://github.com/brsbyrk/pliny)"

# ── URL normalization ────────────────────────────────────────────


def _normalize_url(url: str) -> str:
    """Strip tracking params and normalize for dedup comparison."""
    # Common tracking params to strip
    tracking_params = {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "ref", "ref_src", "ref_url", "source", "fbclid", "gclid",
        "mc_cid", "mc_eid", "mc_tc", "pk_campaign", "pk_kwd",
        "_ga", "_gl", "_hsenc", "_hsmi",
    }
    parsed = urlparse(url)
    query_parts = [
        (k, v) for k, v in (p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
        if k not in tracking_params
    ]
    cleaned = parsed._replace(query="&".join(f"{k}={v}" for k, v in query_parts))
    return cleaned.geturl().rstrip("/")


def _is_already_ingested(db: sqlite3.Connection, url: str) -> bool:
    """Check if a URL (normalized) already exists in Pliny."""
    normalized = _normalize_url(url)
    row = db.execute(
        "SELECT 1 FROM entries WHERE source_url = ? OR source_url = ? LIMIT 1",
        (url, normalized),
    ).fetchone()
    return row is not None


# ── Entry extraction from feed ───────────────────────────────────


def _extract_entry_url(entry: dict[str, Any]) -> str | None:
    """Extract the most useful URL from a feed entry.

    Tries: link → id (if it's a URL) → first link in links.
    """
    # feedparser normalizes 'link' to the first link
    if entry.get("link"):
        return entry["link"]

    # Some feeds put the URL in 'id'
    raw_id = entry.get("id", "")
    if raw_id.startswith("http"):
        return raw_id

    # Check links list
    links = entry.get("links", [])
    for link in links:
        if link.get("rel") in ("alternate", None) and link.get("href", "").startswith("http"):
            return link["href"]

    return None


def _entry_published(entry: dict[str, Any]) -> str | None:
    """Extract published timestamp, return ISO format string or None."""
    for key in ("published_parsed", "updated_parsed"):
        tp = entry.get(key)
        if tp:
            try:
                dt = datetime(*tp[:6], tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except (TypeError, ValueError):
                pass
    return None


def _entry_title(entry: dict[str, Any]) -> str:
    """Extract title, fallback to URL or 'Untitled'."""
    title = entry.get("title", "").strip()
    if title:
        # feedparser sometimes returns HTML in titles
        title = re.sub(r"<[^>]+>", "", title)
        return title
    url = _extract_entry_url(entry)
    if url:
        # Use the slug from the URL path
        path = urlparse(url).path.strip("/")
        if path:
            parts = path.split("/")
            if parts:
                return parts[-1].replace("-", " ").replace("_", " ")[:100]
    return "Untitled"


# ── Feed monitor ──────────────────────────────────────────────────


class FeedMonitor:
    """Polls RSS/Atom feeds and ingests new entries into Pliny.

    Parameters
    ----------
    db_path : str | Path
        Path to Pliny's SQLite database.
    poll_interval : int
        Seconds between polls (default: 3600 = 1 hour).
    max_entries_per_feed : int
        Max new entries to ingest per feed per poll cycle.
    """

    def __init__(
        self,
        db_path: str | Path = DB_PATH,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        max_entries_per_feed: int = MAX_ENTRIES_PER_FEED,
    ) -> None:
        self.db_path = str(db_path)
        self.poll_interval = poll_interval
        self.max_entries_per_feed = max_entries_per_feed

        self._feeds: dict[str, dict[str, Any]] = {}
        self._stats: dict[str, Any] = {
            "feeds": 0,
            "entries_scanned": 0,
            "entries_new": 0,
            "entries_ingested": 0,
            "entries_skipped": 0,
            "errors": 0,
            "last_poll": None,
        }

    # ── Public API ──────────────────────────────────────────────

    def add_feed(self, url: str, name: str | None = None) -> None:
        """Register a feed URL for monitoring."""
        self._feeds[url] = {
            "name": name or url,
            "url": url,
            "last_poll": None,
            "etag": None,
            "modified": None,
            "error_count": 0,
        }
        self._stats["feeds"] = len(self._feeds)

    def add_feeds_from_file(self, path: str | Path) -> int:
        """Load feed URLs from a file (one URL per line, # comments)."""
        added = 0
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Allow "URL # Name" format
            if " # " in line or "\t# " in line:
                url, name = re.split(r"\s+#\s+", line, maxsplit=1)
                self.add_feed(url.strip(), name.strip())
            else:
                self.add_feed(line)
            added += 1
        return added

    def poll_feed(self, feed_url: str, dry_run: bool = False) -> dict[str, Any]:
        """Poll a single feed and ingest new entries.

        Returns a result dict with counts.
        """
        feed_info = self._feeds.get(feed_url)
        if not feed_info:
            return {"error": f"feed not registered: {feed_url}"}

        result = {
            "feed": feed_info["name"],
            "entries_total": 0,
            "entries_new": 0,
            "entries_ingested": 0,
            "entries_skipped": 0,
            "errors": 0,
        }

        # Fetch feed
        try:
            parsed = feedparser.parse(
                feed_url,
                agent=USER_AGENT,
                etag=feed_info.get("etag"),
                modified=feed_info.get("modified"),
            )
        except Exception as e:
            logger.error("Failed to fetch feed %s: %s", feed_info["name"], e)
            feed_info["error_count"] += 1
            self._stats["errors"] += 1
            result["errors"] += 1
            return result

        # Check for feed-level errors
        if parsed.bozo and not parsed.entries:
            logger.warning("Feed %s parse error: %s", feed_info["name"], parsed.bozo_exception)
            feed_info["error_count"] += 1
            self._stats["errors"] += 1
            result["errors"] += 1
            return result

        # Update cache keys for conditional GET
        if hasattr(parsed, "etag") and parsed.etag:
            feed_info["etag"] = parsed.etag
        if hasattr(parsed, "modified") and parsed.modified:
            feed_info["modified"] = parsed.modified

        feed_info["last_poll"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._stats["last_poll"] = feed_info["last_poll"]

        entries = parsed.entries
        result["entries_total"] = len(entries)

        if not entries:
            return result

        # Open DB connection for dedup checks
        db = get_db(self.db_path)

        # Filter: dedup, sort by date, cap
        new_entries = []
        for entry in entries[: self.max_entries_per_feed * 2]:  # extra buffer for dedup
            url = _extract_entry_url(entry)
            if not url:
                continue

            if _is_already_ingested(db, url):
                self._stats["entries_skipped"] += 1
                result["entries_skipped"] += 1
                continue

            new_entries.append(entry)
            if len(new_entries) >= self.max_entries_per_feed:
                break

        result["entries_new"] = len(new_entries)
        self._stats["entries_scanned"] += len(entries)
        self._stats["entries_new"] += len(new_entries)

        if not new_entries:
            db.close()
            return result

        # Ingest each new entry through Pliny's standard pipeline
        for entry in new_entries:
            url = _extract_entry_url(entry)
            if not url:
                continue

            title = _entry_title(entry)
            published = _entry_published(entry)

            if dry_run:
                logger.info("  [DRY RUN] Would ingest: %s — %s", title[:60], url[:80])
                continue

            try:
                entry_id = ingest_url(url, db=db)
                if entry_id:
                    self._stats["entries_ingested"] += 1
                    result["entries_ingested"] += 1
                    # Override created_at with the feed's published date if available
                    if published:
                        db.execute(
                            "UPDATE entries SET created_at = ? WHERE id = ?",
                            (published, entry_id),
                        )
                    logger.info("  ✓ %s (%s)", title[:60], entry_id)
                else:
                    logger.warning("  ✗ Failed to extract: %s", url[:80])
                    self._stats["errors"] += 1
                    result["errors"] += 1
            except Exception as e:
                logger.error("  ✗ Error ingesting %s: %s", url[:80], e)
                self._stats["errors"] += 1
                result["errors"] += 1

        db.commit()
        db.close()

        return result

    def poll_all(self, dry_run: bool = False) -> dict[str, Any]:
        """Poll all registered feeds and return aggregate stats."""
        feed_results = {}
        for feed_url in list(self._feeds):
            result = self.poll_feed(feed_url, dry_run=dry_run)
            feed_results[feed_url] = result

        return {
            "feeds": len(self._feeds),
            "results": feed_results,
            "stats": dict(self._stats),
        }

    def run_loop(self, dry_run: bool = False) -> None:
        """Run continuous polling loop (Ctrl+C to stop)."""
        logger.info("Starting RSS monitor — %d feeds, %ds interval",
                     len(self._feeds), self.poll_interval)
        logger.info("Press Ctrl+C to stop.\n")

        try:
            while True:
                result = self.poll_all(dry_run=dry_run)
                total_new = sum(r["entries_new"] for r in result["results"].values())
                total_ingested = sum(r["entries_ingested"] for r in result["results"].values())
                logger.info(
                    "Poll complete — %d new across %d feeds, %d ingested. Sleeping %ds...\n",
                    total_new, len(self._feeds), total_ingested, self.poll_interval,
                )
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logger.info("\nRSS monitor stopped. Final stats: %s", json.dumps(self._stats, indent=2))

    @property
    def stats(self) -> dict[str, Any]:
        return dict(self._stats)


# ── CLI ──────────────────────────────────────────────────────────


def _load_feeds_from_file(path: str) -> list[str]:
    """Load feed URLs from a file."""
    feeds = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            feeds.append(line)
    return feeds


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pliny RSS/Atom feed monitor — poll feeds and auto-ingest entries"
    )
    parser.add_argument(
        "feeds_file", nargs="?", default=None,
        help="File with one feed URL per line (# comments) or a single URL with --url",
    )
    parser.add_argument(
        "--url", action="append", dest="urls", default=[],
        help="Add a single feed URL (repeatable)",
    )
    parser.add_argument(
        "--interval", type=int, default=DEFAULT_POLL_INTERVAL,
        help=f"Poll interval in seconds (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--max-entries", type=int, default=MAX_ENTRIES_PER_FEED,
        help=f"Max entries per feed per poll (default: {MAX_ENTRIES_PER_FEED})",
    )
    parser.add_argument(
        "--once", action="store_true",
        help="Poll once and exit (no loop)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be ingested without doing it",
    )
    parser.add_argument(
        "--db", default=str(DB_PATH), help=f"Database path (default: {DB_PATH})",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    monitor = FeedMonitor(
        db_path=args.db,
        poll_interval=args.interval,
        max_entries_per_feed=args.max_entries,
    )

    # Load feeds
    if args.feeds_file:
        count = monitor.add_feeds_from_file(args.feeds_file)
        logger.info("Loaded %d feeds from %s", count, args.feeds_file)

    for url in args.urls:
        monitor.add_feed(url)

    if len(monitor._feeds) == 0:
        parser.error("No feeds specified. Use feeds_file or --url.")

    logger.info("Monitoring %d feeds", len(monitor._feeds))

    if args.once:
        result = monitor.poll_all(dry_run=args.dry_run)
        if args.dry_run:
            logger.info("Dry run complete — %d new entries would be ingested",
                         result["stats"]["entries_new"])
        else:
            logger.info("One-shot complete — %d ingested",
                         result["stats"]["entries_ingested"])
    else:
        monitor.run_loop(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
