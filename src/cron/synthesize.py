#!/usr/bin/env python3
"""synthesize.py — Cross-pollination knowledge synthesis agent.

Queries recent entry pairs with complementary embeddings + tags, has an LLM
judge which pairs generate novel insight, and saves synthesis entries.

Pipeline:
  1. Load recent entries (last 7 days) with embeddings + tags
  2. Pairwise cosine similarity — keep pairs in sweet spot (0.3-0.7)
  3. Reject pairs with >60% tag overlap (same topic — boring)
  4. Dedup against existing synthesis entries
  5. LLM judge: worth synthesizing? (filters ~70-80%)
  6. LLM write: generate synthesis with source references
  7. Save as entry_type='synthesis' with source_refs

Usage:
    .venv/bin/python src/synthesize.py                    # default: last 7 days
    .venv/bin/python src/synthesize.py --days 14 --max-pairs 20
    .venv/bin/python src/synthesize.py --dry-run
"""

import json
import logging
import sqlite3
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

import sqlite_vec

logger = logging.getLogger(__name__)

from lib.paths import DB_PATH
from lib.embed import embed_json
from lib.llm import call_llm

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
DEFAULT_DAYS = 7
SIMILARITY_MIN = 0.30   # cosine similarity minimum
SIMILARITY_MAX = 0.75   # cosine similarity maximum (avoid near-duplicates)
TAG_OVERLAP_MAX = 0.60  # max tag overlap ratio to reject
MAX_CANDIDATE_PAIRS = 200  # max pairs to consider for LLM judging
MAX_SYNTHESES = 15       # max syntheses to create per run
MAX_TAGS_PER_ENTRY = 15  # cap tag count for overlap computation

# ── Helpers ───────────────────────────────────────────────────


def _parse_tags(raw: str | None) -> list[str]:
    """Parse JSON auto_tags column into a list of lowercase tags."""
    if not raw:
        return []
    try:
        tags = json.loads(raw)
        if isinstance(tags, list):
            return [t.strip().lower() for t in tags if t.strip()][:MAX_TAGS_PER_ENTRY]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _unpack_embedding(blob: bytes) -> list[float]:
    """Unpack vec0 F32_BLOB (1536 bytes = 384 float32s) into floats."""
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(ai * bi for ai, bi in zip(a, b))
    norm_a = sum(ai * ai for ai in a) ** 0.5
    norm_b = sum(bi * bi for bi in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _tag_overlap(tags_a: list[str], tags_b: list[str]) -> float:
    """Jaccard-like overlap: intersection / min(len(a), len(b))."""
    if not tags_a or not tags_b:
        return 0.0
    set_a, set_b = set(tags_a), set(tags_b)
    intersection = len(set_a & set_b)
    return intersection / min(len(set_a), len(set_b))


def _get_existing_synthesis_pairs(db: sqlite3.Connection) -> set[tuple[str, str]]:
    """Return set of (id1, id2) canonicalized pairs that are already synthesized."""
    rows = db.execute(
        """SELECT source_refs FROM entries WHERE entry_type = 'synthesis'
           AND source_refs IS NOT NULL AND source_refs != '[]'"""
    ).fetchall()
    pairs = set()
    for (refs_json,) in rows:
        try:
            refs = json.loads(refs_json)
            if isinstance(refs, list) and len(refs) == 2:
                pairs.add(tuple(sorted(refs)))
        except (json.JSONDecodeError, TypeError):
            pass
    return pairs


def _judge_pair(entry_a: dict, entry_b: dict) -> tuple[bool, str]:
    """Ask LLM if these two entries should be synthesized together.

    Returns (is_worthwhile, reason).
    """
    system = (
        "You are a knowledge synthesis judge. Given two saved entries "
        "from a user's knowledge base, determine if combining insights "
        "from both would produce something genuinely novel that you "
        "couldn't get from either alone. Be critical — only approve "
        "pairs with real complementary value."
    )

    prompt = f"""Entry A:
Title: {entry_a['title'][:200]}
Tags: {', '.join(entry_a['tags'][:8])}
Content preview: {entry_a['content'][:600]}

Entry B:
Title: {entry_b['title'][:200]}
Tags: {', '.join(entry_b['tags'][:8])}
Content preview: {entry_b['content'][:600]}

Question: Would synthesizing these two produce genuinely novel insight?
Consider: Do they cover different aspects of a shared theme?
Do they come from different domains that could cross-pollinate?
Would the combination reveal something neither alone suggests?

Respond with exactly one line:
WORTH_IT: yes or no
REASON: a one-sentence explanation"""

    try:
        response = call_llm(system, prompt, max_tokens=256)
        lines = response.splitlines()
        worth_it = False
        reason = ""
        for line in lines:
            if line.upper().startswith("WORTH_IT:"):
                val = line[9:].strip().lower()
                worth_it = val in ("yes", "true", "y")
            elif line.upper().startswith("REASON:"):
                reason = line[7:].strip()
        return worth_it, reason
    except Exception as e:
        log.warning(f"LLM judge error: {e}")
        return False, ""


def _write_synthesis(entry_a: dict, entry_b: dict, reason: str) -> str:
    """Generate synthesis content from two entries using LLM.

    Returns the synthesis text as a string.
    """
    system = (
        "You are a knowledge synthesizer. Combine two entries into "
        "a short synthesis that reveals the connection between them. "
        "Focus on: what insight emerges from combining these two sources? "
        "Keep it to 3-5 sentences. Reference source titles explicitly."
    )

    prompt = f"""Entry A: "{entry_a['title']}"
Tags: {', '.join(entry_a['tags'][:8])}
Content: {entry_a['content'][:800]}

Entry B: "{entry_b['title']}"
Tags: {', '.join(entry_b['tags'][:8])}
Content: {entry_b['content'][:800]}

The judge said: {reason}

Write a short synthesis (3-5 sentences) that:
1. States the connection between these two sources
2. Explains the key insight from combining them
3. Mentions each source by title"""

    try:
        return call_llm(system, prompt, max_tokens=512)
    except Exception as e:
        return f"[Synthesis failed: {e}]"


def _generate_title(entry_a: dict, entry_b: dict, content: str) -> str:
    """Generate a concise title for the synthesis."""
    # Use a simpler prompt with explicit delimiter
    system = "Generate a concise title (max 10 words) for a synthesis of these two entries. Return ONLY the title text, no quotes, no prefixes, no labels."
    prompt = f"Entries: \"{entry_a['title'][:100]}\" and \"{entry_b['title'][:100]}\"\nSynthesis: \"{content[:200]}\""
    try:
        title = call_llm(system, prompt, max_tokens=50)
        title = title.strip().strip('"').strip("'").strip()
        if title and len(title) > 3:
            return title
    except Exception as e:
        logger.warning("synthesis title fallback failed: %s", e)
    # Fallback: generate a readable title from source IDs
    return f"{entry_a['title'][:40]} × {entry_b['title'][:40]}"


# ── Core pipeline ─────────────────────────────────────────────


def _slugify(text: str, fallback_a: str = "", fallback_b: str = "") -> str:
    """Generate a URL-safe slug."""
    slug = text.lower().strip()
    slug = "".join(c if c.isalnum() or c in "-_ " else " " for c in slug)
    slug = "-".join(slug.split())
    if slug:
        return slug[:80]
    # Fallback: use source IDs to guarantee uniqueness
    fa = fallback_a.strip().replace(" ", "-")[:30] if fallback_a else "x"
    fb = fallback_b.strip().replace(" ", "-")[:30] if fallback_b else "y"
    return f"synthesis-{fa}-{fb}"


def run_synthesis(
    days: int = DEFAULT_DAYS,
    max_syntheses: int = MAX_SYNTHESES,
    max_candidate_pairs: int = MAX_CANDIDATE_PAIRS,
    dry_run: bool = False,
) -> dict:
    """Run the cross-pollination synthesis pipeline.

    Returns a result dict with counts.
    """
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    # ── 1. Load recent entries ──
    rows = db.execute(
        """SELECT e.rowid, e.id, e.title, e.content, e.auto_tags,
                  e.entry_type, e.created_at
           FROM entries e
           WHERE e.created_at >= datetime('now', ?)
             AND e.extraction_status IN ('extracted', 'thin')
             AND e.entry_type NOT IN ('synthesis', 'gap-report')
           ORDER BY e.created_at DESC""",
        (f"-{days} days",),
    ).fetchall()

    if not rows:
        db.close()
        return {"entries_scanned": 0, "pairs_evaluated": 0, "syntheses_created": 0, "error": "no entries found"}

    entries = []
    for r in rows:
        entries.append({
            "rowid": r["rowid"],
            "id": r["id"],
            "title": r["title"] or "(no title)",
            "content": r["content"] or "",
            "tags": _parse_tags(r["auto_tags"]),
            "entry_type": r["entry_type"] or "bookmark",
            "created_at": r["created_at"],
        })

    # ── 2. Load embeddings ──
    placeholders = ",".join("?" * len(entries))
    vec_rows = db.execute(
        f"SELECT rowid, embedding FROM entries_v0 WHERE rowid IN ({placeholders})",
        [e["rowid"] for e in entries],
    ).fetchall()

    embeddings: dict[int, list[float]] = {}
    for vr in vec_rows:
        try:
            embeddings[vr["rowid"]] = _unpack_embedding(vr["embedding"])
        except (TypeError, struct.error):
            pass

    db.close()

    # Filter entries to those with embeddings
    entries = [e for e in entries if e["rowid"] in embeddings]
    n = len(entries)
    if n < 2:
        return {"entries_scanned": n, "pairs_evaluated": 0, "syntheses_created": 0, "error": "need at least 2 entries"}

    # ── 3. Pairwise similarity (numpy-accelerated) ──
    import numpy as np

    # Build embedding matrix (entries × 384)
    order = [e["rowid"] for e in entries]
    matrix = np.array([embeddings[rid] for rid in order], dtype=np.float32)

    # Normalize for cosine similarity
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    matrix = matrix / norms

    # Full pairwise cosine similarity matrix
    sim_matrix = matrix @ matrix.T  # (n × n)

    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = float(sim_matrix[i, j])
            if sim < SIMILARITY_MIN or sim > SIMILARITY_MAX:
                continue
            a, b = entries[i], entries[j]
            overlap = _tag_overlap(a["tags"], b["tags"])
            if overlap > TAG_OVERLAP_MAX:
                continue
            pairs.append({
                "a": a,
                "b": b,
                "similarity": round(sim, 4),
                "tag_overlap": round(overlap, 4),
            })

    if not pairs:
        return {"entries_scanned": n, "pairs_evaluated": 0, "syntheses_created": 0, "error": "no qualifying pairs"}

    # Sort by similarity (lower = more distant = potentially more interesting)
    pairs.sort(key=lambda p: p["similarity"])

    # Dedup against existing syntheses
    db = sqlite3.connect(str(DB_PATH))
    existing_pairs = _get_existing_synthesis_pairs(db)
    db.close()

    deduped = [p for p in pairs if tuple(sorted([p["a"]["id"], p["b"]["id"]])) not in existing_pairs]

    if not deduped:
        return {"entries_scanned": n, "pairs_evaluated": len(pairs), "syntheses_created": 0, "error": "all pairs already synthesized"}

    # Limit candidates
    candidates = deduped[:max_candidate_pairs]

    log.info(f"Entries scanned:    {n}")
    log.info(f"Total pairs:        {(n * (n - 1)) // 2}")
    log.info(f"Qualifying pairs:   {len(pairs)}")
    log.info(f"After dedup:        {len(deduped)}")
    log.info(f"Candidates to judge: {len(candidates)}")
    log.info("")

    if dry_run:
        print("=== [Dry-run] Top 10 candidate pairs ===")
        for p in candidates[:10]:
            print(f"  sim={p['similarity']:.3f} overlap={p['tag_overlap']:.2f}")
            print(f"    A: {p['a']['title'][:60]}")
            print(f"    B: {p['b']['title'][:60]}")
        print(f"\nWould process up to {max_syntheses} syntheses.")
        return {"entries_scanned": n, "pairs_evaluated": len(pairs), "syntheses_created": 0, "dry_run": True}

    # ── 4-6. LLM judge → write → save ──
    created = 0
    judged = 0
    approved = 0
    errors = 0
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    start = time.time()

    for idx, pair in enumerate(candidates):
        if created >= max_syntheses:
            break

        a, b = pair["a"], pair["b"]
        judged += 1

        log.info(f"  [{judged}/{len(candidates)}] {a['title'][:40]} × {b['title'][:40]}")

        worth_it, reason = _judge_pair(a, b)
        if not worth_it:
            log.info(f"  ✗ {reason[:60]}")
            continue

        approved += 1
        log.info("  ✓")

        # Generate title + content
        content = _write_synthesis(a, b, reason)
        if not content or content.startswith("[Synthesis failed"):
            log.warning(f"    [write failed] {content[:60]}")
            errors += 1
            continue

        title = _generate_title(a, b, content)
        # Keep title clean
        title = title.strip().strip('"').strip("'")

        # Generate entry_id
        eid = _slugify(title, fallback_a=a['id'], fallback_b=b['id'])

        # Combine tags: union minus overlapping tags, plus _synthesis
        all_tags = list(set(a["tags"] + b["tags"]))
        source_refs = json.dumps([a["id"], b["id"]])
        tag_json = json.dumps(all_tags)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Compute embedding for the synthesis content
        try:
            vec = embed_json(title + "\n\n" + content)
        except Exception as e:
            log.warning(f"    [embed error] {e}")
            errors += 1
            continue

        # Save
        try:
            db.execute(
                """INSERT OR IGNORE INTO entries
                   (id, source_url, title, content, entry_type, source_refs, auto_tags,
                    extraction_status, retry_count, created_at, modified_at)
                   VALUES (?, ?, ?, ?, 'synthesis', ?, ?, 'extracted', 0, ?, ?)""",
                (eid, f"pliny://synthesis/{eid}", title, content,
                 source_refs, tag_json, now, now),
            )

            if db.execute("SELECT changes()").fetchone()[0] == 0:
                log.info(f"    [duplicate] id={eid}")
                errors += 1
                continue

            rowid = db.execute("SELECT rowid FROM entries WHERE id = ?", (eid,)).fetchone()[0]
            db.execute("DELETE FROM entries_v0 WHERE rowid = ?", (rowid,))
            db.execute("INSERT INTO entries_v0 (rowid, embedding) VALUES (?, ?)", (rowid, vec))
            db.commit()
            created += 1
            log.info(f"    ✅ saved as '{eid}' ({len(all_tags)} tags, {len(content)}c)")

        except Exception as e:
            db.rollback()
            log.warning(f"    [db error] {e}")
            errors += 1

        # Small delay between LLM calls
        time.sleep(1.0)

    elapsed = time.time() - start
    db.close()

    result = {
        "entries_scanned": n,
        "pairs_evaluated": len(pairs),
        "candidates_judged": judged,
        "approved": approved,
        "syntheses_created": created,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 1),
    }

    print(f"\n{'='*60}")
    print(f"Done: {created} syntheses created in {elapsed:.0f}s")
    print(f"  {judged} judged, {approved} approved, {errors} errors")
    print(f"  ({created}/{max_syntheses} target)")

    return result


# ── CLI ───────────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Cross-pollination knowledge synthesis")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"Look back N days (default: {DEFAULT_DAYS})")
    parser.add_argument("--max-syntheses", type=int, default=MAX_SYNTHESES, help=f"Max syntheses to create (default: {MAX_SYNTHESES})")
    parser.add_argument("--max-pairs", type=int, default=MAX_CANDIDATE_PAIRS, help=f"Max candidate pairs to judge (default: {MAX_CANDIDATE_PAIRS})")
    parser.add_argument("--dry-run", action="store_true", help="Show candidate pairs without creating syntheses")
    args = parser.parse_args()

    result = run_synthesis(
        days=args.days,
        max_syntheses=args.max_syntheses,
        max_candidate_pairs=args.max_pairs,
        dry_run=args.dry_run,
    )

    print(f"\nFinal: {result['syntheses_created']} syntheses from {result['entries_scanned']} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
