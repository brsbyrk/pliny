"""Shared text cleaners for the extraction pipeline."""

from __future__ import annotations

import html
import re


def strip_html_tags(text: str) -> str:
    """Remove HTML tags, decode entities, collapse multi-newlines."""
    if not text:
        return text
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate(text: str, max_chars: int = 50000) -> str:
    """Truncate to max_chars, preserving line boundaries."""
    if not text or len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit("\n", 1)[0] if "\n" in text[:max_chars] else text[:max_chars]


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces/tabs to single space."""
    if not text:
        return text
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
