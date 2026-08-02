#!/usr/bin/env python3
"""migrate.py — Migrate source cards from vault into pliny.db.

Usage:
    python3 src/migrate.py
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from lib.schema import get_db
from lib.embed import embed_json
from lib.paths import DB_PATH, VAULT_CARDS


def parse_card(path: Path) -> dict | None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.DOTALL)
    if not m:
        return None

    fm = m.group(1)
    body = raw[m.end():]

    def get_field(name: str) -> str | None:
        mo = re.search(rf"^{name}:\s*(.+?)$", fm, re.MULTILINE)
        if mo:
            v = mo.group(1).strip().strip("'\"")
            return None if v.lower() in ("", "none") else v
        return None

    source_url = get_field("source_url")
    title = get_field("title")
    captured_at = get_field("captured_at")
    entry_id = path.stem

    if not source_url or not title:
        return None

    content_start = body.find("\n# ")
    content_body = body[content_start:] if content_start >= 0 else body

    for section in ["## Knowledge graph links", "## Source metadata", "## Extraction metadata",
                     "## Repository metadata", "## Selected repository structure"]:
        idx = content_body.find(section)
        if idx >= 0:
            ns = content_body.find("\n## ", idx + 1)
            content_body = content_body[:idx] + (content_body[ns:] if ns >= 0 else "")

    content_body = re.sub(r"^#\s+.*\n?", "", content_body, count=1).strip()
    if not content_body:
        return None

    return {"id": entry_id, "source_url": source_url, "title": title,
            "content": content_body, "captured_at": captured_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def migrate():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = get_db(DB_PATH)
    cards_dir = Path(VAULT_CARDS)

    if not cards_dir.is_dir():
        print(f"X Cards directory not found: {cards_dir}")
        sys.exit(1)

    md_files = sorted(cards_dir.glob("*.md"))
    print(f"Found {len(md_files)} source card files")

    inserted = 0
    skipped = 0
    errors = []

    for i, path in enumerate(md_files):
        card = parse_card(path)
        if card is None:
            skipped += 1
            errors.append(f"  Parse failed: {path.name}")
            continue
        try:
            db.execute(
                """INSERT OR REPLACE INTO entries (id, source_url, title, content, created_at, modified_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (card["id"], card["source_url"], card["title"], card["content"], card["captured_at"], card["captured_at"]),
            )
            vec = embed_json(card["title"] + "\n\n" + card["content"])
            db.execute("INSERT INTO entries_v0 (rowid, embedding) VALUES (?, ?)",
                       (db.execute("SELECT rowid FROM entries WHERE id = ?", (card["id"],)).fetchone()[0], vec))
            inserted += 1
        except Exception as e:
            errors.append(f"  DB error [{path.name}]: {e}")
            skipped += 1

        if (i + 1) % 25 == 0:
            print(f"  Progress: {i+1}/{len(md_files)} ({inserted} inserted, {skipped} skipped)")
            db.commit()

    db.commit()
    db.close()
    print(f"\nV Migration complete: {inserted} inserted, {skipped} skipped")
    if errors:
        print("Errors:")
        for e in errors:
            print(e)


if __name__ == "__main__":
    migrate()
