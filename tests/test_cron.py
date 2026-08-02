"""Test cron job helpers — extract_cron.py, digest.py.

Tests database helpers, count_summary, get_pending_entries, etc.
"""

import json
import sqlite3
import pytest


# ---------------------------------------------------------------------------
# extract_cron tests
# ---------------------------------------------------------------------------

class TestExtractCron:
    def test_get_pending_entries_empty(self, tmp_db):
        from src.cron.extract_cron import get_pending_entries
        tmp_db.row_factory = sqlite3.Row
        entries = get_pending_entries(tmp_db, 10)
        assert entries == []

    def test_get_pending_entries_with_data(self, tmp_db):
        from src.cron.extract_cron import get_pending_entries

        now = "2024-06-01T00:00:00Z"
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type,
               extraction_status, retry_count, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)""",
            ("e1", "https://example.com/1", "Title 1", "content1",
             "web", now, now),
        )
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type,
               extraction_status, retry_count, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, 'pending', 1, ?, ?)""",
            ("e2", "https://example.com/2", "Title 2", "content2",
             "web", now, now),
        )
        # Already extracted
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type,
               extraction_status, retry_count, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, 'extracted', 0, ?, ?)""",
            ("e3", "https://example.com/3", "Title 3", "content3",
             "web", now, now),
        )
        # x_observation — should be skipped
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type,
               extraction_status, retry_count, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)""",
            ("e4", "https://x.com/user/status/123", "X obs", "obs",
             "x_observation", now, now),
        )
        tmp_db.commit()
        tmp_db.row_factory = sqlite3.Row

        entries = get_pending_entries(tmp_db, 10)
        assert len(entries) == 2
        ids = [e["id"] for e in entries]
        assert "e1" in ids
        assert "e2" in ids
        assert "e3" not in ids
        assert "e4" not in ids

    def test_get_pending_entries_respects_retry_limit(self, tmp_db):
        from src.cron.extract_cron import get_pending_entries

        now = "2024-06-01T00:00:00Z"
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type,
               extraction_status, retry_count, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, 'pending', 5, ?, ?)""",
            ("e-dead", "https://example.com/dead", "Dead", "c",
             "web", now, now),
        )
        tmp_db.commit()
        tmp_db.row_factory = sqlite3.Row
        entries = get_pending_entries(tmp_db, 10)
        ids = [e["id"] for e in entries]
        assert "e-dead" not in ids

    def test_get_dead_candidates(self, tmp_db):
        from src.cron.extract_cron import get_dead_candidates

        now = "2024-06-01T00:00:00Z"
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type,
               extraction_status, retry_count, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, 'pending', 3, ?, ?)""",
            ("e-dead", "https://example.com/dead", "Dead", "c",
             "web", now, now),
        )
        tmp_db.commit()
        tmp_db.row_factory = sqlite3.Row
        candidates = get_dead_candidates(tmp_db, 10)
        assert len(candidates) == 1
        assert candidates[0]["id"] == "e-dead"

    def test_count_summary(self, tmp_db):
        from src.cron.extract_cron import count_summary

        now = "2024-06-01T00:00:00Z"
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type,
               extraction_status, retry_count, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, 'extracted', 0, ?, ?)""",
            ("e1", "https://example.com/1", "T1", "content1", "web", now, now),
        )
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type,
               extraction_status, retry_count, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, 'pending', 1, ?, ?)""",
            ("e2", "https://example.com/2", "T2", "c2", "web", now, now),
        )
        tmp_db.execute(
            """INSERT INTO entries (id, source_url, title, content, entry_type,
               extraction_status, retry_count, created_at, modified_at)
               VALUES (?, ?, ?, ?, ?, 'thin', 0, ?, ?)""",
            ("e3", "https://x.com/t/status/1", "X", "obs", "x_observation", now, now),
        )
        tmp_db.commit()
        tmp_db.row_factory = sqlite3.Row

        summary = count_summary(tmp_db)
        assert summary["total"] == 3
        assert summary["extracted"] == 1
        assert summary["pending"] == 1
        assert summary["thin"] == 1
        assert summary["dead"] == 0
        assert len(summary["by_source"]) > 0

    def test_re_extract_unknown_source(self):
        from src.cron.extract_cron import re_extract
        result = re_extract("https://some-weird-domain.xyz/article")
        assert result is not None
        assert "error" in result


# ---------------------------------------------------------------------------
# digest.py tests
# ---------------------------------------------------------------------------

class TestDigest:
    def test_digest_module_imports(self):
        from src.cron.digest import call_llm
        assert callable(call_llm)
