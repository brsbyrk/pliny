"""Test Pliny SDK — HTTP client with mock urllib.

No real network calls. All HTTP mocked via unittest.mock.
"""

import json
from unittest.mock import patch, MagicMock

import pytest


class TestPlinyInit:
    def test_default_base_url(self):
        from sdk import Pliny
        p = Pliny()
        assert p.base_url == "http://localhost:3131"

    def test_custom_base_url(self):
        from sdk import Pliny
        p = Pliny(base_url="http://pliny.example.com:8080")
        assert p.base_url == "http://pliny.example.com:8080"

    def test_strips_trailing_slash(self):
        from sdk import Pliny
        p = Pliny(base_url="http://localhost:3131/")
        assert p.base_url == "http://localhost:3131"

    def test_agent_set(self):
        from sdk import Pliny
        p = Pliny(agent="sherlock")
        assert p.agent == "sherlock"

    def test_agent_none_by_default(self):
        from sdk import Pliny
        p = Pliny()
        assert p.agent is None

    def test_custom_timeout(self):
        from sdk import Pliny
        p = Pliny(timeout=30)
        assert p.timeout == 30


class TestSearch:
    def test_search_basic(self):
        from sdk import Pliny
        mock_response = {
            "entries": [
                {"id": "1", "title": "Test", "summary": "test summary"}
            ],
            "total": 1,
            "page": 1,
            "per_page": 30,
        }
        p = Pliny()
        with patch.object(p, "_request", return_value=mock_response) as mock_req:
            result = p.search(q="machine learning")
            mock_req.assert_called_once_with(
                "GET", "/api/entries",
                params={"q": "machine learning", "per_page": 30},
            )
            assert result == mock_response

    def test_search_with_tags(self):
        from sdk import Pliny
        mock_response = {"entries": [], "total": 0, "page": 1, "per_page": 10}
        p = Pliny()
        with patch.object(p, "_request", return_value=mock_response) as mock_req:
            result = p.search(q="ai", tags=["ml", "dl"], limit=10)
            mock_req.assert_called_once_with(
                "GET", "/api/entries",
                params={"q": "ai", "tags": "ml,dl", "per_page": 10},
            )
            assert result == mock_response

    def test_search_with_entry_type(self):
        from sdk import Pliny
        mock_response = {"entries": [], "total": 0, "page": 1, "per_page": 20}
        p = Pliny()
        with patch.object(p, "_request", return_value=mock_response) as mock_req:
            result = p.search(q="", entry_type="youtube", limit=20)
            mock_req.assert_called_once_with(
                "GET", "/api/entries",
                params={"entry_type": "youtube", "per_page": 20},
            )
            assert result == mock_response

    def test_search_no_query_no_tags(self):
        from sdk import Pliny
        mock_response = {"entries": [], "total": 0, "page": 1, "per_page": 30}
        p = Pliny()
        with patch.object(p, "_request", return_value=mock_response) as mock_req:
            result = p.search()
            mock_req.assert_called_once_with(
                "GET", "/api/entries",
                params={"per_page": 30},
            )
            assert result == mock_response


class TestRequest:
    def test_get_request_success(self):
        import urllib.request
        from sdk import Pliny
        mock_response_data = {"key": "value"}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        p = Pliny()
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = p._request("GET", "/api/test")
            assert result == mock_response_data
            mock_urlopen.assert_called_once()

    def test_get_request_with_params(self):
        import urllib.request
        from sdk import Pliny
        mock_response_data = {"results": [1, 2, 3]}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        p = Pliny()
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = p._request("GET", "/api/entries", params={"q": "test", "page": 1})
            assert result == mock_response_data
            call_args = mock_urlopen.call_args[0][0]
            assert "/api/entries?" in call_args.full_url
            assert "q=test" in call_args.full_url
            assert "page=1" in call_args.full_url

    def test_post_request_with_data(self):
        import urllib.request
        from sdk import Pliny
        mock_response_data = {"status": "ok"}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        p = Pliny()
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            result = p._request("POST", "/api/ingest", data={"url": "https://example.com"})
            assert result == mock_response_data
            call_args = mock_urlopen.call_args[0][0]
            assert call_args.method == "POST"

    def test_params_skip_empty_values(self):
        import urllib.request
        from sdk import Pliny
        mock_response_data = {"entries": []}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        p = Pliny()
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = p._request("GET", "/api/entries", params={"q": "", "tags": None, "limit": 10})
            assert result == mock_response_data

    def test_http_error(self):
        import urllib.request
        from sdk import Pliny

        p = Pliny()
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError(
                       "http://localhost:3131/api/test", 500, "Internal Error",
                       {}, None)) as mock_urlopen:
            with pytest.raises(Exception, match="Pliny HTTP 500"):
                p._request("GET", "/api/test")

    def test_connection_error(self):
        import urllib.request
        from sdk import Pliny

        p = Pliny()
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("Connection refused")) as mock_urlopen:
            with pytest.raises(Exception, match="Pliny connection failed"):
                p._request("GET", "/api/test")
