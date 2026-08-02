# Pliny — Complete Guide

**Shared knowledge infrastructure for humans and AI agents.** Every bookmark, agent observation, and synthesis lives in one searchable corpus — with full provenance.

- **Dashboard:** `http://localhost:3131`
- **API docs (Swagger):** `http://localhost:3131/docs`
- **API docs (ReDoc):** `http://localhost:3131/redoc`
- **Project root:** `~/workspace/_projects/pliny`

---

## Quick Start

```bash
cd ~/workspace/_projects/pliny

# Launch the dashboard
python3 ui/server.py
# → http://localhost:3131

# Ingest a URL
python3 src/ingest/url_ingest.py https://example.com/article

# Search
python3 src/query.py search "your query"
python3 src/query.py search --mode hybrid "your query"
```

---

## URL Ingestion

Pliny auto-detects the source from the URL and uses the best extractor:

| Source | Extractor | Content |
|--------|-----------|---------|
| `x.com` / `twitter.com` | fxtwitter API (free, no auth) | Thread assembly, author, text |
| `youtube.com` / `youtu.be` | oembed + yt-dlp transcripts | Metadata + auto-subtitles |
| `github.com` | Raw README + GitHub API fallback | README content |
| `reddit.com` | Reddit `.json` API | Post body + comments |
| Any other URL | readability-lxml + markdownify | Full article text |

### Entry Types

|| `bookmark` | General web page | Any non-special URL |
|| `x_thread` | X/Twitter | Content ≥ 200 chars |
|| `x_observation` | X/Twitter | Content < 200 chars |
|| `youtube` | YouTube | Video with transcript |
|| `reddit` | Reddit | Post body |
|| `github` | GitHub repo | README content |
|| `synthesis` | Pliny-generated | Cross-pollination pipeline |

```bash
# CLI ingestion
python3 src/ingest/url_ingest.py <url>

# API ingestion (server must be running)
curl -X POST http://localhost:3131/api/ingest/add-url \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/user/repo"}'
```

---

## Search

Pliny offers three search modes, all accessible via CLI and HTTP API.

### CLI

```bash
# FTS5 full-text search (keyword matching)
python3 src/query.py search "rust async performance"

# Vector/semantic search (concept matching)
python3 src/query.py search --mode vec "machine learning for trading"
# Search the corpus
python3 src/query.py search "your query"
python3 src/query.py hybrid "your query"

# List recent entries
python3 src/query.py list --limit 20

# Get a specific entry by ID
python3 src/query.py get <entry-id>

# List all tags with counts
python3 src/query.py tags
```

### HTTP API

```http
GET /api/entries?q=btc+funding&tags=signal&sort=date_desc
```

| Parameter | Purpose |
|-----------|---------|
| `q` | FTS5 full-text search query |
| `tags` | Comma-separated tag filter |
| `entry_type` | `bookmark`, `synthesis`, etc. |
| `source` | Source domain: `x`, `youtube`, `github` |
| `date_from` / `date_to` | ISO date range |
| `sort` | `date_desc` (default), `date_asc`, `size_desc`, `title_asc` |
| `page` / `per_page` | Pagination |

### Related Entries

```http
GET /api/entry/{entry_id}/related
```
Uses vec0 vector similarity + tag overlap. Shows semantically close entries.

### Ask Pliny (LLM Q&A)

```bash
curl -X POST http://localhost:3131/api/ask \
  -H "Content-Type: application/json" \
  -d '{"q": "What do I know about AI agent memory systems?"}'
```

---

## SDK Reference

The `sdk.Pliny` class provides search and retrieval for agents.

### Constructor

```python
from sdk import Pliny

p = Pliny(
    base_url="http://localhost:3131",  # Default
    timeout=10,                         # HTTP timeout in seconds
)
```

### Methods

| Method | Purpose |
|--------|---------|
| `p.search(q, tags, entry_type, limit)` | Search the corpus |
| `p.get(entry_id)` | Get a single entry by ID |
| `p.ask(q)` | LLM Q&A on your corpus |

---

## Karakeep Bidirectional Sync

Pliny syncs bidirectionally with [Karakeep](https://github.com/karakeep-app/karakeep) (self-hosted bookmark manager).

### Pliny → Karakeep

When any URL is ingested into Pliny (via `ingest_url()`), it's automatically pushed to Karakeep's API. Agent memories (`agent:` sources) are skipped.

Triggered by: `src/sync.py → push_to_karakeep()`

### Karakeep → Pliny

Karakeep sends a webhook `POST` to Pliny when a bookmark is created. Pliny extracts the URL and ingests it.

- Webhook endpoint: `POST /api/webhooks/karakeep` (in Pliny's server)
- Karakeep webhook configured for `created` events → `http://172.17.0.1:3131/api/webhooks/karakeep`
- Duplicates are skipped (checks if URL already exists in Pliny)

### Configuration

The Karakeep API token must be set:
```bash
# In ~/workspace/_projects/pliny/.env
KARAKEEP_KEY="your-api-token"
KARAKEEP_BASE_URL="http://127.0.0.1:3000"
```

The Karakeep `.env` must allow internal hostnames for the webhook:
```bash
CRAWLER_ALLOWED_INTERNAL_HOSTNAMES=172.17.0.1
```

---

## Dashboard

The web dashboard runs on **port 3131** and provides:

- **Search** — FTS5 + vector + hybrid search with tag/type/source filters
- **Graph** — D3.js tag co-occurrence visualization
- **Pipeline** — Real-time extraction and enrichment events
- **Starred** — Favorites
- **Saved Queries** — Persistent query bookmarks

### URL endpoints (dashboard features)

|| Route | Description |
||-------|-------------|
|| `GET /` | Dashboard UI |
|| `GET /api/entries` | Paginated search |
|| `GET /api/entry/{id}` | Entry detail |
|| `GET /api/entry/{id}/related` | Related entries |
|| `GET /api/tags` | Tag frequency list |
|| `GET /api/tags/related/{tag}` | Co-occurring tags |
|| `GET /api/tags/graph` | Graph data for D3.js |
|| `POST /api/ask` | LLM Q&A on your corpus |
|| `POST /api/ingest/add-url` | Queue URL for ingestion |
|| `POST /api/webhooks/karakeep` | Karakeep webhook receiver |
|| `GET /docs` | Swagger UI API docs |
|| `GET /redoc` | ReDoc API docs |

---

## Automation & Crons

### Scheduled Tasks

| Schedule | Job | Command |
|----------|-----|---------|
| Daily 09:00 UTC | Extraction retry | `src/cron/extract_cron.py --max 50` |
| Daily 10:00 UTC | Karakeep import | `src/ingest/karakeep_import.py --batch 50` |
| Sunday 12:00 UTC | Synthesis | `src/cron/synthesize.py --days 7 --max-syntheses 10` |

### Extraction Retry Strategy

- Skips `x_observation` entries (inherently short)
- Processes oldest pending entries first
- Max 50/day, 3-second delays between extractions
- After 3 failures: marks entry as `dead`

### Synthesis Pipeline

Weekly cross-pollination:
1. Load recent entries (7 days) with embeddings + tags
2. Pairwise cosine similarity via numpy
3. Keep pairs in "sweet spot": 0.30 ≤ similarity ≤ 0.75
4. Reject pairs with >60% tag overlap
5. Dedup against existing syntheses
6. LLM judge filters ~70-80% of candidates
7. LLM writes synthesis text
8. Saved as `entry_type='synthesis'` with `source_refs` backlinks

---

## Project Structure

```
pliny/
├── src/
│   ├── lib/
│   │   ├── schema.py        SQLite schema + migrations
│   │   ├── embed.py         ONNX/PyTorch embedding (384-dim)
│   │   └── paths.py         Path configuration
│   ├── cli/
│   │   ├── auto_tag.py      c-TF-IDF clustering + centroid tagging
│   │   ├── sync.py          Karakeep bidirectional sync
│   │   └── reembed.py       Re-embedding stub
│   ├── cron/
│   │   ├── synthesize.py    Cross-pollination synthesis agent
│   │   ├── extract_cron.py  Daily extraction retry
│   │   └── digest.py        Daily digest generator
│   ├── ingest/
│   │   ├── url_ingest.py    Source-specific content extraction
│   │   ├── karakeep_import.py  Karakeep batch import
│   │   └── batch_enrich_v2.py   X teaser enrichment (pipeline batch)
│   ├── query.py             QueryEngine: FTS5 + vec0 + hybrid
│   ├── sdk.py               Pliny SDK for AI agents
│   └── migrate.py           Schema migrations
├── ui/
│   ├── server.py            FastAPI dashboard + all API endpoints
│   └── index.html           Vanilla HTML/CSS/JS frontend
├── docs/
│   ├── GUIDE.md             This document
│   ├── ARCHITECTURE.md      System architecture
│   └── AGENTS.md            Agent integration reference
├── data/
│   ├── pliny.db             SQLite database
│   ├── queues/              Operational state (command, ingest)
│   ├── user/                User data (saved queries)
│   └── models/              ML model artifacts (cluster centroids)
├── models/
│   └── onnx/all-MiniLM-L6-v2/  ONNX model files (88MB)
├── media/
│   └── youtube/             Downloaded YouTube videos
└── AGENTS.md                Agent integration reference
```

---

## API Docs Server

Pliny uses FastAPI, which auto-generates:

- **Swagger UI:** `http://localhost:3131/docs` — interactive API explorer, try endpoints directly
- **ReDoc:** `http://localhost:3131/redoc` — clean, searchable API reference

No additional setup needed. These are always available when the server is running.

---

## Quick Reference

```bash
# Ingest
python3 src/ingest/url_ingest.py <url>
curl -X POST http://localhost:3131/api/ingest/add-url -d '{"url":"..."}'

# Search
python3 src/query.py search "query"
python3 src/query.py search --mode hybrid "query"
curl "http://localhost:3131/api/entries?q=query"

# Dashboard
python3 ui/server.py  # → http://localhost:3131

# API docs
open http://localhost:3131/docs
open http://localhost:3131/redoc

# Synthesis
python3 src/cron/synthesize.py --days 7 --max-syntheses 10
```
