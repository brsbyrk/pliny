"""Shared test fixtures."""

import pytest
import sqlite3
from lib.schema import get_db


@pytest.fixture
def tmp_db(tmp_path):
    """Create a fresh temporary SQLite database with schema applied."""
    db_path = str(tmp_path / "test.db")
    db = get_db(db_path)
    db.row_factory = sqlite3.Row
    yield db
    db.close()


@pytest.fixture
def qe(tmp_db, tmp_path):
    """QueryEngine backed by the same temp DB as tmp_db."""
    from query import QueryEngine
    db_path = str(tmp_path / "test.db")
    engine = QueryEngine(db_path)
    import sqlite3
    tmp_db.row_factory = sqlite3.Row
    engine._db = tmp_db
    yield engine
    engine._db = None


@pytest.fixture
def sample_entry(qe):
    """Insert a sample entry and return its id."""
    qe._connect().execute(
        """INSERT INTO entries (id, source_url, title, content, created_at)
           VALUES (?, ?, ?, ?, datetime('now'))""",
        ("test-entry-1", "https://example.com/article", "Test Article", "This is test content for embedding and search."),
    )
    qe._connect().commit()
    return "test-entry-1"
