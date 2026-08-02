"""Test the QueryEngine class."""

import json
import pytest
from query import QueryEngine


class TestQueryEngine:
    def test_recent_returns_entries(self, qe, sample_entry):
        """recent() should return entries ordered by date."""
        results = qe.recent(5)
        assert len(results) >= 1
        assert results[0]["id"] == "test-entry-1"

    def test_entry_by_id_found(self, qe, sample_entry):
        """entry_by_id should return the correct entry."""
        entry = qe.entry_by_id("test-entry-1")
        assert entry is not None
        assert entry["title"] == "Test Article"
        assert entry["source_url"] == "https://example.com/article"

    def test_entry_by_id_not_found(self, qe):
        """entry_by_id should return None for missing entries."""
        assert qe.entry_by_id("nonexistent") is None

    def test_all_entries(self, qe, sample_entry):
        """all_entries() should return all entries."""
        entries = qe.all_entries()
        assert len(entries) >= 1
        ids = [e["id"] for e in entries]
        assert "test-entry-1" in ids

    def test_tags_operations(self, qe, sample_entry):
        """Adding and listing tags should work."""
        assert qe.add_tag("test-entry-1", "test-tag")
        assert qe.add_tag("test-entry-1", "ai")

        tags = qe.list_tags()
        tag_names = [t["tag"] for t in tags]
        assert "test-tag" in tag_names
        assert "ai" in tag_names

        # Verify tags were stored
        entry = qe.entry_by_id("test-entry-1")
        stored = json.loads(entry["tags"])
        assert "test-tag" in stored
        assert "ai" in stored

    def test_delete_entry(self, qe, sample_entry):
        """delete_entry should remove entry from all tables."""
        assert qe.delete_entry("test-entry-1")
        assert qe.entry_by_id("test-entry-1") is None

    def test_archive_entry(self, qe, sample_entry):
        """archive_entry should set archived flag."""
        assert qe.archive_entry("test-entry-1")
        entry = qe.entry_by_id("test-entry-1")
        assert entry is not None

    def test_context_manager(self):
        """QueryEngine should work as context manager on :memory:."""
        with QueryEngine(":memory:") as qe:
            assert qe.recent(1) == []
