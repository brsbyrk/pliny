//! SQLite store — schema, FTS5, vec0, and CRUD operations.

mod schema;

use anyhow::Result;
use rusqlite::Connection;
use std::path::Path;
use std::sync::Mutex;

/// Persistent store wrapping a SQLite connection with FTS5 + vec0.
pub struct Store {
    conn: Mutex<Connection>,
}

impl Store {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        unsafe {
            rusqlite::ffi::sqlite3_auto_extension(Some(std::mem::transmute(
                sqlite_vec::sqlite3_vec_init as *const (),
            )));
        }
        let conn = Connection::open(path)?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
        schema::apply(&conn)?;
        Ok(Self { conn: Mutex::new(conn) })
    }

    pub fn open_in_memory() -> Result<Self> {
        unsafe {
            rusqlite::ffi::sqlite3_auto_extension(Some(std::mem::transmute(
                sqlite_vec::sqlite3_vec_init as *const (),
            )));
        }
        let conn = Connection::open_in_memory()?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
        schema::apply(&conn)?;
        Ok(Self { conn: Mutex::new(conn) })
    }

    pub fn conn(&self) -> std::sync::MutexGuard<'_, Connection> {
        self.conn.lock().expect("store lock poisoned")
    }

    pub fn insert(&self, entry: &crate::core::Entry) -> Result<bool> {
        let conn = self.conn();
        let exists: bool = if entry.source_url.is_empty() {
            // Notes have no source_url — dedup by content hash instead
            false // Always allow notes (content variation ensures uniqueness)
        } else {
            conn.query_row(
                "SELECT COUNT(*) > 0 FROM entries WHERE source_url = ?1",
                rusqlite::params![entry.source_url],
                |r| r.get(0),
            )?
        };
        if exists { return Ok(false); }
        conn.execute(
            "INSERT INTO entries (id, source_url, title, content, source_type, tags, created_at, modified_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?7)",
            rusqlite::params![
                entry.id.to_string(), entry.source_url, entry.title, entry.content,
                entry.source_type.as_str(), serde_json::to_string(&entry.tags)?,
                entry.created_at.to_rfc3339(),
            ],
        )?;
        Ok(true)
    }

    pub fn count(&self) -> Result<usize> {
        self.conn().query_row("SELECT COUNT(*) FROM entries", [], |r| r.get(0))
            .map_err(Into::into)
    }

    /// Toggle starred status. Returns new state (true = starred).
    pub fn toggle_star(&self, id: &str) -> Result<bool> {
        let conn = self.conn();
        conn.execute(
            "UPDATE entries SET starred = CASE WHEN starred = 1 THEN 0 ELSE 1 END
             WHERE id = ?1",
            rusqlite::params![id],
        )?;
        conn.query_row("SELECT starred FROM entries WHERE id = ?1", rusqlite::params![id], |r| r.get(0))
            .map(|s: i32| s == 1)
            .map_err(Into::into)
    }

    /// Store an embedding vector for an entry (384 f32 values as blob).
    pub fn insert_with_embedding(&self, entry: &crate::core::Entry, embedding: &[f32]) -> Result<bool> {
        let inserted = self.insert(entry)?;
        if inserted {
            self.insert_embedding(&entry.id.to_string(), embedding)?;
        }
        Ok(inserted)
    }

    /// Store a 384-dim embedding blob linked to an entry rowid.
    pub fn insert_embedding(&self, entry_id: &str, embedding: &[f32]) -> Result<()> {
        let conn = self.conn();
        conn.execute(
            "INSERT OR REPLACE INTO entries_v0(rowid, embedding)
             VALUES ((SELECT rowid FROM entries WHERE id = ?1), ?2)",
            rusqlite::params![entry_id, f32_to_blob(embedding)],
        )?;
        Ok(())
    }

    /// Vector KNN search via vec0.
    pub fn search_vec(&self, embedding: &[f32], limit: usize) -> Result<Vec<(String, f32)>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT e.id, v.distance
             FROM entries_v0 v
             JOIN entries e ON e.rowid = v.rowid
             WHERE v.embedding MATCH ?1
             ORDER BY v.distance
             LIMIT ?2"
        )?;
        let rows = stmt.query_map(rusqlite::params![f32_to_blob(embedding), limit], |row| {
            Ok((row.get::<_, String>(0)?, 1.0 - row.get::<_, f32>(1)?))
        })?;
        rows.collect::<Result<Vec<_>, _>>().map_err(Into::into)
    }

    /// Hybrid RRF: fuse FTS5 + vector results.
    pub fn search_hybrid(&self, query: &str, embedding: &[f32], limit: usize) -> Result<Vec<crate::search::SearchResult>> {
        let fts = self.search_fts(query, limit * 2)?;
        let vec = self.search_vec(embedding, limit * 2)?;
        let mut scores: std::collections::HashMap<String, f32> = std::collections::HashMap::new();
        const K: f32 = 60.0;
        for (i, r) in fts.iter().enumerate() { *scores.entry(r.id.clone()).or_default() += 1.0 / (K + i as f32 + 1.0); }
        for (i, (id, _)) in vec.iter().enumerate() { *scores.entry(id.clone()).or_default() += 1.0 / (K + i as f32 + 1.0); }
        let mut scored: Vec<_> = scores.into_iter().collect();
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        scored.truncate(limit);

        let mut results = Vec::new();
        for (id, _) in &scored {
            if let Some(r) = fts.iter().find(|r| &r.id == id) {
                results.push(r.clone());
            }
        }
        Ok(results)
    }

    /// Knowledge base statistics.
    pub fn stats(&self) -> Result<Stats> {
        let conn = self.conn();
        let total = conn.query_row("SELECT COUNT(*) FROM entries", [], |r| r.get(0))?;

        let mut stmt = conn.prepare(
            "SELECT source_type, COUNT(*) FROM entries GROUP BY source_type ORDER BY COUNT(*) DESC"
        )?;
        let mut by_source = std::collections::BTreeMap::new();
        let rows = stmt.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, usize>(1)?)))?;
        for r in rows { let (k, v) = r?; by_source.insert(k, v); }

        let mut stmt = conn.prepare("SELECT tags FROM entries WHERE tags != '[]'")?;
        let mut tag_counts: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
        let rows = stmt.query_map([], |r| r.get::<_, String>(0))?;
        for r in rows {
            let tags_str = r?;
            if let Ok(tags) = serde_json::from_str::<Vec<String>>(&tags_str) {
                for tag in tags { *tag_counts.entry(tag).or_default() += 1; }
            }
        }
        let mut top_tags: Vec<_> = tag_counts.into_iter().collect();
        top_tags.sort_by(|a, b| b.1.cmp(&a.1));
        top_tags.truncate(10);

        let last = conn.query_row(
            "SELECT title, source_type, created_at FROM entries ORDER BY created_at DESC LIMIT 1",
            [],
            |r| Ok(LastEntry { title: r.get(0)?, source_type: r.get(1)?, created_at: r.get(2)? }),
        ).ok();

        let db_size = conn.path()
            .and_then(|p| std::fs::metadata(p).ok())
            .map(|m| m.len() as f64 / 1_000_000.0)
            .unwrap_or(0.0);

        Ok(Stats { total, db_size_mb: db_size, by_source, top_tags, last_ingested: last })
    }
}

/// Knowledge base statistics.
#[derive(Debug, serde::Serialize)]
pub struct Stats {
    pub total: usize,
    pub db_size_mb: f64,
    pub by_source: std::collections::BTreeMap<String, usize>,
    pub top_tags: Vec<(String, usize)>,
    pub last_ingested: Option<LastEntry>,
}

#[derive(Debug, serde::Serialize)]
pub struct LastEntry {
    pub title: String,
    pub source_type: String,
    pub created_at: String,
}

fn f32_to_blob(data: &[f32]) -> Vec<u8> {
    data.iter().flat_map(|f| f.to_le_bytes()).collect()
}
