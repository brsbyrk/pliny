#!/usr/bin/env python3
"""digest.py — Weekly knowledge digest for Pliny.

Queries the last 7 days of saved entries, clusters them by tags,
and produces a synthesized markdown summary using DeepSeek.

Usage:
    .venv/bin/python src/digest.py [--days N] [--min-entries N]

Outputs markdown to stdout for cron job delivery.
"""
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # resolves to project root
DB_PATH = ROOT / "data" / "pliny.db"

# ── LLM Config ─────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
import os

from lib.config import LLM_API_URL as DEEPSEEK_API_URL
DEEPSEEK_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 1024) -> str:
    """Call DeepSeek and return the response text."""
    if not DEEPSEEK_API_KEY:
        return "[error: DEEPSEEK_API_KEY not configured]"

    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "temperature": 0.3,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(
        DEEPSEEK_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode())
        choices = result.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "").strip()


def main():
    days = 7
    min_entries_per_cluster = 2

    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        days = int(sys.argv[idx + 1])
    if "--min-entries" in sys.argv:
        idx = sys.argv.index("--min-entries")
        min_entries_per_cluster = int(sys.argv[idx + 1])

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        """SELECT id, title, source_url, auto_tags, content,
                  LENGTH(content) as content_len
           FROM entries
           WHERE created_at >= ?
           ORDER BY created_at DESC""",
        (cutoff,),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"## Pliny Weekly Digest — No Activity\n\nNo entries were saved in the last {days} days.")
        return

    total = len(rows)
    print("# Pliny Weekly Digest")
    print(f"**Period:** Last {days} days · **{total} entries saved**\n")

    # Cluster entries by shared tags
    clusters = {}  # tag -> list of entries
    for r in rows:
        try:
            tags = json.loads(r[3]) if r[3] else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        for tag in tags:
            tag = tag.strip().lower()
            if not tag:
                continue
            if tag not in clusters:
                clusters[tag] = []
            clusters[tag].append({
                "id": r[0],
                "title": r[1] or "(no title)",
                "url": r[2] or "",
                "summary": (r[4] or "")[:200],
                "content_len": r[5] or 0,
            })

    # Sort clusters by number of entries (descending), filter by minimum
    sorted_clusters = sorted(clusters.items(), key=lambda x: -len(x[1]))
    sorted_clusters = [(tag, entries) for tag, entries in sorted_clusters
                       if len(entries) >= min_entries_per_cluster]

    # Also create a "miscellaneous" bucket for entries that don't fit any cluster
    clustered_ids = set()
    for _, entries in sorted_clusters:
        for e in entries:
            clustered_ids.add(e["id"])

    uncategorized = [r for r in rows if r[0] not in clustered_ids]

    # Header stats
    print(f"**Clusters found:** {len(sorted_clusters)}")
    if uncategorized:
        print(f"**Uncategorized:** {len(uncategorized)} entries\n")
    else:
        print()

    # Generate a cluster synthesis for the top clusters (max 8 to stay within token budget)
    max_clusters = 8
    for idx, (tag, entries) in enumerate(sorted_clusters[:max_clusters]):
        titles = "\n".join(f"- {e['title']}" for e in entries[:10])
        summaries = "\n".join(
            f"- {e['title']}: {e['summary'][:200]}" if e['summary'] else f"- {e['title']}"
            for e in entries[:8]
        )

        # Skip LLM call for very small clusters — just list them
        if len(entries) < 3:
            print(f"## {idx+1}. {tag.title()}")
            print(f"**{len(entries)} entries**\n")
            for e in entries:
                print(f"- [{e['title']}]({e['url']})")
            print()
            continue

        # Call LLM for synthesis
        system_prompt = (
            "You are an analyst reviewing a user's saved bookmarks. "
            "Given a group of related entries, identify the key themes, insights, "
            "and patterns across them. Be concise (2-3 sentences max). "
            "Output only the synthesis, no disclaimers."
        )

        user_prompt = f"""These entries are all tagged with "{tag}".

Titles:
{titles}

Summaries:
{summaries}

Synthesize: What are the key themes and takeaways across these entries?"""

        try:
            synthesis = call_llm(system_prompt, user_prompt, max_tokens=512)
        except Exception as e:
            synthesis = f"*Synthesis failed: {e}*"

        print(f"## {idx+1}. {tag.title()}")
        print(f"**{len(entries)} entries**\n")
        print(f"{synthesis}\n")
        for e in entries[:5]:
            print(f"- [{e['title']}]({e['url']})")
        if len(entries) > 5:
            print(f"  *...and {len(entries) - 5} more*")
        print()

    # Uncategorized entries
    if uncategorized:
        print("---\n")
        print(f"## Other Saved Links ({len(uncategorized)})\n")
        for r in uncategorized[:10]:
            title = r[1] or "(no title)"
            url = r[2] or ""
            print(f"- [{title}]({url})")
        if len(uncategorized) > 10:
            print(f"  *...and {len(uncategorized) - 10} more*")
        print()

    # Footer
    print("---\n")
    print(f"*Generated by Pliny · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")


if __name__ == "__main__":
    main()
