"""Test RSS feed monitor — URL normalization, dedup, feed parsing.

No real network calls. Tests feed parsing with mock feedparser data,
URL normalization, and dedup logic against the database.
"""

import json
import sqlite3
from unittest.mock import patch, MagicMock
from urllib.parse import urlparse

import pytest

# Make src/ importable
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ingest.rss import (
    _normalize_url,
    _is_already_ingested,
    _extract_entry_url,
    _entry_published,
    _entry_title,
    FeedMonitor,
)


# ── URL Normalization ────────────────────────────────────────────


class TestNormalizeUrl:
    def test_strips_tracking_params(self):
        url = "https://example.com/article?utm_source=twitter&utm_medium=social"
        result = _normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result

    def test_preserves_valid_params(self):
        url = "https://example.com/article?page=2&sort=date"
        result = _normalize_url(url)
        assert "page=2" in result
        assert "sort=date" in result

    def test_handles_no_query(self):
        url = "https://example.com/article"
        result = _normalize_url(url)
        assert result == url

    def test_strips_fbclid(self):
        url = "https://example.com/post?fbclid=abc123&id=5"
        result = _normalize_url(url)
        assert "fbclid" not in result
        assert "id=5" in result

    def test_trailing_slash_normalized(self):
        url = "https://example.com/article/"
        result = _normalize_url(url)
        assert not result.endswith("/")


# ── Dedup ────────────────────────────────────────────────────────


class TestDedup:
    def test_url_not_already_ingested(self, tmp_db):
        assert _is_already_ingested(tmp_db, "https://example.com/new") is False

    def test_url_already_ingested(self, tmp_db):
        tmp_db.execute(
            "INSERT INTO entries (id, source_url, title, content, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            ("test-1", "https://example.com/existing", "Test", "Content"),
        )
        tmp_db.commit()
        assert _is_already_ingested(tmp_db, "https://example.com/existing") is True

    def test_url_matches_normalized(self, tmp_db):
        tmp_db.execute(
            "INSERT INTO entries (id, source_url, title, content, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            ("test-2", "https://example.com/article", "Test", "Content"),
        )
        tmp_db.commit()
        assert _is_already_ingested(tmp_db, "https://example.com/article/") is True


# ── Entry URL extraction ─────────────────────────────────────────


class TestExtractEntryUrl:
    def test_direct_link(self):
        entry = {"link": "https://example.com/post"}
        assert _extract_entry_url(entry) == "https://example.com/post"

    def test_id_is_url(self):
        entry = {"id": "https://example.com/feed/item/123", "link": ""}
        assert _extract_entry_url(entry) == "https://example.com/feed/item/123"

    def test_links_list_alternate(self):
        entry = {
            "links": [
                {"rel": "self", "href": "https://example.com/feed"},
                {"rel": "alternate", "href": "https://example.com/post"},
            ]
        }
        assert _extract_entry_url(entry) == "https://example.com/post"

    def test_no_url(self):
        entry = {"title": "Just a title"}
        assert _extract_entry_url(entry) is None


# ── Published date extraction ────────────────────────────────────


class TestEntryPublished:
    def test_published_parsed(self):
        entry = {"published_parsed": (2026, 8, 1, 12, 0, 0, 0, 214, 0)}
        result = _entry_published(entry)
        assert result
        assert result.startswith("2026-08-01")

    def test_updated_parsed_fallback(self):
        entry = {"updated_parsed": (2026, 7, 31, 15, 30, 0, 0, 212, 0)}
        result = _entry_published(entry)
        assert result
        assert result.startswith("2026-07-31")

    def test_none_when_missing(self):
        assert _entry_published({}) is None


# ── Title extraction ─────────────────────────────────────────────


class TestEntryTitle:
    def test_direct_title(self):
        entry = {"title": "Hello World"}
        assert _entry_title(entry) == "Hello World"

    def test_strips_html(self):
        entry = {"title": "Breaking: <b>Important</b> News"}
        assert _entry_title(entry) == "Breaking: Important News"

    def test_fallback_to_url_slug(self):
        entry = {"title": "", "link": "https://blog.com/posts/hello-world-2026"}
        assert "hello" in _entry_title(entry).lower()

    def test_fallback_to_untitled(self):
        entry = {"title": ""}
        assert _entry_title(entry) == "Untitled"


# ── FeedMonitor ──────────────────────────────────────────────────


class TestFeedMonitor:
    def test_add_feed(self):
        monitor = FeedMonitor(":memory:")
        monitor.add_feed("https://example.com/feed.xml", "Example Blog")
        assert len(monitor._feeds) == 1
        assert monitor.stats["feeds"] == 1

    def test_add_feeds_from_file(self, tmp_path):
        feeds_file = tmp_path / "feeds.txt"
        feeds_file.write_text(
            "# My feeds\n"
            "https://blog1.com/feed.xml # Blog 1\n"
            "https://blog2.com/rss\n"
        )
        monitor = FeedMonitor(":memory:")
        count = monitor.add_feeds_from_file(str(feeds_file))
        assert count == 2
        assert len(monitor._feeds) == 2

    @patch("ingest.rss.feedparser.parse")
    def test_poll_feed_dry_run(self, mock_parse):
        mock_parse.return_value = MagicMock(
            bozo=False,
            entries=[
                {
                    "title": "Test Post",
                    "link": "https://example.com/test-post",
                    "published_parsed": (2026, 8, 1, 10, 0, 0, 0, 214, 0),
                }
            ],
            etag=None,
            modified=None,
        )

        monitor = FeedMonitor(":memory:")
        monitor.add_feed("https://example.com/feed.xml")

        with patch("ingest.rss.get_db") as mock_db:
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn
            mock_conn.execute.return_value.fetchone.return_value = None

            result = monitor.poll_feed("https://example.com/feed.xml", dry_run=True)
            assert result["entries_total"] == 1
            assert result["entries_new"] == 1
            assert result["entries_ingested"] == 0  # dry run

    @patch("ingest.rss.feedparser.parse")
    def test_poll_feed_skips_ingested(self, mock_parse):
        mock_parse.return_value = MagicMock(
            bozo=False,
            entries=[
                {
                    "title": "Old Post",
                    "link": "https://example.com/old-post",
                }
            ],
        )

        monitor = FeedMonitor(":memory:")
        monitor.add_feed("https://example.com/feed.xml")

        with patch("ingest.rss.get_db") as mock_db:
            mock_conn = MagicMock()
            mock_db.return_value = mock_conn
            # Simulate already ingested
            mock_conn.execute.return_value.fetchone.return_value = (1,)

            result = monitor.poll_feed("https://example.com/feed.xml")
            assert result["entries_skipped"] == 1
            assert result["entries_new"] == 0

    @patch("ingest.rss.feedparser.parse")
    def test_poll_feed_handles_parse_error(self, mock_parse):
        mock_parse.return_value = MagicMock(
            bozo=True,
            bozo_exception=Exception("Malformed XML"),
            entries=[],
        )

        monitor = FeedMonitor(":memory:")
        monitor.add_feed("https://example.com/broken.xml")

        result = monitor.poll_feed("https://example.com/broken.xml")
        assert result["errors"] == 1
