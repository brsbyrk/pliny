"""Test dashboard routes with FastAPI TestClient and real temp DB.

Strategy: apply real schema to temp DB, monkeypatch DB_PATH, then import app.
The tricky part is server.py's module-level _schema_get_db(DB_PATH).close().
We handle it by creating the DB file first so the call is a no-op.
"""

import json
import sys
import sqlite3
from unittest.mock import patch

import pytest


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    """Create a FastAPI TestClient with a temp DB."""
    import sys
    test_db_path = tmp_path / "pliny.db"

    # ---- Apply FULL schema to temp DB (with real get_db) ----
    from lib.schema import get_db as real_get_db
    _conn = real_get_db(str(test_db_path))
    _conn.close()

    # ---- Monkeypatch DB_PATH to point to temp DB ----
    monkeypatch.setattr("lib.paths.DB_PATH", test_db_path)

    # Also need to mock the server-level _schema_get_db call
    # But since we patched lib.paths.DB_PATH, the server will use our temp DB
    # which already has schema. That's fine — just need to make sure it connects.
    # The DB file exists at test_db_path with valid schema.

    # ---- Override get_db_conn in all route modules to use our temp DB ----
    import src.dashboard.routes.shared as dash_shared
    import src.dashboard.routes.search as search_mod
    import src.dashboard.routes.pipeline as pipeline_mod
    import src.dashboard.routes.entries as entries_mod
    import src.dashboard.routes.tags as tags_mod
    import src.dashboard.routes.stats as stats_mod
    import src.dashboard.routes.ingest as ingest_mod

    def _get_db_conn():
        conn = sqlite3.connect(str(test_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    for mod in [dash_shared, entries_mod, tags_mod, stats_mod, ingest_mod,
                search_mod, pipeline_mod]:
        if hasattr(mod, "get_db_conn"):
            monkeypatch.setattr(mod, "get_db_conn", _get_db_conn)

    # Patch paths
    query_path = tmp_path / "data" / "user" / "saved_queries.json"
    check_path = tmp_path / "data" / "user" / "saved_query_last_check.json"
    cmd_queue = tmp_path / "data" / "queues" / "command_queue.json"

    monkeypatch.setattr(dash_shared, "ROOT", tmp_path)
    monkeypatch.setattr(dash_shared, "COMMAND_QUEUE", cmd_queue)
    if hasattr(dash_shared, "DB_PATH"):
        monkeypatch.setattr(dash_shared, "DB_PATH", test_db_path)

    monkeypatch.setattr(search_mod, "ROOT", tmp_path)
    monkeypatch.setattr(search_mod, "SAVED_QUERIES_PATH", query_path)
    monkeypatch.setattr(search_mod, "SAVED_QUERIES_CHECK_PATH", check_path)

    monkeypatch.setattr(pipeline_mod, "ROOT", tmp_path)
    monkeypatch.setattr(pipeline_mod, "COMMAND_QUEUE", cmd_queue)

    if hasattr(entries_mod, "DB_PATH"):
        monkeypatch.setattr(entries_mod, "DB_PATH", test_db_path)

    # ---- Import app ----
    if "dashboard.server" in sys.modules:
        del sys.modules["dashboard.server"]
    from dashboard.server import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    return client


def _seed_entry(test_db_path, entry_id="test-1", **overrides):
    """Insert a test entry into the DB."""
    conn = sqlite3.connect(str(test_db_path))
    conn.row_factory = sqlite3.Row
    defaults = {
        "id": entry_id,
        "source_url": "https://example.com/article",
        "title": "Test Article",
        "content": "This is test content for the article.",
        "entry_type": "bookmark",
        "extraction_status": "extracted",
        "auto_tags": json.dumps(["ai", "ml"]),
        "starred": 0,
        "retry_count": 0,
        "created_at": "2024-01-01T00:00:00Z",
        "modified_at": "2024-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    conn.execute(
        """INSERT INTO entries (id, source_url, title, content, entry_type,
           extraction_status, auto_tags, starred, retry_count, created_at, modified_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (defaults["id"], defaults["source_url"], defaults["title"],
         defaults["content"], defaults["entry_type"], defaults["extraction_status"],
         defaults["auto_tags"], defaults["starred"], defaults["retry_count"],
         defaults["created_at"], defaults["modified_at"]),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Entries routes
# ---------------------------------------------------------------------------

class TestEntryRoutes:
    def test_get_entry_found(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1")
        resp = app_client.get("/api/entry/test-1")
        assert resp.status_code == 200

    def test_get_entry_not_found(self, app_client):
        resp = app_client.get("/api/entry/nonexistent")
        assert resp.status_code == 404

    def test_toggle_star(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", starred=0)
        resp = app_client.post("/api/entry/test-1/star")
        assert resp.status_code == 200

    def test_toggle_star_not_found(self, app_client):
        resp = app_client.post("/api/entry/nonexistent/star")
        assert resp.status_code == 404

    def test_get_starred(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", starred=1)
        _seed_entry(tmp_path / "pliny.db", "test-2", starred=0,
                    source_url="https://example.com/other",
                    auto_tags=json.dumps(["python"]))
        resp = app_client.get("/api/entries/starred")
        assert resp.status_code == 200

    def test_similarity_search(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1")
        resp = app_client.get("/api/similarity/search?q=test")
        assert resp.status_code == 200

    def test_similarity_search_empty_query(self, app_client):
        resp = app_client.get("/api/similarity/search?q=")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tags routes
# ---------------------------------------------------------------------------

class TestTagRoutes:
    def test_get_tags(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", auto_tags=json.dumps(["ai", "ml"]))
        _seed_entry(tmp_path / "pliny.db", "test-2", auto_tags=json.dumps(["ai", "python"]),
                    source_url="https://example.com/2")
        resp = app_client.get("/api/tags")
        assert resp.status_code == 200

    def test_get_tags_with_query(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", auto_tags=json.dumps(["ai", "ml"]))
        resp = app_client.get("/api/tags?query=ai")
        assert resp.status_code == 200

    def test_get_tag_graph(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", auto_tags=json.dumps(["ai", "ml"]))
        _seed_entry(tmp_path / "pliny.db", "test-2", auto_tags=json.dumps(["ai", "python"]),
                    source_url="https://example.com/2")
        resp = app_client.get("/api/tags/graph?min_count=1")
        assert resp.status_code == 200

    def test_get_related_tags(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", auto_tags=json.dumps(["ai", "ml"]))
        _seed_entry(tmp_path / "pliny.db", "test-2", auto_tags=json.dumps(["ai", "python"]),
                    source_url="https://example.com/2")
        resp = app_client.get("/api/tags/related/ai")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Search routes
# ---------------------------------------------------------------------------

class TestSearchRoutes:
    def test_search_entries(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1")
        resp = app_client.get("/api/entries")
        assert resp.status_code == 200

    def test_search_with_date_range(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", created_at="2024-06-15T00:00:00Z")
        resp = app_client.get("/api/entries?date_from=2024-01-01&date_to=2024-12-31")
        assert resp.status_code == 200

    def test_search_with_sort(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1")
        resp = app_client.get("/api/entries?sort=date_asc")
        assert resp.status_code == 200

    def test_search_with_entry_type(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", entry_type="youtube")
        resp = app_client.get("/api/entries?entry_type=youtube")
        assert resp.status_code == 200

    def test_deprecated_search_endpoint(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", content="some test content here")
        resp = app_client.get("/api/entries?q=test")
        assert resp.status_code == 200

    def test_fts_post_search(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", content="some test content here")
        resp = app_client.post("/api/search/fts", json={"q": "test", "limit": 10})
        assert resp.status_code == 200

    def test_fts_post_search_no_query(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", content="some content")
        resp = app_client.post("/api/search/fts", json={"q": "", "limit": 10})
        assert resp.status_code in (200, 400)

    def test_ask_requires_question(self, app_client):
        resp = app_client.post("/api/ask", json={})
        assert resp.status_code == 400

    def test_ask_with_question(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1",
                    content="Deep learning is a subset of machine learning.")
        with patch("dashboard.routes.search.call_llm",
                   return_value="Deep learning is about neural networks."):
            resp = app_client.post("/api/ask", json={"q": "what is deep learning?"})
            assert resp.status_code == 200

    def test_ask_no_results(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", content="X", title="X")
        with patch("dashboard.routes.search.call_llm", return_value="No answer."):
            resp = app_client.post("/api/ask", json={"q": "zzzxyznonexistentterm"})
            assert resp.status_code == 200

    def test_saved_queries_sync(self, app_client):
        resp = app_client.post("/api/saved-queries/sync", json={"myquery": {"q": "test"}})
        assert resp.status_code == 200

    def test_get_saved_queries(self, app_client):
        app_client.post("/api/saved-queries/sync", json={"myquery": {"q": "test"}})
        resp = app_client.get("/api/saved-queries")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Stats routes
# ---------------------------------------------------------------------------

class TestStatsRoutes:
    def test_get_stats(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1")
        resp = app_client.get("/api/stats")
        assert resp.status_code == 200

    def test_get_activity(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1")
        resp = app_client.get("/api/activity?limit=10")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Pipeline routes
# ---------------------------------------------------------------------------

class TestPipelineRoutes:
    def test_get_pipeline(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1")
        resp = app_client.get("/api/pipeline")
        assert resp.status_code == 200

    def test_cleanup_dead(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", content="", source_url="x", extraction_status="dead")
        resp = app_client.post("/api/pipeline/cleanup-dead")
        assert resp.status_code == 200

    def test_re_extract_thin(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1", content="short",
                    source_url="https://example.com/long-enough-url", extraction_status="thin")
        resp = app_client.post("/api/pipeline/re-extract-thin")
        assert resp.status_code == 200

    def test_command_queue(self, app_client):
        resp = app_client.post("/api/command", json={"command": "search ai agents"})
        assert resp.status_code == 200

    def test_read_command_queue(self, app_client):
        resp = app_client.get("/api/command/queue")
        assert resp.status_code == 200

    def test_clear_command_queue(self, app_client):
        resp = app_client.post("/api/command/clear")
        assert resp.status_code == 200

    def test_batch_summarize(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1")
        resp = app_client.post("/api/batch/summarize", json={"ids": ["test-1"]})
        assert resp.status_code == 200

    def test_batch_summarize_no_ids(self, app_client):
        resp = app_client.post("/api/batch/summarize", json={"ids": []})
        assert resp.status_code == 400

    def test_batch_tag(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1")
        resp = app_client.post("/api/batch/tag",
                               json={"ids": ["test-1"], "tag": "newtag"})
        assert resp.status_code == 200

    def test_batch_tag_missing_params(self, app_client):
        resp = app_client.post("/api/batch/tag", json={"ids": []})
        assert resp.status_code == 400

    def test_queue_re_extraction(self, app_client, tmp_path):
        _seed_entry(tmp_path / "pliny.db", "test-1")
        resp = app_client.post("/api/batch/queue-re-extraction",
                               json={"ids": ["test-1"]})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Ingest routes
# ---------------------------------------------------------------------------

class TestIngestRoutes:
    def test_ingest_no_url(self, app_client):
        resp = app_client.post("/api/ingest/add-url", json={"url": ""})
        assert resp.status_code == 400

    def test_ingest_add_url(self, app_client):
        with patch("ingest.url_ingest.ingest_url",
                   return_value="test-ingested-id"):
            resp = app_client.post("/api/ingest/add-url",
                                   json={"url": "https://example.com/article"})
            assert resp.status_code == 200

    def test_ingest_add_url_failure(self, app_client):
        with patch("ingest.url_ingest.ingest_url", return_value=None):
            resp = app_client.post("/api/ingest/add-url",
                                   json={"url": "https://example.com/article"})
            assert resp.status_code == 500

    def test_ingest_add_url_exception(self, app_client):
        with patch("ingest.url_ingest.ingest_url",
                   side_effect=RuntimeError("extraction crashed")):
            resp = app_client.post("/api/ingest/add-url",
                                   json={"url": "https://example.com/article"})
            assert resp.status_code == 500

    def test_karakeep_webhook(self, app_client):
        with patch("cli.sync.handle_karakeep_event",
                   return_value={"status": "ok"}):
            resp = app_client.post("/api/webhooks/karakeep",
                                   json={"event": "bookmark_created", "data": {}})
            assert resp.status_code == 200

    def test_karakeep_webhook_invalid_json(self, app_client):
        resp = app_client.post("/api/webhooks/karakeep",
                               content=b"not json",
                               headers={"Content-Type": "application/json"})
        assert resp.status_code == 400
