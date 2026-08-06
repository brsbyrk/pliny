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
    /// Open (or create) the database at `path`, applying all migrations.
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }

        // Register sqlite-vec extension before opening any connection
        unsafe {
            rusqlite::ffi::sqlite3_auto_extension(Some(std::mem::transmute(
                sqlite_vec::sqlite3_vec_init as *const (),
            )));
        }

        let conn = Connection::open(path)?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
        schema::apply(&conn)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    /// Open an in-memory database for testing.
    pub fn open_in_memory() -> Result<Self> {
        // Register extension (idempotent — safe to call multiple times)
        unsafe {
            rusqlite::ffi::sqlite3_auto_extension(Some(std::mem::transmute(
                sqlite_vec::sqlite3_vec_init as *const (),
            )));
        }

        let conn = Connection::open_in_memory()?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;")?;
        schema::apply(&conn)?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    /// Acquire a lock on the underlying connection.
    pub fn conn(&self) -> std::sync::MutexGuard<'_, Connection> {
        self.conn.lock().expect("store lock poisoned")
    }
}
