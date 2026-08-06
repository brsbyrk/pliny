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

## Phase 1: Capture Engine ✅

### Task 1: Web Extractor ✅
> Readability-based HTML extraction. 6 tests.

### Task 2: X/Twitter Extractor ✅
> og:meta primary + fxtwitter enrichment. 17 tests (8 parsing + 2 JSON + 7 integration).

### Task 3: GitHub Extractor ✅
> Raw README (main→master) + API fallback. 14 tests (6 parsing + 4 integration + 4 API).

### Task 4: Reddit Extractor ✅
> JSON API (no auth) with comment extraction. 11 tests (7 parsing/formatting + 4 integration).

### Task 5: YouTube Extractor ✅
> oembed metadata + timedtext captions (no yt-dlp). 11 tests (8 parsing + 3 integration).

**Total: 55 tests, all pass. 0 warnings.**

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
