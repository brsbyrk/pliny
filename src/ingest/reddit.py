"""Reddit extractor — fetch + format for posts and comments."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

REDDIT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_LAST_REDDIT_CALL = 0.0
_REDDIT_CALL_INTERVAL = 5.0
_REDDIT_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rate_limit_reddit() -> None:
    """Ensure at least _REDDIT_CALL_INTERVAL seconds between Reddit API calls."""
    global _LAST_REDDIT_CALL
    with _REDDIT_LOCK:
        elapsed = time.time() - _LAST_REDDIT_CALL
        if elapsed < _REDDIT_CALL_INTERVAL:
            time.sleep(_REDDIT_CALL_INTERVAL - elapsed)
        _LAST_REDDIT_CALL = time.time()


def _resolve_share_link(url: str) -> str | None:
    """Resolve a reddit.com/s/ share link to the canonical post URL."""
    if "/s/" not in url:
        return url

    # Strategy 1: Use Playwright via Node.js script
    try:
        script = Path(__file__).resolve().parent / "resolve_reddit_share.js"
        import subprocess
        r = subprocess.run(
            ["node", str(script), url],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            data = json.loads(r.stdout)
            if data.get("canonical_url"):
                return data["canonical_url"]
        return None
    except Exception as e:
        logger.debug("playwright reddit share resolve failed: %s", e)

    # Strategy 2 (fallback): parse share page HTML
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": REDDIT_UA,
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="replace")
        m = re.search(r'href="(https?://[^"]+?)">Moved Permanently', html)
        if m:
            raw = m.group(1).replace("&amp;", "&")
            return raw.split("?")[0]
        m = re.search(r'href="(https?://[^"]*reddit\.com[^"]*/comments/[^"]+?)"', html)
        if m:
            raw = m.group(1).replace("&amp;", "&")
            return raw.split("?")[0]
    except Exception as e:
        logger.debug("reddit share page HTML parse failed: %s", e)

    return None


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch(url: str, canonical_url: str | None = None) -> dict | None:
    """Fetch raw Reddit post data via the public JSON API.

    Args:
        url: The Reddit URL (share link or direct post URL)
        canonical_url: Optional pre-resolved canonical URL. Skips share link
                       resolution step.

    Returns:
        Dict with post data, or dict with _error key on known failures,
        or None on unrecoverable errors.
    """
    try:
        # Resolve to canonical post URL
        post_url = canonical_url if canonical_url is not None else _resolve_share_link(url)
        if not post_url:
            return {"_error": "resolve_failed"}

        # Fetch JSON
        _rate_limit_reddit()
        json_url = f"{post_url.rstrip('/')}/.json"
        req = urllib.request.Request(
            json_url,
            headers={
                "User-Agent": REDDIT_UA,
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))

        if not isinstance(data, list) or len(data) < 2:
            return {"_error": "invalid_response"}

        post = data[0]["data"]["children"][0]["data"]
        comments = data[1]["data"]["children"]

        return {
            "post": post,
            "comments": comments,
        }

    except urllib.error.HTTPError as e:
        return {"_error": f"http_{e.code}"}
    except urllib.error.URLError as e:
        return {"_error": f"network: {e.reason}"}
    except json.JSONDecodeError:
        return {"_error": "json_decode_error"}
    except Exception as e:
        return {"_error": str(e)}


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


def format(raw: dict, url: str) -> dict:
    """Convert raw Reddit data into standard {title, content, status} shape."""
    # Handle errors
    error = raw.get("_error")
    if error == "resolve_failed":
        return {"title": None, "content": None, "status": "reddit_resolve_failed"}
    if error == "invalid_response":
        return {"title": None, "content": None, "status": "reddit_invalid_response"}
    if error and error.startswith("http_"):
        return {"title": None, "content": None, "status": f"reddit_{error}"}
    if error and error.startswith("network:"):
        return {"title": None, "content": None, "status": f"reddit_network: {error[8:]}"}
    if error == "json_decode_error":
        return {"title": None, "content": None, "status": "reddit_json_decode_error"}
    if error is not None:
        return {"title": None, "content": None, "status": f"reddit_error: {error}"}

    post = raw.get("post", {})
    comments = raw.get("comments", [])

    title = post.get("title", "")
    selftext = post.get("selftext", "") or ""
    author = post.get("author", "[deleted]")
    score = post.get("score", 0)
    num_comments = post.get("num_comments", 0)
    subreddit = post.get("subreddit", "")

    # Parse top-level comments
    comment_lines = []
    for c in comments:
        if c.get("kind") == "t1":
            body = c["data"].get("body", "").strip()
            c_author = c["data"].get("author", "[deleted]")
            c_score = c["data"].get("score", 0)
            if body:
                comment_lines.append(f"[{c_author}] ({c_score} pts): {body}")

    # Check if deleted
    post_is_deleted = (
        author == "[deleted]"
        and (not selftext.strip() or "[removed]" in selftext)
        and len([c for c in comments if c.get("kind") == "t1" and c["data"].get("body", "").strip()]) == 0
    )
    if post_is_deleted:
        return {"title": title, "content": None, "status": "reddit_deleted"}

    # Build content
    parts = [f"# {title}"]
    parts.append(f"**r/{subreddit}** — by u/{author} — ▲{score} — {num_comments} comments")

    if selftext:
        parts.append("")
        parts.append(selftext)

    if comment_lines:
        parts.append("")
        parts.append(f"---\n**Comments ({len(comment_lines)}):**")
        parts.append("")
        parts.extend(comment_lines)

    content = "\n".join(parts)[:50000]

    if len(content) > 100:
        return {"title": title, "content": content, "status": f"reddit_json_{len(comment_lines)}comments"}
    else:
        return {"title": title, "content": None, "status": "reddit_empty"}
