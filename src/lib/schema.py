"""SQLite schema: entries + FTS5 + sqlite-vec v0 vector index.

All columns are declared here. The get_db() function runs migration
checks for columns added after the initial schema (backward compat).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entries (
    id           TEXT PRIMARY KEY,
    source_url   TEXT NOT NULL,
    title        TEXT NOT NULL,
    content      TEXT NOT NULL,
    tags         TEXT,
    auto_tags    TEXT,
    tagged_at    TIMESTAMP,
    media_path   TEXT,
    starred      INTEGER NOT NULL DEFAULT 0,
    archived     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now')),
    modified_at  TEXT DEFAULT (datetime('now'))
);

-- Full-text search via FTS5
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    title, content,
    content='entries', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, title, content)
    VALUES (new.rowid, new.title, new.content);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, content)
    VALUES ('delete', old.rowid, old.title, old.content);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, content)
    VALUES ('delete', old.rowid, old.title, old.content);
    INSERT INTO entries_fts(rowid, title, content)
    VALUES (new.rowid, new.title, new.content);
END;

-- Vector index via sqlite-vec vec0 (ANN search)
CREATE VIRTUAL TABLE IF NOT EXISTS entries_v0 USING vec0(
    embedding float[384]
);
"""

VECTOR_DIMS = 384

# Columns that may have been added incrementally — check and migrate
_MIGRATION_COLUMNS = [
    ("media_path", "ALTER TABLE entries ADD COLUMN media_path TEXT"),
    ("auto_tags", "ALTER TABLE entries ADD COLUMN auto_tags TEXT"),
    ("tagged_at", "ALTER TABLE entries ADD COLUMN tagged_at TIMESTAMP"),
    ("starred", "ALTER TABLE entries ADD COLUMN starred INTEGER DEFAULT 0"),
    ("archived", "ALTER TABLE entries ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"),
    ("entry_type", "ALTER TABLE entries ADD COLUMN entry_type TEXT NOT NULL DEFAULT 'bookmark'"),
    ("extraction_status", "ALTER TABLE entries ADD COLUMN extraction_status TEXT DEFAULT 'pending'"),
    ("retry_count", "ALTER TABLE entries ADD COLUMN retry_count INTEGER DEFAULT 0"),
    ("source_refs", "ALTER TABLE entries ADD COLUMN source_refs TEXT"),
    ("session_id", "ALTER TABLE entries ADD COLUMN session_id TEXT"),
]


def _run_migrations(db: sqlite3.Connection) -> None:
    """Add any missing columns from ad-hoc migrations."""
    cols = {row[1] for row in db.execute("PRAGMA table_info(entries)").fetchall()}
    for col_name, alter_sql in _MIGRATION_COLUMNS:
        if col_name not in cols:
            db.execute(alter_sql)
    # Performance indices for frequently-queried columns
    db.execute("CREATE INDEX IF NOT EXISTS idx_entries_created_at ON entries(created_at DESC)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_entries_entry_type ON entries(entry_type)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_entries_starred ON entries(starred) WHERE starred = 1")
    db.execute("CREATE INDEX IF NOT EXISTS idx_entries_extraction_status ON entries(extraction_status)")
    db.commit()


def get_db(db_path: str | Path) -> sqlite3.Connection:
    """Open Pliny DB with sqlite-vec loaded and schema applied."""
    db = sqlite3.connect(str(db_path))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.executescript(SCHEMA_SQL)
    # Drop legacy subscription/notification tables if they exist
    db.execute("DROP TABLE IF EXISTS notifications")
    db.execute("DROP TABLE IF EXISTS subscriptions")
    _run_migrations(db)
    return db
