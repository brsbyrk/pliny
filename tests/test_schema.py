"""Test SQLite schema and migrations."""

from lib.schema import get_db


class TestSchema:
    def test_creates_tables(self, tmp_db):
        """Core tables should exist after get_db()."""
        tables = {
            r[0] for r in tmp_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "entries" in tables
        assert "entries_fts" in tables
        assert "entries_v0" in tables

    def test_has_all_columns(self, tmp_db):
        """All expected columns should be present."""
        cols = {r[1] for r in tmp_db.execute("PRAGMA table_info(entries)").fetchall()}
        expected = {
            "id", "source_url", "title", "content", "tags",
            "auto_tags", "tagged_at", "media_path",
            "starred", "archived", "created_at", "modified_at",
        }
        missing = expected - cols
        assert not missing, f"Missing columns: {missing}"

    def test_triggers_exist(self, tmp_db):
        """FTS5 sync triggers should exist."""
        triggers = {
            r[0] for r in tmp_db.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        for t in ("entries_ai", "entries_ad", "entries_au"):
            assert t in triggers, f"Missing trigger: {t}"

    def test_vector_table_exists(self, tmp_db):
        """Vec0 virtual table should accept 384-dim embeddings."""
        tmp_db.execute(
            "INSERT INTO entries (id, source_url, title, content) VALUES ('v1', 'u', 't', 'c')"
        )
        rowid = tmp_db.execute("SELECT rowid FROM entries WHERE id = 'v1'").fetchone()[0]
        vec = ", ".join(["0.1"] * 384)
        tmp_db.execute(
            f"INSERT INTO entries_v0 (rowid, embedding) VALUES (?, '[{vec}]')",
            (rowid,),
        )
        tmp_db.commit()
        count = tmp_db.execute("SELECT COUNT(*) FROM entries_v0").fetchone()[0]
        assert count == 1

    def test_new_db_migration_idempotent(self):
        """Calling get_db() twice on same file should not error."""
        import tempfile, os
        path = tempfile.mktemp(suffix=".db")
        try:
            db1 = get_db(path)
            db1.close()
            db2 = get_db(path)
            db2.close()
        finally:
            os.unlink(path)
