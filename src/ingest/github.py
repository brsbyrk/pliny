"""GitHub repo extractor — fetch + format for README or API description."""

from __future__ import annotations

import logging

import requests
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def fetch(url: str) -> dict | None:
    """Fetch raw GitHub repo metadata.

    Tries raw README (main → master), then API for description.
    Returns a dict with repo info (even for errors, so format() can
    produce proper status strings), or None on unrecoverable error.
    """
    try:
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2:
            return {"_error": "invalid_url"}
        owner, repo = parts[0], parts[1]

        result: dict = {"owner": owner, "repo": repo}

        # Try raw README
        readme_url = f"https://raw.githubusercontent.com/{owner}/{repo}/main/README.md"
        resp = requests.get(readme_url, timeout=15)
        if resp.status_code != 200:
            readme_url = f"https://raw.githubusercontent.com/{owner}/{repo}/master/README.md"
            resp = requests.get(readme_url, timeout=15)

        if resp.status_code == 200:
            result["readme"] = resp.text[:50000]
            result["_fetch_source"] = "readme"
            return result

        # Fallback: API
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        resp = requests.get(api_url, timeout=15, headers={"Accept": "application/vnd.github.v3+json"})
        if resp.status_code == 200:
            data = resp.json()
            result["full_name"] = data.get("full_name", f"{owner}/{repo}")
            result["description"] = data.get("description", "") or ""
            result["_fetch_source"] = "api"
            return result

        # API returned error — repo might be deleted/private
        result["_fetch_source"] = f"http_{resp.status_code}" if resp.status_code != 404 else "not_found"
        return result

    except Exception as e:
        return {"_error": str(e)}


def format(raw: dict, url: str) -> dict:
    """Convert raw GitHub data into standard {title, content, status} shape."""
    # Handle error/invalid cases
    error = raw.get("_error")
    if error == "invalid_url":
        return {"title": None, "content": None, "status": "github_invalid_url"}
    if error is not None:
        return {"title": None, "content": None, "status": f"github_error: {error}"}

    owner = raw.get("owner", "")
    repo = raw.get("repo", "")
    title = f"{owner}/{repo}" if owner and repo else url

    source = raw.get("_fetch_source", "")

    if source == "readme":
        content = raw.get("readme", "")
        return {"title": title, "content": content, "status": "github_readme"}

    if source == "api":
        title = raw.get("full_name", title)
        content = raw.get("description", "")
        if content:
            return {"title": title, "content": content, "status": "github_api"}
        else:
            return {"title": title, "content": None, "status": "github_empty"}

    if source == "not_found":
        return {"title": title, "content": None, "status": "github_not_found"}

    if source.startswith("http_"):
        return {"title": title, "content": None, "status": f"github_{source}"}

    return {"title": title, "content": None, "status": "github_invalid_url"}
