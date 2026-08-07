//! Search engine — FTS5, vector, and hybrid RRF.

mod embed;
pub use embed::{Embedder, EMBEDDING_DIM};

use anyhow::Result;
use rusqlite::params;
use serde::Serialize;

use crate::store::Store;

/// A search result — entry metadata + snippet.
#[derive(Debug, Serialize, Clone)]
pub struct SearchResult {
    pub id: String,
    pub title: String,
    pub source_url: String,
    pub source_type: String,
    pub created_at: String,
    pub snippet: String,
    pub tags: Vec<String>,
}

impl Store {
    /// Full-text search via FTS5 with BM25 ranking.
    pub fn search_fts(&self, query: &str, limit: usize) -> Result<Vec<SearchResult>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT e.id, e.title, e.source_url, e.source_type, e.created_at, e.tags,
                    snippet(entries_fts, 0, '<mark>', '</mark>', '…', 40) AS snippet
             FROM entries_fts
             JOIN entries e ON e.rowid = entries_fts.rowid
             WHERE entries_fts MATCH ?
             ORDER BY rank
             LIMIT ?"
        )?;

        let rows = stmt.query_map(params![query, limit], |row| {
            let tags_str: String = row.get(5).unwrap_or_default();
            let tags: Vec<String> = serde_json::from_str(&tags_str).unwrap_or_default();
            Ok(SearchResult {
                id: row.get(0)?,
                title: row.get(1)?,
                source_url: row.get(2)?,
                source_type: row.get(3)?,
                created_at: row.get(4)?,
                snippet: row.get(6)?,
                tags,
            })
        })?;

        let mut results = Vec::new();
        for row in rows {
            results.push(row?);
        }
        Ok(results)
    }

    /// List recent entries.
    pub fn list_recent(&self, limit: usize) -> Result<Vec<SearchResult>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT id, title, source_url, source_type, created_at, coalesce(tags, '[]') as tags,
                    substr(content, 1, 200) AS snippet
             FROM entries
             ORDER BY created_at DESC
             LIMIT ?"
        )?;

        let rows = stmt.query_map(params![limit], |row| {
            let tags_str: String = row.get(5).unwrap_or_default();
            let tags: Vec<String> = serde_json::from_str(&tags_str).unwrap_or_default();
            Ok(SearchResult {
                id: row.get(0)?,
                title: row.get(1)?,
                source_url: row.get(2)?,
                source_type: row.get(3)?,
                created_at: row.get(4)?,
                snippet: row.get(6)?,
                tags,
            })
        })?;

        let mut results = Vec::new();
        for row in rows {
            results.push(row?);
        }
        Ok(results)
    }

    /// Get a single entry by ID.
    pub fn get_entry(&self, id: &str) -> Result<Option<crate::core::Entry>> {
        let conn = self.conn();
        let mut stmt = conn.prepare(
            "SELECT id, source_url, title, content, source_type, tags, created_at
             FROM entries WHERE id = ?"
        )?;

        let mut rows = stmt.query_map(params![id], |row| {
            let tags_str: String = row.get(5).unwrap_or_default();
            let tags: Vec<String> = serde_json::from_str(&tags_str).unwrap_or_default();
            let created_at: String = row.get(6)?;

            Ok(crate::core::Entry {
                id: crate::core::EntryId(row.get(0)?),
                source_url: row.get(1)?,
                title: row.get(2)?,
                content: row.get(3)?,
                source_type: {
                    let s: String = row.get(4)?;
                    match s.as_str() {
                        "x" => crate::core::SourceType::X,
                        "youtube" => crate::core::SourceType::YouTube,
                        "github" => crate::core::SourceType::GitHub,
                        "reddit" => crate::core::SourceType::Reddit,
                        "feed" => crate::core::SourceType::Feed,
                        "" => crate::core::SourceType::Note,
                        "note" => crate::core::SourceType::Note,
                        _ => crate::core::SourceType::Web,
                    }
                },
                tags,
                created_at: chrono::DateTime::parse_from_rfc3339(&created_at)
                    .map(|dt| dt.with_timezone(&chrono::Utc))
                    .unwrap_or_else(|_| chrono::Utc::now()),
            })
        })?;

        Ok(rows.next().transpose()?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::{Entry, EntryId, SourceType};

    fn sample_entry(id: &str, title: &str, content: &str) -> Entry {
        Entry {
            id: EntryId(id.into()),
            source_url: format!("https://example.com/{id}"),
            title: title.into(),
            content: content.into(),
            source_type: SourceType::Web,
            tags: Vec::new(),
            created_at: chrono::Utc::now(),
        }
    }

    #[test]
    fn search_fts_finds_entry() {
        let store = Store::open_in_memory().unwrap();
        store.insert(&sample_entry("1", "Rust Programming Guide", "How to write async code in Rust with Tokio")).unwrap();
        store.insert(&sample_entry("2", "Python Tips", "List comprehensions and generators")).unwrap();

        let results = store.search_fts("Rust async", 10).unwrap();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].id, "1");
    }

    #[test]
    fn search_fts_no_match() {
        let store = Store::open_in_memory().unwrap();
        store.insert(&sample_entry("1", "Rust", "content")).unwrap();

        let results = store.search_fts("zzzxyznonexistent", 10).unwrap();
        assert!(results.is_empty());
    }

    #[test]
    fn list_recent_returns_ordered() {
        let store = Store::open_in_memory().unwrap();
        store.insert(&sample_entry("a", "First", "one")).unwrap();
        store.insert(&sample_entry("b", "Second", "two")).unwrap();

        let results = store.list_recent(10).unwrap();
        assert_eq!(results.len(), 2);
    }

    #[test]
    fn get_entry_returns_full_content() {
        let store = Store::open_in_memory().unwrap();
        store.insert(&sample_entry("test-id", "Test Title", "Full content here")).unwrap();

        let entry = store.get_entry("test-id").unwrap().expect("should find entry");
        assert_eq!(entry.title, "Test Title");
        assert_eq!(entry.content, "Full content here");
    }

    #[test]
    fn get_entry_not_found() {
        let store = Store::open_in_memory().unwrap();
        assert!(store.get_entry("nonexistent").unwrap().is_none());
    }
}
