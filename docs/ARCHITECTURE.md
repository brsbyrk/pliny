# Pliny Architecture

**Local-first knowledge infrastructure for humans and AI agents.** Pliny is a shared, searchable corpus where humans and agents collectively store, discover, and synthesize knowledge — with full provenance tracking.

---

## 1. System Overview

Pliny sits at the intersection of bookmark managers, agent memory layers, and knowledge graphs. It ingests content from URLs and agent observations, extracts meaningful text, auto-tags and embeds everything, then makes it all searchable and connectable.

```
Human saves a URL ──→ Pliny extracts, tags, embeds ──→ One SQLite corpus
Agent logs an observation ──→ Pliny stores, tags, embeds ──→ One SQLite corpus
                                                              │
                                              ┌───────────────┴───────────────┐
                                              ↓                               ↓
                                       Hybrid search                    Cross-pollination
                                       (FTS5 + vector)                   (synthesis agent)
                                              ↓                               ↓
                                       Results from                    New knowledge from
                                       both worlds                     connecting entries
```

Every entry has a **type** that records provenance — who observed it, from where, and when.

---

## 2. Data Flow

### URL Ingest Pipeline

```
URL submitted
  ↓
classify_url() → determines source: x, youtube, github, reddit, or web
  ↓
Source-specific extractor:
  · X/Twitter     → fxtwitter API (free, no auth, returns JSON)
  · YouTube       → oembed + yt-dlp transcript + optional Whisper fallback
  · GitHub        → raw README or GitHub API
  · Reddit        → reddit.com/.json API + Playwright for share link resolution
  · General web   → readability-lxml → markdownify → stdlib fallback
  ↓
Content stored in entries table
  ↓
cli/auto_tag.py     → c-TF-IDF centroid matching → suggested tags
  ↓
lib/embed.py    → all-MiniLM-L6-v2 → 384-dim vector → entries_v0
  ↓
Searchable via FTS5 + vec0
```

---

## 3. Schema

### `entries` — Main table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | Human-readable slug (auto-generated from title) |
| `source_url` | TEXT NOT NULL | Origin URL or `agent:{name}:{type}:{seq}` for memories |
| `title` | TEXT NOT NULL | Searchable title |
| `content` | TEXT NOT NULL | Full extracted content or observation body |
| `tags` | TEXT | JSON array of user-assigned tags |
| `auto_tags` | TEXT | JSON array of LLM/topic-model generated tags |
| `tagged_at` | TIMESTAMP | When auto-tagging ran |
| `media_path` | TEXT | Path to local media file (e.g. YouTube download) |
| `starred` | INTEGER | 0/1 bookmark flag |
| `archived` | INTEGER | 0/1 hidden from default search |
| `entry_type` | TEXT | One of: `bookmark`, `x_thread`, `x_observation`, `youtube`, `reddit`, `github`, `synthesis` |
| `extraction_status` | TEXT | `pending`, `extracted`, `thin`, `dead` |
| `retry_count` | INTEGER | Extraction retry counter (max 3) |
| `source_refs` | TEXT | JSON array of source entry IDs (for synthesis entries) |
| `created_at` | TEXT | ISO 8601 timestamp |
| `modified_at` | TEXT | ISO 8601 timestamp |

### `entries_fts` — FTS5 virtual table

Full-text search index on `title` and `content`. Synchronized via triggers on INSERT, UPDATE, DELETE.

```sql
CREATE VIRTUAL TABLE entries_fts USING fts5(
    title, content,
    content='entries', content_rowid='rowid'
);
```

### `entries_v0` — vec0 vector index

Approximate nearest neighbor (ANN) index for semantic search. 384-dimensional float32 vectors.

```sql
CREATE VIRTUAL TABLE entries_v0 USING vec0(
    embedding float[384]
);
```

---

## 4. Entry Types

| Type | Source | Content Profile |
|------|--------|-----------------|
|| `bookmark` | General web page | Full article text via readability |
|| `x_thread` | X/Twitter thread (≥200 chars) | Multi-tweet thread assembled as one entry |
|| `x_observation` | X/Twitter post (<200 chars) | Single short post or hot take |
|| `youtube` | YouTube video | Video metadata + transcript (yt-dlp/Whisper) |
|| `reddit` | Reddit post | Post body via Reddit JSON API |
|| `github` | GitHub repository | README content or API metadata |
|| `synthesis` | Pliny-generated | Cross-pollination insight from ≥2 entries |

---

## 5. Extraction Pipeline

### Source Classification (`url_ingest.py`)

`classify_url()` inspects the domain and routes to the correct extractor:

```python
def classify_url(url: str) -> str:
    if "x.com" in host or "twitter.com" in host: return "x"
    if "youtube.com" in host or "youtu.be" in host: return "youtube"
    if "github.com" in host: return "github"
    if "reddit.com" in host: return "reddit"
    return "web"
```

### Per-Source Extractors

**X/Twitter** — `extract_x()`
- Uses `api.fxtwitter.com` (free, no auth) as primary
- Falls back to `api.vxtwitter.com`
- Extracts author, text, thread assembly
- Returns JSON with `{title, content, status}`

**YouTube** — `extract_youtube()`
- Gets video ID from any URL format (watch, short, youtu.be)
- Fetches metadata via YouTube oembed API
- Attempts transcript extraction via `yt-dlp --write-auto-sub`
- Falls back to local Whisper (faster-whisper) transcription on downloaded audio
- Downloads video to `media/youtube/{id}.mp4` (720p max)

**GitHub** — `extract_github()`
- Attempts raw README (main → master fallback)
- Falls back to GitHub API for repo description

**Reddit** — `extract_reddit()`
- Uses Reddit's `.json` API (free, no auth)
- Rate-limited to 5s between calls
- Resolves share links (`/s/`) via Playwright

**General Web** — `extract_web()`
- Uses `readability-lxml` for article extraction
- Converts HTML to Markdown via `markdownify`
- Falls back to regex-based HTML tag stripping

### Entry Type Determination

```python
def entry_type_for_url(url: str, content_len: int) -> str:
    cls = classify_url(url)
    if cls == "x":
        return "x_observation" if content_len < 200 else "x_thread"
    return cls  # youtube, github, reddit, web → 'bookmark'
```

### X Teaser Enrichment (`batch_enrich_v2.py`)

A separate cron pipeline identifies X entries that are still short (<200 chars) after initial extraction and re-fetches them with DuckDuckGo's text-only view for full content. Runs daily at 09:00 UTC.

---

## 6. Search

### QueryEngine (`src/query.py`)

The `QueryEngine` class provides three search modes, all accessible via CLI and programmatic API.

#### FTS5 — Full-Text Search

Uses SQLite's FTS5 for keyword matching with BM25 ranking. Returns highlighted snippets.

```python
engine.search_fts("quantum computing", limit=20)
```

SQL: `SELECT ... FROM entries_fts JOIN entries ... MATCH ? ORDER BY rank`

#### vec0 — Semantic (Vector) Search

Embeds the query text with all-MiniLM-L6-v2, then searches the vec0 ANN index for nearest neighbors by cosine distance.

```python
engine.search_vec("machine learning concepts", limit=20)
```

#### Hybrid — RRF Fusion

Reciprocal Rank Fusion: runs FTS5 and vec0 searches independently (with expanded limit), then merges results using RRF scores. Each result's rank from each method contributes `1/(rank + 60)` to a combined score.

```python
engine.hybrid("deep learning for trading", limit=20)
```

### Tag Filtering

Tags are stored as JSON arrays in the `auto_tags` column. Filtering uses SQL `LIKE` with JSON value patterns:

```sql
WHERE auto_tags LIKE '%"technical-analysis"%'
```

### Search Parameters (via HTTP API)

| Parameter | Purpose |
|-----------|---------|
| `q` | FTS5 full-text search query |
| `tags` | Comma-separated tag filter |
| `entry_type` | Filter by type: `bookmark`, `synthesis`, etc. |
| `source` | Filter by source domain: `x`, `youtube`, `github` |
| `date_from` / `date_to` | ISO date range |
| `sort` | `date_desc` (default), `date_asc`, `size_desc`, `title_asc` |
| `page` / `per_page` | Pagination |

### Related Entries

`GET /api/entry/{entry_id}/related` — uses vec0 vector similarity to find semantically close entries, with tag-overlap fallback and shared-concept annotation.

---

## 7. Synthesis (`src/cron/synthesize.py`)

The cross-pollination agent discovers novel connections between entries. Pipeline:

```
  1. Load recent entries (last 7 days) with embeddings + tags
  2. Pairwise cosine similarity via numpy (matrix @ matrix.T)
  3. Keep pairs in "sweet spot": 0.30 ≤ similarity ≤ 0.75
  4. Reject pairs with >60% tag overlap (same topic — boring)
  5. Dedup against existing synthesis entries (source_refs pairs)
  6. LLM judge (qwen2.5:7b): "Would synthesizing these produce novel insight?"
     → Filters ~70-80% of candidates
  7. LLM write: generate synthesis text with source title references
  8. Save as entry_type='synthesis' with source_refs linking to source entries
```

Key parameters:
- `--days 7` — lookback window
- `--max-syntheses 15` — cap per run
- `--max-pairs 200` — candidate pairs to judge
- Config: `SIMILARITY_MIN=0.30`, `SIMILARITY_MAX=0.75`, `TAG_OVERLAP_MAX=0.60`

The numpy-accelerated pairwise similarity handles the full `n × n` matrix in seconds for typical corpus sizes.

---

## 8. Cron Jobs

| Schedule | Job | Command | Purpose |
|----------|-----|---------|---------|
|| Daily 09:00 UTC | Extraction retry | `cron/extract_cron.py --max 50` | Retry pending extractions, mark dead after 3 failures |
|| Daily 10:00 UTC | Karakeep import | `ingest/karakeep_import.py --batch 50` | Import new bookmarks from Karakeep |
|| Sunday 12:00 UTC | Synthesis | `cron/synthesize.py --days 7 --max-syntheses 10` | Weekly cross-pollination |

### Extraction Retry Strategy (`src/cron/extract_cron.py`)

- Skips `x_observation` entries (inherently short)
- Processes oldest pending entries first
- Batches up to 50/day with 3-second delays between extractions
- 480-second safety timeout
- After 3 retries: marks entry as `dead`

---

## 9. Dashboard (`ui/server.py`)

A FastAPI server on **port 3131** serving a vanilla HTML/CSS/JS single-page application.

### Endpoints

||| Route | Description |
|||-------|-------------|
||| `GET /` | Serves `index.html` |
||| `GET /api/entries` | Paginated search with filters |
||| `GET /api/entry/{id}` | Full entry detail |
||| `GET /api/entry/{id}/related` | Vector-similar related entries |
||| `POST /api/entry/{id}/star` | Toggle star |
||| `GET /api/tags` | Tag frequency list |
||| `GET /api/tags/related/{tag}` | Co-occurring tags |
||| `GET /api/tags/graph` | Tag co-occurrence graph data |
||| `POST /api/ask` | LLM Q&A on your corpus (Ollama) |
||| `GET /api/similarity/search` | Similarity explorer picker |
||| `POST /api/ingest/add-url` | Queue URL for ingestion |
||| `POST /api/pipeline/*` | Run enrichment, retag, synthesize |
||| `POST /api/search/vector` | Hybrid search endpoint |
||| `GET /api/saved-queries` | Saved queries CRUD |
||| `POST /api/webhooks/karakeep` | Karakeep webhook receiver |
||| `WS /ws` | WebSocket for real-time pipeline events |

### Frontend

- Dark theme (GitHub-dark inspired)
- Tabbed views: Search, Graph, Pipeline, Starred, Saved Queries
- D3.js tag co-occurrence graph
- Real-time pipeline event updates via WebSocket
- Command bar with keyboard shortcuts

---

## 10. Technical Stack

### Storage

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Main database | SQLite (WAL mode) | All entries, metadata, provenance |
| Full-text search | FTS5 (embedded SQLite) | Keyword search with BM25 ranking |
| Vector index | sqlite-vec (vec0) | 384-dim ANN search |
| Embedding model | all-MiniLM-L6-v2 | 384-dim normalized embeddings |

### Embedding (`lib/embed.py`)

- **Primary**: ONNX Runtime via `optimum.onnxruntime` — ~88MB model, fast inference
- **Fallback**: PyTorch via `sentence-transformers` 
- **Output**: L2-normalized 384-dim float32 vectors
- **Max length**: 256 tokens (truncated)
- **Storage**: JSON array string in vec0 index

### Auto-Tagging (`src/cli/auto_tag.py`)

- `HashingVectorizer` (5000 features) for memory-efficient text vectorization
- `KMeans` clustering with silhouette-score-optimized K (8–25)
- Cluster centroids persisted as JSON for zero-shot tag prediction on new entries
- Tag overlap computed via Jaccard-like intersection/min ratio

### LLM

| Component | Model | Provider |
|-----------|-------|----------|
| Auto-tagging | qwen2.5:7b | Ollama (localhost:11434) |
| Synthesis judge | qwen2.5:7b | Ollama |
| Synthesis writer | qwen2.5:7b | Ollama |
| Ask Pliny (Q&A) | qwen2.5:7b | Ollama |

### Mathematics

- **Cosine similarity** (pairwise): `numpy` matrix multiplication `matrix @ matrix.T`
- **RRF scoring**: `score = Σ 1/(rank + 60)` for each result across FTS5 and vec0
- **Tag overlap**: `|tags_a ∩ tags_b| / min(|tags_a|, |tags_b|)`
- **Embedding**: mean pooling of last hidden state with L2 normalization

### Project Layout

```
|pliny/
|├── src/
|│   ├── lib/
|│   │   ├── schema.py       SQLite schema + migrations
|│   │   ├── embed.py        ONNX/PyTorch embedding
|│   │   └── paths.py        Path configuration
|│   ├── cli/
|│   │   ├── auto_tag.py     c-TF-IDF clustering + centroid tagging
|│   │   ├── sync.py         Karakeep bidirectional sync
|│   │   ├── reembed.py      Re-embedding stub
|│   │   └── ingest_cli.py   CLI entry point for ingestion
|│   ├── cron/
|│   │   ├── synthesize.py   Cross-pollination synthesis agent
|│   │   ├── extract_cron.py Daily extraction retry cron
|│   │   └── digest.py       Daily digest generator
|│   ├── ingest/
|│   │   ├── url_ingest.py   Source-specific content extraction
|│   │   ├── karakeep_import.py  Karakeep batch import
|│   │   └── batch_enrich_v2.py  X teaser enrichment (pipeline batch)
|│   ├── query.py            QueryEngine: FTS5 + vec0 + hybrid (RRF)
|│   ├── sdk.py              Pliny client SDK for AI agents
|│   └── migrate.py          Schema migrations
|├── ui/
|│   ├── server.py           FastAPI dashboard (port 3131)
|│   └── index.html          Vanilla HTML/CSS/JS frontend
|├── bot/
|│   └── telegram_forward.py Telegram bot integration
|├── docs/
|│   ├── ARCHITECTURE.md     This document
|│   └── GUIDE.md            Complete user guide
|├── data/
|│   └── pliny.db            SQLite database
|├── models/
|│   └── onnx/all-MiniLM-L6-v2/  ONNX model files
|├── media/                  Downloaded media (YouTube, etc.)
|└── scripts/
|    └── export_onnx.py      Model export utility
```
