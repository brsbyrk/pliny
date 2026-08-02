#!/usr/bin/env python3
"""url_ingest.py — Thin orchestrator for the extractor pipeline.

Classifies a URL, loads the appropriate extractor module (ingest.x,
ingest.github, etc.), runs fetch() → clean → format(), and ingests
the result into Pliny's database.

Usage:
    python3 src/ingest/url_ingest.py https://x.com/user/status/123
    python3 src/ingest/url_ingest.py https://example.com/article
    python3 src/ingest/url_ingest.py --id my-custom-slug https://...
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import requests

# Make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.cleaners import strip_html_tags
from lib.paths import DB_PATH
from lib.schema import get_db

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Pliny/0.1"
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extractor module registry
# ---------------------------------------------------------------------------

EXTRACTOR_MODULES = {
    "x": "ingest.x",
    "github": "ingest.github",
    "youtube": "ingest.youtube",
    "reddit": "ingest.reddit",
    "web": "ingest.web",
}


# ---------------------------------------------------------------------------
# URL classification
# ---------------------------------------------------------------------------


def classify_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "x.com" in host or "twitter.com" in host:
        return "x"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if "github.com" in host:
        return "github"
    if "reddit.com" in host:
        return "reddit"
    return "web"


def entry_type_for_url(url: str, content_len: int, extraction_status: str = "") -> str:
    """Determine entry_type based on source URL and content length."""
    cls = classify_url(url)
    if cls == "x":
        if "article" in extraction_status:
            return "x_article"
        return "x_observation" if content_len < 200 else "x_thread"
    return cls  # youtube, github, reddit, web → 'bookmark'


# ---------------------------------------------------------------------------
# Internal extraction helper
# ---------------------------------------------------------------------------


def _run_extractor(kind: str, url: str, **extra_kwargs) -> dict:
    """Load the extractor module for *kind* and run fetch → format.

    Applies strip_html_tags() from lib.cleaners on the formatted content
    so ALL extractors get uniform HTML stripping.
    """
    mod_name = EXTRACTOR_MODULES[kind]
    mod = importlib.import_module(mod_name)

    try:
        raw = mod.fetch(url, **extra_kwargs)
    except TypeError:
        # Module's fetch() doesn't accept extra kwargs; try without
        raw = mod.fetch(url)

    if raw is None:
        return {"title": None, "content": None, "status": f"{kind}_unavailable"}
    if raw.get("_error"):
        # Let format() translate the error into a proper status
        pass

    result = mod.format(raw, url)

    # Apply shared cleaners uniformly
    if result.get("content"):
        result["content"] = strip_html_tags(result["content"])

    return result


# ---------------------------------------------------------------------------
# Backward-compatible extractor wrappers
# ---------------------------------------------------------------------------

# These preserve the exact function signatures used by external importers
# (reprocess.py, batch_yt_reextract.py, enrich.py, extract_cron.py, etc.)


def extract_x(url: str) -> dict:
    return _run_extractor("x", url)


def extract_github(url: str) -> dict:
    return _run_extractor("github", url)


def extract_youtube(url: str) -> dict:
    return _run_extractor("youtube", url)


def extract_reddit(url: str, canonical_url: str | None = None) -> dict:
    return _run_extractor("reddit", url, canonical_url=canonical_url)


def extract_web(url: str, timeout: int = 30) -> dict:
    return _run_extractor("web", url, timeout=timeout)


EXTRACTORS = {
    "x": extract_x,
    "github": extract_github,
    "youtube": extract_youtube,
    "reddit": extract_reddit,
    "web": extract_web,
}

# Re-export for batch_yt_reextract.py
from ingest.youtube import _extract_video_id  # noqa: E402, F401

# ---------------------------------------------------------------------------
# Social-domain blocklist for linked-content resolution
# ---------------------------------------------------------------------------

SOCIAL_DOMAINS: set[str] = {
    "x.com", "twitter.com", "reddit.com", "youtube.com",
    "youtu.be", "instagram.com", "facebook.com", "tiktok.com",
    "twitch.tv",
}

# Regex for finding HTTP(S) URLs in text (see resolve_linked_content)
_URL_RE = re.compile(r'https?://[^\s<>"\'\)\]}]+')

# Punctuation to strip from the end of a matched URL
_TRAILING_PUNCTUATION = ".,;:!?)\"'＞"


def resolve_linked_content(text: str, source_url: str) -> str | None:
    """One-level URL resolver.

    Finds HTTP(S) URLs in *text*, extracts their content using the same
    EXTRACTORS / classify_url machinery, and appends the linked content
    to the original text with a ``---`` separator.

    Social domains and self-references are skipped.  At most 3 links are
    followed.  Results with <= 100 chars of content are discarded.

    Returns the combined text when at least one link resolved, or None
    when no links with substantial content were found.
    """
    # 1. Find all HTTPS? URLs
    raw_urls = _URL_RE.findall(text)

    # 2. Strip trailing punctuation
    stripped = [u.rstrip(_TRAILING_PUNCTUATION) for u in raw_urls]

    # 3. Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for u in stripped:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    # 4. Filter: skip self-reference + social domains, cap at 3
    candidates: list[str] = []
    for u in unique:
        if u == source_url:
            continue  # self-reference

        parsed = urlparse(u)
        host = parsed.netloc.lower()

        # Exact match or subdomain match against social domains
        parts = host.split(".")
        base = ".".join(parts[-2:]) if len(parts) >= 2 else host
        if base in SOCIAL_DOMAINS or host in SOCIAL_DOMAINS:
            continue

        candidates.append(u)
        if len(candidates) >= 3:
            break

    if not candidates:
        return None

    # 5. Extract content for each candidate (max 3)
    results: list[dict[str, str]] = []
    for u in candidates:
        try:
            kind = classify_url(u)
            extracted = EXTRACTORS[kind](u)
            c = extracted.get("content")
            if c and len(c) > 100:
                results.append({
                    "title": extracted.get("title") or u,
                    "url": u,
                    "content": c,
                })
        except Exception:
            continue

    if not results:
        return None

    # 6. Build combined text
    parts = [text]
    for r in results:
        block = (
            f"Linked: {r['title']}\n"
            f"Source: {r['url']}\n\n"
            f"{r['content']}"
        )
        parts.append(block)

    return "\n\n---\n\n".join(parts)


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:64]


# ---------------------------------------------------------------------------
# Main ingestion function (unchanged external signature)
# ---------------------------------------------------------------------------


def ingest_url(url: str, entry_id: str | None = None, db: sqlite3.Connection | None = None) -> str | None:
    """Extract content from *url* and store it in Pliny's database.

    Returns the entry ID on success, None on failure.

    External callers (ingest_cli.py, karakeep_import.py, sync.py) rely on
    this function signature — do not change it.
    """
    # Resolve t.co redirects so X/Twitter links shared via t.co are classified correctly
    parsed = urlparse(url)
    if "t.co" in parsed.netloc.lower():
        try:
            resp = requests.head(url, allow_redirects=True, timeout=10,
                                 headers={"User-Agent": USER_AGENT})
            url = resp.url
        except Exception as e:
            logger.debug("t.co resolve failed for %s: %s", url, e)

    kind = classify_url(url)
    result = _run_extractor(kind, url)
    title = result.get("title") or url
    content = result.get("content")

    # Reject dead/unavailable sources
    status = result.get("status", "")
    dead_statuses = {"reddit_deleted", "reddit_resolve_failed",
                     "github_not_found", "github_empty", "github_invalid_url",
                     "youtube_unavailable", "youtube_no_id",
                     "web_dead", "web_blocked", "web_connection_error",
                     "x_api_failed", "x_article_unsupported"}
    if status in dead_statuses or "http_404" in status:
        print(f"X Source dead/unavailable: {url} ({status})")
        return None

    if not content:
        print(f"X No content extracted from {url} ({status})")
        return None

    if status.startswith("error"):
        print(f"X Extraction failed: {status}")
        return None

    # One-level linked-content resolution: find URLs in extracted text,
    # extract their content, and append it before enrichment.
    linked = resolve_linked_content(content, url)
    if linked is not None:
        content = linked

    if not entry_id:
        entry_id = _slugify(title)
        if not entry_id:
            entry_id = hashlib.md5(url.encode()).hexdigest()[:12]

    close_db = False
    if db is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        db = get_db(DB_PATH)
        close_db = True

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    content_len = len(content)
    etype = entry_type_for_url(url, content_len, result.get("status", ""))
    estatus = "extracted" if content_len >= 200 else ("thin" if content_len >= 50 else "pending")

    db.execute(
        """INSERT INTO entries (id, source_url, title, content, entry_type, extraction_status, retry_count, created_at, modified_at)
           VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               source_url = excluded.source_url,
               title = excluded.title,
               content = excluded.content,
               entry_type = excluded.entry_type,
               extraction_status = excluded.extraction_status,
               modified_at = excluded.modified_at""",
        (entry_id, url, title, content, etype, estatus, now, now),
    )
    rowid = db.execute("SELECT rowid FROM entries WHERE id = ?", (entry_id,)).fetchone()[0]
    from lib.embed import embed_json
    vec = embed_json(title + "\n\n" + content)
    db.execute("DELETE FROM entries_v0 WHERE rowid = ?", (rowid,))
    db.execute("INSERT INTO entries_v0 (rowid, embedding) VALUES (?, ?)", (rowid, vec))
    db.commit()

    # Auto-tag via c-TF-IDF centroid matching (non-blocking if centroids don't exist)
    try:
        from cli.auto_tag import predict_tags
        tags = predict_tags(title, content)
        if tags:
            db.execute("UPDATE entries SET tags = ? WHERE id = ?",
                       (json.dumps(tags), entry_id))
            db.commit()
    except Exception as e:
        logger.debug("auto-tagging failed: %s", e)

    # Push URL entries to Karakeep (non-critical — ignore errors)
    try:
        from cli.sync import push_to_karakeep
        push_to_karakeep(url, title=title)
    except Exception as e:
        logger.debug("karakeep sync failed: %s", e)

    if close_db:
        db.close()
    return entry_id


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract URL and ingest into Pliny")
    parser.add_argument("url", help="URL to ingest")
    parser.add_argument("--id", help="Custom entry slug (auto-generated if omitted)")
    args = parser.parse_args()

    eid = ingest_url(args.url, args.id)
    if eid:
        print(f"V Ingested: {eid}")
    else:
        sys.exit(1)
