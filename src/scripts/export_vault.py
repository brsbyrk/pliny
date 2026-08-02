#!/usr/bin/env python3
"""export_vault.py — Export Pliny entries -> Obsidian vault.

Reads pliny.db and writes .md files into a vault directory.
The vault is an optional export — Pliny's index remains source of truth.

Usage:
    python3 src/export_vault.py [--vault <path>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.schema import get_db


def build_md(entry: dict[str, Any]) -> str:
    lines = [
        "---",
        f"id: {entry['id']}",
        f"source_url: {entry['source_url']}",
        f"title: {entry['title']}",
        f"created_at: {entry['created_at']}",
        f"modified_at: {entry['modified_at']}",
        "---",
        "",
        f"# {entry['title']}",
        "",
        entry['content'],
        "",
        f"Source: [{entry['source_url']}]({entry['source_url']})",
    ]
    return "\n".join(lines)


def export(vault_dir: str | Path) -> int:
    vault = Path(vault_dir)
    vault.mkdir(parents=True, exist_ok=True)

    db = get_db()
    rows = db.execute("SELECT * FROM entries ORDER BY created_at DESC").fetchall()
    db.close()

    if not rows:
        print("No entries to export.")
        return 0

    count = 0
    for row in rows:
        entry = dict(row)
        out_path = vault / f"{entry['id']}.md"
        out_path.write_text(build_md(entry), encoding="utf-8")
        count += 1

    print(f"Exported {count} entries to {vault}")
    return count


def main():
    parser = argparse.ArgumentParser(description="Export Pliny entries to Obsidian vault")
    parser.add_argument("--vault", help="Output vault directory",
                        default=str(Path.home() / "workspace" / "_vaults" / "BBB" / "00-Projects" / "LinkLab" / "sources" / "cards"))
    args = parser.parse_args()
    export(args.vault)


if __name__ == "__main__":
    main()
