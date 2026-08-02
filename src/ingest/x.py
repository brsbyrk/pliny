"""X/Twitter extractor — fetch + format for tweets, threads, and articles."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from pathlib import Path

import requests
from dotenv import load_dotenv

from lib.paths import MEDIA_DIR

logger = logging.getLogger(__name__)
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Pliny/0.1"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_tweet_id(url: str) -> str | None:
    """Extract numeric tweet/post ID from an X/Twitter URL."""
    m = re.search(r"(?:status/|statuses/|^)(\d{12,25})(?:\D|$)", url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Fetch: raw data from external APIs
# ---------------------------------------------------------------------------


_X_API_ENDPOINTS = {
    "tweets": "https://api.twitter.com/2/tweets",
    "users": "https://api.twitter.com/2/users",
}
_X_TWEET_FIELDS = "author_id,created_at,text,attachments,public_metrics,article,note_tweet,conversation_id"
_X_EXPANSIONS = "attachments.media_keys,author_id"
_X_MEDIA_FIELDS = "url,type,width,height,alt_text"
_X_USER_FIELDS = "name,username,profile_image_url"


def _fetch_x_via_fxtwitter(post_id: str) -> dict | None:
    """Fetch tweet data via fxtwitter API. Falls back to vxtwitter."""
    endpoints = [
        f"https://api.fxtwitter.com/status/{post_id}",
        f"https://api.vxtwitter.com/Twitter/status/{post_id}",
    ]
    for url in endpoints:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            code = data.get("code") or data.get("status_code")
            if code and code != 200:
                continue
            if data.get("tweet") or data.get("text"):
                return data
        except Exception as e:
            logger.debug("fxtwitter API error for %s: %s", post_id, e)
            continue
    return None


def _fetch_x_via_api_v2(post_id: str) -> dict | None:
    """Fetch tweet data via official X API v2 using Bearer Token.

    Returns a dict with the same shape as fxtwitter for compatibility:
        {"tweet": {"text": ..., "author": {"name": ..., "screen_name": ...}, "media": {"all": [...]}}, "thread": [...]}
    Returns None if Bearer Token not configured or request fails.
    """
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
    bearer_key = os.getenv("X_BEARER_KEY")
    if not bearer_key:
        return None

    headers = {"Authorization": f"Bearer {bearer_key}"}

    params = {
        "ids": post_id,
        "tweet.fields": _X_TWEET_FIELDS,
        "expansions": _X_EXPANSIONS,
        "media.fields": _X_MEDIA_FIELDS,
        "user.fields": _X_USER_FIELDS,
    }
    try:
        r = requests.get(_X_API_ENDPOINTS["tweets"], params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception as e:
        logger.debug("X API v2 request failed for %s: %s", post_id, e)
        return None

    tweets_data = data.get("data", [])
    if not tweets_data:
        return None

    tweet = tweets_data[0]
    includes = data.get("includes", {})
    users_map = {u["id"]: u for u in includes.get("users", [])}
    media_map = {m["media_key"]: m for m in includes.get("media", [])}

    author = users_map.get(tweet.get("author_id", ""), {})
    author_name = author.get("name", "Unknown")
    author_handle = author.get("username", "")

    media_keys = (tweet.get("attachments") or {}).get("media_keys", [])
    photos = []
    for mk in media_keys:
        m = media_map.get(mk)
        if m and m.get("type") == "photo":
            photos.append({"url": m["url"]})
    other_media = []
    for mk in media_keys:
        m = media_map.get(mk)
        if m and m.get("type") in ("video", "animated_gif"):
            other_media.append(m)

    metrics = tweet.get("public_metrics", {})

    conv_id = tweet.get("conversation_id")
    thread_tweets = []
    if conv_id and conv_id != tweet.get("id"):
        try:
            conv_params = {
                "query": f"conversation_id:{conv_id} from:{author_handle}",
                "max_results": 20,
                "tweet.fields": _X_TWEET_FIELDS,
                "expansions": _X_EXPANSIONS,
                "media.fields": _X_MEDIA_FIELDS,
                "user.fields": _X_USER_FIELDS,
            }
            cr = requests.get(
                f"{_X_API_ENDPOINTS['tweets']}/search/recent",
                params=conv_params,
                headers=headers,
                timeout=15,
            )
            if cr.status_code == 200:
                conv_data = cr.json()
                conv_includes = conv_data.get("includes", {})
                for m in conv_includes.get("media", []):
                    media_map[m["media_key"]] = m
                for u in conv_includes.get("users", []):
                    users_map[u["id"]] = u
                thread_tweets = sorted(conv_data.get("data", []), key=lambda t: t.get("created_at", ""))
        except Exception as e:
            logger.debug("X API v2 thread lookup failed for %s: %s", post_id, e)
            pass

    if not thread_tweets:
        thread_tweets = [tweet]

    nested_tweet = {
        "text": tweet.get("text", ""),
        "author": {"name": author_name, "screen_name": author_handle},
        "media": {"all": photos + other_media, "photos": photos},
        "public_metrics": metrics,
    }
    if "article" in tweet:
        nested_tweet["article"] = tweet["article"]
    if "note_tweet" in tweet:
        nested_tweet["note_tweet"] = tweet["note_tweet"]

    result = {"tweet": nested_tweet}

    if len(thread_tweets) > 1:
        thread_result = []
        for t in thread_tweets:
            tm = users_map.get(t.get("author_id", ""), {})
            t_media_keys = (t.get("attachments") or {}).get("media_keys", [])
            t_photos = []
            for mk in t_media_keys:
                m = media_map.get(mk)
                if m and m.get("type") == "photo":
                    t_photos.append({"url": m["url"]})
            thread_result.append(
                {
                    "tweet": {
                        "text": t.get("text", ""),
                        "author": {"name": tm.get("name", author_name), "screen_name": tm.get("username", author_handle)},
                        "media": {"all": t_photos},
                    }
                }
            )
        result["thread"] = thread_result

    return result


def fetch(url: str) -> dict | None:
    """Fetch raw X/Twitter data.

    Returns a dict with fxtwitter-compatible shape, or None if the source
    is unreachable. Handles API v2 → fxtwitter fallback chain.

    For /i/article/ URLs returns a special dict so format() can return
    the unsupported message.
    """
    # X article URLs cannot be resolved via the API
    if "/i/article/" in url:
        return {
            "_article_unsupported": True,
        }

    post_id = _extract_tweet_id(url)
    if not post_id:
        return None

    # Try official X API v2 first
    api_data = _fetch_x_via_api_v2(post_id)
    if api_data:
        api_data["_source"] = "api_v2"
        return api_data

    # Fallback to fxtwitter
    data = _fetch_x_via_fxtwitter(post_id)
    if data:
        data["_source"] = "fxtwitter"
        return data

    return None


# ---------------------------------------------------------------------------
# Format: raw data → standard shape
# ---------------------------------------------------------------------------


def _format_x_from_api(api_data: dict) -> dict:
    """Format API v2 response into standard shape."""
    tweet = api_data["tweet"]
    author = tweet.get("author", {})
    author_name = author.get("name", "Unknown")
    author_handle = author.get("screen_name", "")
    handle_str = f" (@{author_handle})" if author_handle else ""

    # Check for article field
    article = tweet.get("article")
    if article and article.get("plain_text"):
        article_text = article["plain_text"]
        article_title = article.get("title", "")
        preview = article_text.replace("\n", " ")[:80].strip()

        if article_title:
            title = f"{author_name}{handle_str}: {article_title}"
        else:
            title = f"{author_name}{handle_str}: {preview}"

        content = f"{author_name}{handle_str} [Article]:\n{article_title}\n\n{article_text}"

        media = tweet.get("media") or {}
        photos = media.get("all") or []
        if photos:
            photo_notes = "\n\n---\nImages:\n"
            for i, p in enumerate(photos, 1):
                url = p.get("url", "")
                photo_notes += f"\n[📷 Image {i}/{len(photos)}] {url}"
            content += photo_notes

        return {"title": title, "content": content, "status": "x_v2_article"}

    # Regular tweet
    text = tweet.get("text", "")
    thread = api_data.get("thread", [])
    preview = text.replace("\n", " ")[:80].strip()
    title = f"{author_name}{handle_str}: {preview}"

    if thread:
        lines = []
        for i, item in enumerate(thread):
            t = item.get("tweet", item)
            name = t.get("author", {}).get("name", author_name)
            handle_raw = t.get("author", {}).get("screen_name", "")
            t_text = t.get("text", "")
            prefix = f"{name} (@{handle_raw}):" if handle_raw else f"{name}:"
            tweet_content = f"{prefix}\n{t_text}"
            media = t.get("media") or {}
            photos = media.get("all") or []
            for p in photos:
                url = p.get("url", "")
                tweet_content += f"\n[📷] {url}"
            lines.append(tweet_content)
        content = "\n\n---\n\n".join(lines)
        status = f"x_v2_{len(thread):d}tweets"
    else:
        handle_prefix = f" (@{author_handle})" if author_handle else ""
        content_text = f"{author_name}{handle_prefix}:\n{text}"
        media = tweet.get("media") or {}
        photos = media.get("all") or []
        if photos:
            photo_notes = "\n"
            for i, p in enumerate(photos, 1):
                url = p.get("url", "")
                photo_notes += f"\n[📷 Image {i}/{len(photos)}] {url}"
            content_text += photo_notes
        content = content_text
        status = "x_v2_1tweet"

    return {"title": title, "content": content, "status": status}


def _format_x_from_fxtwitter(data: dict) -> dict:
    """Format fxtwitter response into standard shape."""
    tweet = data.get("tweet") or data
    if not isinstance(tweet, dict) or ("text" not in tweet and "content" not in tweet):
        return {"title": None, "content": None, "status": "x_fxtwitter_no_text"}

    text = tweet.get("text") or tweet.get("content") or ""
    if not text.strip():
        return {"title": None, "content": None, "status": "x_no_text"}

    author = tweet.get("author") or tweet.get("user") or {}
    author_name = author.get("name", "Unknown")
    author_handle = author.get("screen_name", author.get("username", ""))

    preview = text.replace("\n", " ")[:80].strip()
    handle_str = f" (@{author_handle})" if author_handle else ""
    title = f"{author_name}{handle_str}: {preview}"

    thread = data.get("thread", [])
    if thread:
        lines = []
        for i, item in enumerate(thread):
            t = item.get("tweet", item)
            name = t.get("author", {}).get("name", author_name)
            handle_raw = t.get("author", {}).get("screen_name", "")
            t_text = t.get("text", "")
            prefix = f"{name} (@{handle_raw}):" if handle_raw else f"{name}:"
            tweet_content = f"{prefix}\n{t_text}"
            media = t.get("media") or {}
            photos = media.get("photos") or media.get("all") or []
            for p in photos:
                url = p.get("url", "")
                tweet_content += f"\n[📷] {url}"
            lines.append(tweet_content)
        content = "\n\n---\n\n".join(lines)
        status = f"x_fxtwitter_{len(thread):d}tweets"
    else:
        handle_prefix = f" (@{author_handle})" if author_handle else ""
        content_text = f"{author_name}{handle_prefix}:\n{text}"
        media = tweet.get("media") or {}
        photos = media.get("photos") or media.get("all") or []
        if photos:
            photo_notes = "\n"
            for i, p in enumerate(photos, 1):
                url = p.get("url", "")
                photo_notes += f"\n[📷 Image {i}/{len(photos)}] {url}"
            content_text += photo_notes
        content = content_text
        status = "x_fxtwitter_1tweet"

    return {"title": title, "content": content, "status": status}


def format(raw: dict, url: str) -> dict:
    """Convert raw X data into standard {title, content, status} shape."""
    # Handle article unsupported
    if raw.get("_article_unsupported"):
        return {
            "title": "X Article",
            "content": (
                "X articles cannot be extracted directly from the /i/article/ URL. "
                "Please save the tweet URL instead (the tweet that links to the article). "
                "The tweet URL format is: https://x.com/{username}/status/{tweet_id}"
            ),
            "status": "x_article_unsupported",
        }

    source = raw.get("_source", "fxtwitter")

    if source == "api_v2":
        return _format_x_from_api(raw)
    else:
        return _format_x_from_fxtwitter(raw)
