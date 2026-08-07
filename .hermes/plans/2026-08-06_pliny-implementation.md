# Pliny — Implementation Plan

> **Goal:** Personal knowledge engine — capture anything, search everything. Single Rust binary.

**Architecture:** Single crate, strict modules. Extractors (trait + enrich), SQLite+FTS5+vec0, Axum, React+shadcn+Tailwind.

---

## Done ✅

| # | Task | Tests |
|---|---|---|
| 0 | Scaffold: Cargo.toml, module structure, traits, CLI | — |
| 1 | Web extractor (readability) | 6 |
| 2 | X extractor (og:meta + fxtwitter enrichment) | 17 |
| 3 | GitHub extractor (raw README + API fallback) | 14 |
| 4 | Reddit extractor (JSON API, comments) | 11 |
| 5 | YouTube extractor (oembed + timedtext captions) | 11 |
| 6 | FTS5 search (BM25, snippets, search CLI) | 5 |
| 7 | Axum server (API + embedded React SPA) | — |
| 8 | Dashboard (shadcn/ui + Tailwind, light/dark theme) | — |
| 9 | Browser extension (popup + context menu) | — |
| 10 | RSS/Atom feed monitor (feed-rs, dedup, auto-ingest) | 3 |
| 11 | Dedup (URL check before insert, duplicate toast) | — |
| 12 | Tags in UI (badges, coalesce) | — |
| 13 | Live search (300ms debounce, keyboard shortcuts) | — |
| 14 | Entry detail modal (full content from API) | — |
| 15 | Embedding stub (ONNX-ready interface) | 3 |

**Total: 69 tests, 0 warnings, 1 binary.**

---

## In Progress / Next

### Phase 6: Manual Notes

**Goal:** Add arbitrary text as entries without a URL.

```rust
SourceType::Note  // new variant
```

- [ ] `pliny note "content" [--title "..."]` — saves directly
- [ ] Textarea in dashboard — "Write a note" button
- [ ] Notes appear in search/browse like any entry
- [ ] Notes have no source_url (or `/notes/{id}` placeholder)

### Phase 7: Full Embeddings + Vector Search

**Goal:** ONNX inference (all-MiniLM-L6-v2) → vec0 ANN search → RRF fusion.

- [ ] Download model script (`pliny setup-model` or `make model`)
- [ ] Finish ONNX inference in `src/search/embed.rs`
- [ ] Embed on ingest (async, background)
- [ ] `Store::search_vec()` — vec0 ANN via sqlite-vec
- [ ] `Store::search_hybrid()` — RRF fusion of FTS5 + vector results

### Phase 8: Related Entries

**Goal:** Click any entry → "Related" panel with top-5 nearest neighbors.

- [ ] `GET /api/entry/{id}/related` — vector similarity
- [ ] "Related" section in detail modal
- [ ] Falls back gracefully when no embeddings available

### Phase 9: Importers

**Goal:** Bulk import from existing knowledge tools.

- [ ] Pocket export (HTML file)
- [ ] Browser bookmarks (HTML export)
- [ ] Raindrop export (CSV)
- [ ] `pliny import <file>` command

### Phase 10: Synthesis (v0.2+)

**Goal:** LLM-powered "connect these entries" via DeepSeek API.

- [ ] `POST /api/synthesis` — takes entry IDs + prompt
- [ ] DeepSeek API integration
- [ ] Synthesis results page in dashboard

### Polish

- [ ] Browser extension real icons
- [ ] `pliny stats` CLI — source type breakdown
- [ ] Tags as first-class: autocomplete, filter by tag
- [ ] Offline content storage (full HTML archive)
