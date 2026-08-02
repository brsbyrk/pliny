"""sdk.py — Pliny client SDK for AI agents.

Lightweight HTTP client for agents to search Pliny's corpus.
No direct SQLite access — everything goes through the HTTP API.

Usage:
    from sdk import Pliny

    p = Pliny(agent="sherlock")

    # Search
    results = p.search(q="machine learning", tags=["ai"], limit=20)
    for entry in results:
        print(f"{entry['title']}: {entry['summary']}")
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class Pliny:
    """HTTP client for Pliny's agent API.

    Parameters
    ----------
    base_url : str
        Pliny server URL (default: http://localhost:3131).
    agent : str
        Agent identifier used for subscriptions and notifications.
        Set once, used for all calls unless overridden.
    timeout : int
        HTTP request timeout in seconds (default: 10).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:3131",
        agent: str | None = None,
        timeout: int = 10,
    ):
        self.base_url = base_url.rstrip("/")
        self.agent = agent
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        data: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Make an HTTP request to Pliny and return the JSON response."""
        url = f"{self.base_url}{path}"

        if params:
            qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items() if v)
            url = f"{url}?{qs}"

        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(
            url,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"} if body else {},
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            raise Exception(
                f"Pliny HTTP {e.code} on {method} {path}: {error_body}"
            ) from e
        except urllib.error.URLError as e:
            raise Exception(
                f"Pliny connection failed on {method} {path}: {e.reason}"
            ) from e

    def search(
        self,
        q: str = "",
        tags: list[str] | None = None,
        entry_type: str = "",
        limit: int = 30,
    ) -> dict:
        """Search Pliny's corpus.

        Returns a dict with 'entries' (list of entry dicts), 'total', 'page',
        and 'per_page'.
        """
        params = {}
        if q:
            params["q"] = q
        if tags:
            params["tags"] = ",".join(tags)
        if entry_type:
            params["entry_type"] = entry_type
        params["per_page"] = limit

        return self._request("GET", "/api/entries", params=params)
