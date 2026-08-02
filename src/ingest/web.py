"""General web page extractor — fetch + format for any HTML page."""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Pliny/0.1"

try:
    from readability import Document as ReadabilityDoc
    HAS_READABILITY = True
except ImportError:
    HAS_READABILITY = False

try:
    import markdownify
    HAS_MARKDOWNIFY = True
except ImportError:
    HAS_MARKDOWNIFY = False


# ---------------------------------------------------------------------------
# Fallback HTML text parser
# ---------------------------------------------------------------------------


class _TextOnlyParser(HTMLParser):
    """HTML tag stripper that adds newlines around block-level elements
    and skips script/style content. Used as fallback when readability
    is unavailable or fails."""

    def __init__(self):
        super().__init__()
        self._text = []
        self._skip = False
        self._skip_tags = {"script", "style", "nav", "footer", "header", "aside", "noscript", "svg", "form", "button"}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True
        if tag in ("br", "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "th", "td"):
            self._text.append("\n")

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data)

    def get_text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self._text)).strip()


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch(url: str, timeout: int = 30) -> dict | None:
    """Fetch raw HTML from a URL.

    Returns a dict with 'html', 'status_code' on success.
    Returns a dict with '_error' on HTTP/network failures.
    Returns None on unrecoverable errors.
    """
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
        return {"html": resp.text, "status_code": resp.status_code}
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        if status in (404, 410):
            return {"_error": "dead"}
        elif status in (403,):
            return {"_error": "blocked"}
        else:
            return {"_error": f"http_{status}"}
    except requests.exceptions.ConnectionError:
        return {"_error": "connection_error"}
    except requests.exceptions.Timeout:
        return {"_error": "timeout"}
    except Exception as e:
        return {"_error": str(e)}


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


def format(raw: dict, url: str) -> dict:
    """Convert raw HTML into standard {title, content, status} shape.

    Uses readability → markdownify as primary path, falls back to
    _TextOnlyParser for plain text extraction.
    """
    # Handle errors
    error = raw.get("_error")
    if error:
        status_map = {
            "dead": "web_dead",
            "blocked": "web_blocked",
            "connection_error": "web_connection_error",
            "timeout": "web_timeout",
        }
        status = status_map.get(error, f"web_error: {error}")
        return {"title": None, "content": None, "status": status}

    html = raw.get("html", "")
    status_code = raw.get("status_code", 200)
    status_base = f"http_{status_code}"

    # Primary: readability → markdownify
    if HAS_READABILITY:
        try:
            doc = ReadabilityDoc(html)
            title = doc.title()
            content_html = doc.summary()
            if HAS_MARKDOWNIFY:
                content = markdownify.markdownify(content_html, heading_style="ATX")
            else:
                content = content_html
            return {"title": title, "content": content.strip(), "status": "readability"}
        except Exception as e:
            logger.debug("readability extraction failed for %s: %s", url, e)

    # Fallback: _TextOnlyParser
    parser = _TextOnlyParser()
    parser.feed(html)
    text = parser.get_text()

    # Extract title from <title> tag
    title = url
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        title = m.group(1).strip()

    return {"title": title, "content": text[:50000], "status": "stdlib"}
