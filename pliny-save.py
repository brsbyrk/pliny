#!/usr/bin/env python3
"""pliny-save — Extract a URL and save as markdown into Obsidian vault.

Usage:
    python3 pliny-save.py https://x.com/user/status/123

    python3 pliny-save.py https://github.com/user/repo --vault ~/vault/BBB/00-Projects/pliny-inbox/

Creates a .md file in the vault directory. Directory is created if needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Ensure src/ is importable
SRC_DIR = str(Path(__file__).resolve().parent / "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from lib.cleaners import strip_html_tags
from ingest.url_ingest import classify_url, EXTRACTORS

# Default vault path
DEFAULT_VAULT = os.path.expanduser("~/vault/BBB/00-Projects/pliny-inbox")


def slugify(text: str, maxlen: int = 48) -> str:
    """Generate a filesystem-safe slug from text."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:maxlen] or "untitled"


def extract(url: str) -> dict | None:
    """Extract content from a URL using Pliny's extraction engine."""
    kind = classify_url(url)
    try:
        result = EXTRACTORS[kind](url)
    except KeyError:
        logger.error(f"Unknown URL type: {kind}")
        return None
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return None

    status = result.get("status", "")
    content = result.get("content")
    title = result.get("title") or url

    # Apply shared cleaning
    if content:
        content = strip_html_tags(content)

    # Reject dead/unavailable
    dead_statuses = {
        "reddit_deleted", "reddit_resolve_failed",
        "github_not_found", "github_empty", "github_invalid_url",
        "youtube_unavailable", "youtube_no_id",
        "web_dead", "web_blocked", "web_connection_error",
        "x_api_failed", "x_article_unsupported",
    }
    if status in dead_statuses or "http_404" in status:
        logger.warning(f"  Source dead/unavailable: {url} ({status})")
        return None

    if not content:
        logger.warning(f"  No content extracted: {url} ({status})")
        return None

    return {"title": title, "content": content, "status": status, "kind": kind, "url": url}


def format_frontmatter(title: str, url: str, kind: str, status: str, tags: list[str] | None = None) -> str:
    """Build YAML frontmatter for Obsidian markdown."""
    lines = ["---"]
    lines.append(f'title: "{title.replace(chr(34), chr(39))}"')
    lines.append(f"source: {url}")
    lines.append(f"source_type: {kind}")
    lines.append(f"extraction_status: {status}")
    lines.append(f"created: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    if tags:
        lines.append(f"tags: [{', '.join(tags)}]")
    lines.append("---")
    return "\n".join(lines)


def save_to_vault(result: dict, vault_dir: Path, entry_id: str | None = None) -> Path:
    """Write extracted content as a markdown file into the vault directory."""
    vault_dir.mkdir(parents=True, exist_ok=True)

    title = result["title"]
    url = result["url"]
    kind = result["kind"]
    status = result["status"]
    content = result["content"]

    # Generate a unique filename
    if not entry_id:
        entry_id = slugify(title)
        if not entry_id:
            entry_id = hashlib.md5(url.encode()).hexdigest()[:12]

    # Ensure no collision
    outpath = vault_dir / f"{entry_id}.md"
    counter = 1
    while outpath.exists():
        outpath = vault_dir / f"{entry_id}-{counter}.md"
        counter += 1

    # Build markdown
    frontmatter = format_frontmatter(title, url, kind, status)
    md = f"{frontmatter}\n\n# {title}\n\n{content}\n\n---\n*Saved from: {url}*"

    outpath.write_text(md, encoding="utf-8")
    return outpath


def resolve_linked(url: str) -> str | None:
    """Try to resolve linked content for a single URL (one level deep)."""
    kind = classify_url(url)
    if kind == "x":
        return None  # Skip social
    try:
        result = EXTRACTORS[kind](url)
        if result and result.get("content") and len(result["content"]) > 100:
            content = strip_html_tags(result["content"])
            title = result.get("title") or url
            return f"\n\n---\n**Linked:** {title}\n**Source:** {url}\n\n{content}"
    except Exception:
        pass
    return None


# ── Tiny HTTP listener (for browser extension) ─────────────────────
# Runs a minimal HTTP server that accepts POST /api/ingest/add-url
# with {"url": "..."} and saves to the vault as .md.


def _start_listener(vault_dir: Path, host: str = "0.0.0.0", port: int = 3131) -> None:
    """Start a minimal HTTP server that accepts URL saves."""
    import http.server
    import json as json_mod

    class SaveHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/api/ingest/add-url":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            try:
                data = json_mod.loads(body)
                url = data.get("url", "").strip()
            except Exception:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json_mod.dumps({"error": "bad json"}).encode())
                return
            if not url:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json_mod.dumps({"error": "url required"}).encode())
                return

            result = extract(url)
            if result:
                outpath = save_to_vault(result, vault_dir)
                clen = len(result["content"])
                logger.info(f"  → Saved: {outpath.name} ({clen}c)")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json_mod.dumps({
                    "status": "ingested",
                    "entry_id": outpath.stem,
                    "url": url,
                }).encode())
            else:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json_mod.dumps({"error": "extraction failed",
                                                  "url": url}).encode())

        def log_message(self, format, *args):
            logger.info(f"  [HTTP] {args[0]} {args[1]}")

    server = http.server.HTTPServer((host, port), SaveHandler)
    logger.info(f"Listening on http://{host}:{port}")
    logger.info(f"Saving to: {vault_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("\nShutting down.")
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Extract a URL and save to Obsidian vault")
    parser.add_argument("url", nargs="?", help="URL to extract")
    parser.add_argument("--vault", default=DEFAULT_VAULT,
                        help=f"Obsidian vault directory (default: {DEFAULT_VAULT})")
    parser.add_argument("--target", choices=["auto", "x", "github", "youtube", "reddit", "web"],
                        default="auto", help="Force extraction type")
    parser.add_argument("--id", help="Custom entry slug for the filename")
    parser.add_argument("--follow-links", action="store_true",
                        help="Follow links in the content one level deep")
    parser.add_argument("--stdout", action="store_true",
                        help="Print markdown to stdout instead of saving to file")
    parser.add_argument("--listen", action="store_true",
                        help="Run as HTTP server for browser extension")
    parser.add_argument("--port", type=int, default=3131,
                        help="HTTP server port (default: 3131)")
    args = parser.parse_args()

    vault_dir = Path(args.vault)

    if args.listen:
        _start_listener(vault_dir, port=args.port)
        return

    if not args.url:
        parser.print_help()
        sys.exit(1)

    # Extract
    logger.info(f"Extracting: {args.url}")
    result = extract(args.url)
    if not result:
        sys.exit(1)

    # Optionally follow links in content
    if args.follow_links:
        from ingest.url_ingest import _URL_RE
        urls = re.findall(_URL_RE, result["content"])
        linked = []
        for link_url in urls[:3]:
            link_url = link_url.rstrip(".,;:!?)>\"'")
            if link_url == args.url:
                continue
            logger.info(f"  Following link: {link_url}")
            lr = resolve_linked(link_url)
            if lr:
                linked.append(lr)
        if linked:
            result["content"] += "".join(linked)
            result["status"] = f"{result['status']}_with_linked"

    # Save or print
    if args.stdout:
        title = result["title"]
        content = result["content"]
        kind = result["kind"]
        status = result["status"]
        frontmatter = format_frontmatter(title, args.url, kind, status)
        print(f"{frontmatter}\n\n# {title}\n\n{content}")
        return

    outpath = save_to_vault(result, Path(args.vault), args.id)
    clen = len(result["content"])
    print(f"✓ Saved: {outpath} ({clen} chars) [{result['status']}]")


if __name__ == "__main__":
    main()
