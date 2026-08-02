"""Test ingest extractor fetch() paths with mock HTTP.

No real network calls — all HTTP is mocked via unittest.mock or responses-style patching.
"""

from unittest.mock import patch, MagicMock

import pytest


# ===========================================================================
# X/Twitter fetch()
# ===========================================================================

class TestXFetch:
    def test_article_url_returns_unsupported(self):
        from ingest.x import fetch
        result = fetch("https://x.com/i/article/123456")
        assert result is not None
        assert result["_article_unsupported"] is True

    def test_no_status_id_returns_none(self):
        from ingest.x import fetch
        result = fetch("https://x.com/user")
        assert result is None

    def test_extract_tweet_id(self):
        from ingest.x import _extract_tweet_id
        assert _extract_tweet_id("https://x.com/user/status/12345678901234567") == "12345678901234567"
        assert _extract_tweet_id("https://twitter.com/user/status/12345678901234567") == "12345678901234567"
        assert _extract_tweet_id("no url here") is None
        assert _extract_tweet_id("https://x.com/user") is None

    def test_fetch_with_api_v2_success(self):
        from ingest.x import fetch, _fetch_x_via_api_v2, _fetch_x_via_fxtwitter
        # Mock API v2 response
        mock_api_data = {
            "tweet": {
                "text": "Hello world",
                "author": {"name": "Test User", "screen_name": "testuser"},
                "media": {"all": [], "photos": []},
                "public_metrics": {"like_count": 10, "retweet_count": 2},
            },
            "_source": "api_v2",
        }
        with patch("ingest.x._fetch_x_via_api_v2", return_value=mock_api_data):
            result = fetch("https://x.com/testuser/status/12345678901234567")
            assert result is not None
            assert result.get("_source") == "api_v2"
            assert result["tweet"]["text"] == "Hello world"

    def test_fetch_fxtwitter_fallback(self):
        from ingest.x import fetch
        mock_fxt_data = {
            "tweet": {
                "text": "Hello from fxtwitter",
                "author": {"name": "User", "screen_name": "user"},
                "media": {"all": [], "photos": []},
            },
        }
        with patch("ingest.x._fetch_x_via_api_v2", return_value=None), \
             patch("ingest.x._fetch_x_via_fxtwitter", return_value=mock_fxt_data):
            result = fetch("https://x.com/user/status/12345678901234567")
            assert result is not None
            assert result.get("_source") == "fxtwitter"

    def test_fetch_both_fail_returns_none(self):
        from ingest.x import fetch
        with patch("ingest.x._fetch_x_via_api_v2", return_value=None), \
             patch("ingest.x._fetch_x_via_fxtwitter", return_value=None):
            result = fetch("https://x.com/user/status/12345678901234567")
            assert result is None


# ===========================================================================
# GitHub fetch()
# ===========================================================================

class TestGithubFetch:
    def test_invalid_url(self):
        from ingest.github import fetch
        result = fetch("https://github.com/norepo")
        assert result["_error"] == "invalid_url"

    def test_valid_repo_readme(self):
        from ingest.github import fetch
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "# Test Repo\nThis is a readme."
        with patch("requests.get", return_value=mock_resp):
            result = fetch("https://github.com/testuser/myrepo")
            assert result["_fetch_source"] == "readme"
            assert result["readme"] == "# Test Repo\nThis is a readme."
            assert result["owner"] == "testuser"
            assert result["repo"] == "myrepo"

    def test_readme_fallback_to_master(self):
        from ingest.github import fetch
        mock_fail_resp = MagicMock()
        mock_fail_resp.status_code = 404
        mock_ok_resp = MagicMock()
        mock_ok_resp.status_code = 200
        mock_ok_resp.text = "# Master README"
        mock_ok_resp.json.return_value = {}
        with patch("requests.get", side_effect=[mock_fail_resp, mock_ok_resp, mock_ok_resp]):
            result = fetch("https://github.com/testuser/oldrepo")
            assert result["_fetch_source"] == "readme"

    def test_api_fallback(self):
        from ingest.github import fetch
        mock_readme_fail = MagicMock()
        mock_readme_fail.status_code = 404
        mock_api_ok = MagicMock()
        mock_api_ok.status_code = 200
        mock_api_ok.json.return_value = {
            "full_name": "testuser/myrepo",
            "description": "A great repo",
        }
        with patch("requests.get", side_effect=[mock_readme_fail, mock_readme_fail, mock_api_ok]):
            result = fetch("https://github.com/testuser/myrepo")
            assert result["_fetch_source"] == "api"
            assert result["description"] == "A great repo"

    def test_not_found_repo(self):
        from ingest.github import fetch
        mock_404 = MagicMock()
        mock_404.status_code = 404
        mock_404.json.side_effect = Exception("no body")
        with patch("requests.get", return_value=mock_404):
            result = fetch("https://github.com/testuser/notfound")
            assert result["_fetch_source"] in ("not_found", "http_404")

    def test_exception_returns_error(self):
        from ingest.github import fetch
        with patch("requests.get", side_effect=Exception("Network error")):
            result = fetch("https://github.com/testuser/myrepo")
            assert "_error" in result


# ===========================================================================
# YouTube fetch()
# ===========================================================================

class TestYoutubeFetch:
    def test_extract_video_id_normal(self):
        from ingest.youtube import _extract_video_id
        vid = _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert vid == "dQw4w9WgXcQ"

    def test_extract_video_id_short(self):
        from ingest.youtube import _extract_video_id
        vid = _extract_video_id("https://youtu.be/dQw4w9WgXcQ")
        assert vid == "dQw4w9WgXcQ"

    def test_extract_video_id_shorts(self):
        from ingest.youtube import _extract_video_id
        vid = _extract_video_id("https://www.youtube.com/shorts/abc123def45")
        assert vid == "abc123def45"

    def test_extract_video_id_none(self):
        from ingest.youtube import _extract_video_id
        assert _extract_video_id("https://www.youtube.com/") is None
        assert _extract_video_id("not a url") is None

    def test_fetch_no_video_id(self):
        from ingest.youtube import fetch
        result = fetch("https://youtube.com")
        assert result is None

    def test_fetch_with_oembed(self):
        from ingest.youtube import fetch
        mock_oembed = MagicMock()
        mock_oembed.status_code = 200
        mock_oembed.json.return_value = {
            "title": "Test Video",
            "author_name": "Test Author",
        }

        with patch("ingest.youtube._extract_video_id", return_value="test123"), \
             patch("requests.get", return_value=mock_oembed), \
             patch("ingest.youtube._fetch_youtube_transcript", return_value=None), \
             patch("ingest.youtube._download_youtube_video", return_value=None), \
             patch("subprocess.run"):
            result = fetch("https://youtube.com/watch?v=test123")
            assert result is not None
            assert result["title"] == "Test Video"
            assert result["author"] == "Test Author"

    def test_fetch_with_transcript(self):
        from ingest.youtube import fetch
        mock_oembed = MagicMock()
        mock_oembed.status_code = 200
        mock_oembed.json.return_value = {
            "title": "Test Video",
        }

        with patch("ingest.youtube._extract_video_id", return_value="test123"), \
             patch("requests.get", return_value=mock_oembed), \
             patch("ingest.youtube._fetch_youtube_transcript",
                   return_value="This is the transcript text."), \
             patch("ingest.youtube._download_youtube_video", return_value=None):
            result = fetch("https://youtube.com/watch?v=test123")
            assert result is not None
            assert result["transcript"] == "This is the transcript text."
            assert result["transcript_source"] == "ytdlp"


# ===========================================================================
# YouTube format()
# ===========================================================================

class TestYoutubeFormat:
    def test_format_with_transcript(self):
        from ingest.youtube import format as yt_format
        raw = {
            "title": "Test Video", "author": "Author",
            "transcript": "Transcript content here.",
            "transcript_source": "ytdlp",
            "media_path": "/media/test.mp4",
        }
        result = yt_format(raw, "https://youtube.com/watch?v=test")
        assert result["status"] == "youtube_transcript"
        assert "Transcript" in result["content"]
        assert result["media_path"] == "/media/test.mp4"

    def test_format_whisper(self):
        from ingest.youtube import format as yt_format
        raw = {
            "title": "Test Video",
            "transcript": "Whisper transcript.",
            "transcript_source": "whisper",
        }
        result = yt_format(raw, "https://youtube.com/watch?v=test")
        assert result["status"] == "youtube_whisper"

    def test_format_no_video_title(self):
        from ingest.youtube import format as yt_format
        result = yt_format({}, "url")
        assert result["status"] == "youtube_no_id"

    def test_format_no_title_with_video_id(self):
        from ingest.youtube import format as yt_format
        result = yt_format({"video_id": "test123"}, "url")
        assert result["status"] == "youtube_unavailable"

    def test_format_oembed_only(self):
        from ingest.youtube import format as yt_format
        raw = {
            "title": "Test Video", "author": "Author",
            "description": "A description of the video.",
        }
        result = yt_format(raw, "https://youtube.com/watch?v=test")
        assert result["status"] == "youtube_oembed"
        assert "Description" in result["content"]

    def test_format_metadata_only(self):
        from ingest.youtube import format as yt_format
        raw = {"title": "Test Video"}
        result = yt_format(raw, "https://youtube.com/watch?v=test")
        assert result["status"] == "youtube_metadata_only"

    def test_parse_vtt(self):
        from ingest.youtube import _parse_vtt
        vtt = """WEBVTT

00:00:01.000 --> 00:00:05.000
Hello world

00:00:05.000 --> 00:00:10.000
<v Speaker>This is a test</v>

"""
        result = _parse_vtt(vtt)
        assert "Hello world" in result
        assert "This is a test" in result
        assert "WEBVTT" not in result
        assert "-->" not in result


# ===========================================================================
# Web fetch()
# ===========================================================================

class TestWebFetch:
    def test_fetch_success(self):
        from ingest.web import fetch
        mock_resp = MagicMock()
        mock_resp.text = "<html><body>Hello</body></html>"
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        with patch("requests.get", return_value=mock_resp):
            result = fetch("https://example.com")
            assert result["html"] == "<html><body>Hello</body></html>"
            assert result["status_code"] == 200

    def test_fetch_404_dead(self):
        from ingest.web import fetch
        import requests as req_mod
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        http_error = req_mod.exceptions.HTTPError(response=mock_resp)
        with patch("requests.get", side_effect=http_error):
            result = fetch("https://example.com/gone")
            assert result["_error"] == "dead"

    def test_fetch_403_blocked(self):
        from ingest.web import fetch
        import requests as req_mod
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        http_error = req_mod.exceptions.HTTPError(response=mock_resp)
        with patch("requests.get", side_effect=http_error):
            result = fetch("https://example.com/blocked")
            assert result["_error"] == "blocked"

    def test_fetch_connection_error(self):
        from ingest.web import fetch
        import requests as req_mod
        with patch("requests.get", side_effect=req_mod.exceptions.ConnectionError()):
            result = fetch("https://example.com")
            assert result["_error"] == "connection_error"

    def test_fetch_timeout(self):
        from ingest.web import fetch
        import requests as req_mod
        with patch("requests.get", side_effect=req_mod.exceptions.Timeout()):
            result = fetch("https://example.com")
            assert result["_error"] == "timeout"

    def test_fetch_generic_exception(self):
        from ingest.web import fetch
        with patch("requests.get", side_effect=RuntimeError("boom")):
            result = fetch("https://example.com")
            assert "_error" in result


# ===========================================================================
# Reddit fetch() — test format since fetch needs actual API
# ===========================================================================

class TestRedditFormatAdditional:
    def test_format_error_unknown(self):
        from ingest.reddit import format as reddit_format
        result = reddit_format({"_error": "some_other_error"}, "")
        assert result["status"].startswith("reddit_")

    def test_format_no_post(self):
        from ingest.reddit import format as reddit_format
        result = reddit_format({}, "https://reddit.com/r/test/")
        # Should handle gracefully
        assert "status" in result


# ===========================================================================
# URL Ingest helpers
# ===========================================================================

class TestClassifyUrl:
    def test_x_urls(self):
        from ingest.url_ingest import classify_url
        assert classify_url("https://x.com/user/status/123") == "x"
        assert classify_url("https://twitter.com/user/status/123") == "x"

    def test_youtube_urls(self):
        from ingest.url_ingest import classify_url
        assert classify_url("https://youtube.com/watch?v=123") == "youtube"
        assert classify_url("https://youtu.be/abc123") == "youtube"

    def test_github_urls(self):
        from ingest.url_ingest import classify_url
        assert classify_url("https://github.com/user/repo") == "github"

    def test_reddit_urls(self):
        from ingest.url_ingest import classify_url
        assert classify_url("https://reddit.com/r/python/comments/123") == "reddit"

    def test_web_fallback(self):
        from ingest.url_ingest import classify_url
        assert classify_url("https://example.com/article") == "web"


class TestEntryTypeForUrl:
    def test_x_article(self):
        from ingest.url_ingest import entry_type_for_url
        result = entry_type_for_url("https://x.com/user/status/123", 500,
                                    "x_v2_article")
        assert result == "x_article"

    def test_x_short_tweet(self):
        from ingest.url_ingest import entry_type_for_url
        result = entry_type_for_url("https://x.com/user/status/123", 50)
        assert result == "x_observation"

    def test_x_long_thread(self):
        from ingest.url_ingest import entry_type_for_url
        result = entry_type_for_url("https://x.com/user/status/123", 500)
        assert result == "x_thread"

    def test_youtube(self):
        from ingest.url_ingest import entry_type_for_url
        result = entry_type_for_url("https://youtube.com/watch?v=123", 1000)
        assert result == "youtube"

    def test_github(self):
        from ingest.url_ingest import entry_type_for_url
        result = entry_type_for_url("https://github.com/user/repo", 500)
        assert result == "github"


class TestSlugify:
    def test_basic_title(self):
        from ingest.url_ingest import _slugify
        result = _slugify("Hello World")
        assert result == "hello-world"

    def test_special_chars(self):
        from ingest.url_ingest import _slugify
        result = _slugify("AI & ML: The Future!")
        assert result == "ai-ml-the-future"

    def test_truncate(self):
        from ingest.url_ingest import _slugify
        result = _slugify("a" * 100)
        assert len(result) <= 64
