//! SQLite schema and migrations.

use anyhow::Result;
use rusqlite::Connection;

/// Apply the full schema and any pending migrations.
pub fn apply(conn: &Connection) -> Result<()> {
    conn.execute_batch(SCHEMA_SQL)?;
    run_migrations(conn)?;
    Ok(())
}

const SCHEMA_SQL: &str = r#"
CREATE TABLE IF NOT EXISTS entries (
    id           TEXT PRIMARY KEY,
    source_url   TEXT NOT NULL,
    title        TEXT NOT NULL,
    content      TEXT NOT NULL,
    source_type  TEXT NOT NULL DEFAULT 'web',
    tags         TEXT NOT NULL DEFAULT '[]',
    auto_tags    TEXT,
    starred      INTEGER NOT NULL DEFAULT 0,
    archived     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now')),
    modified_at  TEXT DEFAULT (datetime('now'))
);

-- Full-text search
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

-- Vector index (384-dim embeddings from all-MiniLM-L6-v2)
CREATE VIRTUAL TABLE IF NOT EXISTS entries_v0 USING vec0(
    embedding float[384]
);

CREATE INDEX IF NOT EXISTS idx_entries_created_at ON entries(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_entries_source_type ON entries(source_type);
CREATE INDEX IF NOT EXISTS idx_entries_starred ON entries(starred) WHERE starred = 1;
"#;

fn run_migrations(_conn: &Connection) -> Result<()> {
    // Placeholder for future column additions.
    // Example pattern:
    //   let cols: Vec<String> = conn
    //       .prepare("PRAGMA table_info(entries)")?
    //       .query_map([], |r| r.get(1))?
    //       .filter_map(|r| r.ok())
    //       .collect();
    //   if !cols.contains(&"new_column".to_string()) {
    //       conn.execute("ALTER TABLE entries ADD COLUMN new_column TEXT", [])?;
    //   }
    Ok(())
}
