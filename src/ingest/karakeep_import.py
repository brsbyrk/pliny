#!/usr/bin/env python3
"""karakeep_import.py — Import bookmarks from Karakeep into Pliny.

Usage:
    .venv/bin/python3 src/ingest/karakeep_import.py          # import 50 (default)
    .venv/bin/python3 src/ingest/karakeep_import.py --batch 100
    .venv/bin/python3 src/ingest/karakeep_import.py --batch 100 --dry-run

Design:
  - Exports unprocessed bookmarks from Karakeep (paginated API)
  - Skips URLs already tagged `pliny:imported` (from previous runs)
  - Skips URLs already in Pliny's DB
  - Feeds each new URL through url_ingest.ingest_url()
  - On success: tags bookmark with `pliny:imported` + `pliny:batch:<run-id>`
  - On failure: tags with `pliny:failed`
  - Writes run state to data/kk-import-state.json (resumable)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make src/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.schema import get_db
from lib.paths import DB_PATH, QUEUES_DIR

logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────
DEFAULT_BASE_URL = "http://127.0.0.1:3000"
STATE_PATH = QUEUES_DIR / "kk-import-state.json"
BATCH_TAG = "pliny:imported"
FAIL_TAG = "pliny:needs-review"
PRE_DELAY = 1.0   # seconds before each extraction (anti-rate-limit)

# ── Karakeep API helpers ──────────────────────────────────────


def _read_dotenv(path: Path, key: str) -> str | None:
    """Read a key=value from a .env file. Returns None if missing."""
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            val = line.split("=", 1)[1].strip().strip("\"'")
            if val:
                return val
    return None


def load_env() -> str:
    token = os.environ.get("KARAKEEP_API_TOKEN")
    if token:
        return token

    # Try pliny/.env (KARAKEEP_KEY)
    dotenv = Path(__file__).resolve().parent.parent.parent / ".env"
    token = _read_dotenv(dotenv, "KARAKEEP_KEY")
    if token:
        return token

    print("! Missing KARAKEEP_API_TOKEN. Set env var or configure pliny/.env with KARAKEEP_KEY.")
    sys.exit(2)


def kk_request(
    method: str, url: str, token: str, body: dict | None = None, timeout: int = 30
) -> tuple[int, Any]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Pliny/1.0",
    }
    data = json.dumps(body).encode() if body else None
    if body:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(txt) if txt else {}
            except json.JSONDecodeError:
                return r.status, txt
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt) if txt else {}
        except json.JSONDecodeError:
            return e.code, txt


def fetch_all_bookmarks(base_url: str, token: str) -> list[dict]:
    """Fetch ALL bookmarks from Karakeep (handles pagination)."""
    items: list[dict] = []
    cursor: str | None = None
    page = 0
    while True:
        params: dict[str, str | int] = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        url = base_url.rstrip("/") + "/api/v1/bookmarks?" + urllib.parse.urlencode(params)
        status, payload = kk_request("GET", url, token)
        if not (200 <= status < 300):
            print(f"! API error {status} at page {page + 1}, stopping")
            break
        batch = payload.get("bookmarks", [])
        if not batch:
            break
        items.extend(batch)
        next_cursor = payload.get("nextCursor")
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        page += 1
        time.sleep(0.1)
    return items


def bookmark_has_tag(bookmark: dict, tag_name: str) -> bool:
    """Check if a bookmark already has a specific tag."""
    for tag in bookmark.get("tags", []):
        if isinstance(tag, dict) and tag.get("name") == tag_name:
            return True
        if isinstance(tag, str) and tag == tag_name:
            return True
    return False


def attach_tags(base_url: str, token: str, bookmark_id: str, tags: list[str]) -> bool:
    """Attach tags to a Karakeep bookmark. Returns True on success."""
    cleaned = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
    if not cleaned:
        return True
    endpoint = base_url.rstrip("/") + f"/api/v1/bookmarks/{bookmark_id}/tags"
    body = {"tags": [{"tagName": tag} for tag in cleaned]}
    status, _payload = kk_request("POST", endpoint, token, body)
    return 200 <= status < 300


# ── Pliny helpers ─────────────────────────────────────────────


def known_urls(db) -> set[str]:
    rows = db.execute(
        "SELECT source_url FROM entries WHERE source_url IS NOT NULL"
    ).fetchall()
    return set(r[0] for r in rows)


def run_id() -> str:
    return datetime.now(timezone.utc).strftime("kk-%Y%m%d-%H%M%S")


# ── State persistence (resumable) ──────────────────────────────


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"run_id": None, "processed": [], "skipped": [], "failed": [], "total_run": 0}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


# ── Main ───────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="Import Karakeep bookmarks into Pliny")
    ap.add_argument("--batch", type=int, default=50, help="Max bookmarks to process (default: 50)")
    ap.add_argument("--dry-run", action="store_true", help="Scan and report without importing")
    ap.add_argument("--base-url", default=os.environ.get("KARAKEEP_BASE_URL", DEFAULT_BASE_URL))
    ap.add_argument(
        "--from-state",
        action="store_true",
        help="Resume from saved state (skips already-processed URLs)",
    )
    args = ap.parse_args()


    token = load_env()
    base = args.base_url.rstrip("/")
    rid = run_id()
    batch_limit = args.batch
    dry = args.dry_run

    # ── 1. Load state ──
    state = load_state()
    already_processed = set(state.get("processed", []))

    # ── 2. Fetch bookmarks ──
    print("V Fetching bookmarks from Karakeep...", flush=True)
    all_bookmarks = fetch_all_bookmarks(base, token)
    print(f"V Fetched {len(all_bookmarks)} total bookmarks", flush=True)

    # ── 3. Filter candidates ──
    candidates: list[dict] = []
    already_tagged = 0
    already_dead = 0
    needs_review = 0
    no_url = 0
    for bm in all_bookmarks:
        content = bm.get("content", {})
        url = content.get("url", "") if isinstance(content, dict) else ""
        if not url:
            no_url += 1
            continue
        if bookmark_has_tag(bm, "pliny:dead"):
            already_dead += 1
            continue
        if bookmark_has_tag(bm, BATCH_TAG):
            already_tagged += 1
            continue
        if bookmark_has_tag(bm, FAIL_TAG):
            needs_review += 1
            continue  # Skip previously failed entries
        if bookmark_has_tag(bm, "alfred:imported"):
            # Alfred-era imports — already in Pliny, no need to re-scan
            continue
        candidates.append(bm)

    print(
        f"  Already tagged '{BATCH_TAG}': {already_tagged}"
        f"\n  Tagged 'dead': {already_dead}"
        f"\n  Tagged 'needs-review': {needs_review}"
        f"\n  No URL: {no_url}"
        f"\n  Candidates: {len(candidates)}"
    )

    if not candidates:
        print("V Nothing to import!")
        return 0

    # ── 4. Load Pliny's known URLs for dedup ──
    db = get_db(DB_PATH)
    known = known_urls(db)
    db.close()

    # ── 5. Process batch ──
    imported = 0
    skipped_dup = 0
    failed_list: list[str] = []

    batch = candidates[:batch_limit]

    if dry:
        print(
            f"\n[Dry run] Would process up to {len(batch)} bookmarks:"
            f"\n  Total candidates: {len(candidates)}"
            f"\n  Remaining (after this batch): {len(candidates) - len(batch)}"
        )
        for bm in batch:
            content = bm.get("content", {})
            url = content.get("url", "")
            title = content.get("title", "") or bm.get("title", "") or "(no title)"
            in_pliny = " [already in Pliny]" if url in known else ""
            print(f"  {title[:60]:60s} {in_pliny or ''}")
        print(
            f"\nSummary: {len(batch)} scanned, "
            f"{'would skip ' + str(sum(1 for bm in batch if bm.get('content', {}).get('url', '') in known)) + ', ' if dry else ''}"
            f"would import {sum(1 for bm in batch if bm.get('content', {}).get('url', '') not in known)}"
        )
        return 0

    print(f"\n{'='*60}")
    print(f"Importing up to {batch_limit} bookmarks (batch {rid})")
    print(f"{'='*60}\n")

    from ingest.url_ingest import ingest_url

    db = get_db(DB_PATH)

    for i, bm in enumerate(batch, 1):
        content = bm.get("content", {})
        url = content.get("url", "") if isinstance(content, dict) else ""
        bm_id = bm.get("id", "")
        title = content.get("title", "") or bm.get("title", "") or url[:60]
        short_title = (title[:55] + "..") if len(title) > 55 else title

        # Skip if already in Pliny
        if url in known:
            print(f"  [{i}/{len(batch)}] ~ Skipped (already in Pliny): {short_title}")
            skipped_dup += 1
            # Still tag it so we don't re-check
            if bm_id:
                attach_tags(base, token, bm_id, [BATCH_TAG, f"{BATCH_TAG}:{rid}"])
            already_processed.add(url)
            continue

        # Small delay before extraction (anti-rate-limit)
        time.sleep(PRE_DELAY)

        # Import (with retry for DB lock)
        print(f"  [{i}/{len(batch)}] ~ Importing: {short_title}...", end="", flush=True)
        eid = None
        last_err = None
        for attempt in range(3):
            try:
                eid = ingest_url(url, db=db)
                break
            except Exception as e:
                err_str = str(e)
                if "database is locked" in err_str or "UNIQUE constraint" in err_str:
                    last_err = err_str
                    time.sleep(1.5 * (attempt + 1))
                    continue
                last_err = err_str
                break

        if eid:
            print(f" V (id={eid})", flush=True)
            imported += 1
            state["total_run"] = state.get("total_run", 0) + 1
            if bm_id:
                ok = attach_tags(base, token, bm_id, [BATCH_TAG, f"{BATCH_TAG}:{rid}"])
                if not ok:
                    print(f"  ! Warning: failed to tag bookmark {bm_id}")
            already_processed.add(url)
        elif last_err:
            print(f" X error: {last_err}", flush=True)
            failed_list.append(url)
            if bm_id:
                try:
                    attach_tags(base, token, bm_id, [FAIL_TAG, f"{FAIL_TAG}:{rid}"])
                except Exception as e:
                    logger.warning("failed to tag failed bookmark %s with %s: %s", bm_id, FAIL_TAG, e)
        else:
            print(" X extraction failed", flush=True)
            failed_list.append(url)
            if bm_id:
                attach_tags(base, token, bm_id, [FAIL_TAG, f"{FAIL_TAG}:{rid}"])

        # Small delay between requests
        time.sleep(0.3)

    # Close shared DB connection
    db.close()

    # ── 6. Save state ──
    state["run_id"] = rid
    state["processed"] = list(already_processed)
    state["skipped"] = list(set(state.get("skipped", [])) | {u for u in [bm.get("content", {}).get("url", "") for bm in batch] if u in known})
    state["failed"] = list(set(state.get("failed", [])) | set(failed_list))
    save_state(state)

    # ── 7. Summary ──
    remaining = len(candidates) - len(batch)
    print(f"\n{'='*60}")
    print(f"Batch complete: {rid}")
    print(f"  Imported:  {imported}")
    print(f"  Skipped:   {skipped_dup} (already in Pliny)")
    print(f"  Failed:    {len(failed_list)}")
    print(f"  Remaining: {remaining} candidates left")
    print(f"{'='*60}")

    fn = STATE_PATH.name
    print(f"\nState saved to data/{fn}")
    if remaining > 0:
        print(f"Run again to process next batch: python3 src/ingest/karakeep_import.py --batch {batch_limit}")

    return 0 if not failed_list else 1


if __name__ == "__main__":
    raise SystemExit(main())
