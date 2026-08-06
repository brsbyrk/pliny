# Pliny — Implementation Plan

> **Goal:** Personal knowledge engine — capture anything, search everything, single Rust binary.

**Architecture:** Single crate with strict modules. Trait-based extractor system. SQLite + FTS5 + vec0 for storage. Axum for server. `pliny ingest|serve|search|rss` CLI.

**Tech Stack:** Rust 2021, tokio, axum, rusqlite (bundled), sqlite-vec, reqwest, readability, feed-rs, ort (ONNX), clap.

---

## Completed

| # | Feature | Status |
|---|---|---|
| 0 | Scaffold: Cargo.toml, module structure, types, traits, config, store schema, CLI stubs | ✅ |

---

## Phase 1: Capture Engine

### Task 1: Web Extractor ✅

> **DONE** — 6 tests passing. Readability-based HTML extraction with 404/empty/non-HTML handling.

> The catch-all extractor. Uses `readability` crate to extract article content from HTML. Falls back to plain text if readability fails.

**Files:**
- Implement: `src/extractors/web.rs`
- Test: `tests/extractors/web.rs`

**Acceptance criteria:**
- `can_handle()` returns true for any URL (catch-all)
- `extract()` fetches HTML → readability → Entry with title, content, source_type
- Handles: valid article, 404, timeout, non-HTML content, empty page
- `name()` returns "web"

### Task 2: X/Twitter Extractor

> Fetches tweet/thread data from fxtwitter API (free, no auth).

**Files:**
- Implement: `src/extractors/twitter.rs`
- Test: `tests/extractors/twitter.rs`

**Acceptance criteria:**
- `can_handle()` returns true for x.com and twitter.com URLs
- `extract()` calls fxtwitter API → formats tweet/thread → Entry
- Handles: single tweet, thread, deleted tweet, invalid URL

### Task 3: GitHub Extractor

> Fetches README from raw.githubusercontent.com, falls back to API description.

**Files:**
- Implement: `src/extractors/github.rs`
- Test: `tests/extractors/github.rs`

### Task 4: Reddit Extractor

> Fetches post + comments from reddit.com/.json API (free, rate-limited).

**Files:**
- Implement: `src/extractors/reddit.rs`
- Test: `tests/extractors/reddit.rs`

### Task 5: YouTube Extractor

> Fetches metadata via oembed API. Transcript via yt-dlp (system dependency).

**Files:**
- Implement: `src/extractors/youtube.rs`
- Test: `tests/extractors/youtube.rs`

### Task 6: Ingest Pipeline

> Wires extractors into `pliny ingest <url>` CLI command. Auto-detect source → extract → store.

**Files:**
- Implement: `src/commands.rs`, `src/extractors/mod.rs`
- Test: `tests/ingest.rs`

---

## Phase 2: Search

### Task 7: FTS5 Search

> Full-text search via SQLite FTS5 with BM25 ranking and snippets.

### Task 8: Embeddings + Vector Search

> ONNX inference (all-MiniLM-L6-v2) → vec0 ANN search via sqlite-vec.

### Task 9: Hybrid RRF

> Reciprocal rank fusion of FTS5 + vector results.

---

## Phase 3: Server + UX

### Task 10: REST API

> Axum routes: GET /api/entries (search), POST /api/ingest (capture from extension), GET /api/stats.

### Task 11: Dashboard

> Port Python v0.3 dashboard (index.html, pliny.css, pliny.js, command-bar.css) to Rust static serving.

### Task 12: Browser Extension

> Update extension to point to new Axum backend. Add real icons.

---

## Phase 4: Feed Monitor

### Task 13: RSS/Atom Feed Monitor

> Poll feeds via `feed-rs`, dedup against store, auto-ingest new entries.

---

## Phase 5: Polish

### Task 14: Importers

> Import from browser bookmarks, Pocket export, Raindrop export.

### Task 15: Synthesis

> On-demand cross-pollination: "connect these three entries." LLM-powered via DeepSeek API.
