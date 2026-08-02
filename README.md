# Pliny

**Personal knowledge base.** One searchable corpus for bookmarks, articles, YouTube videos, threads, and more.

**Dashboard:** `http://localhost:3131`
**API docs:** `http://localhost:3131/docs` (Swagger)

---

## Why Pliny

Existing tools are silos:
- **Bookmark managers** (Raindrop, Karakeep) — human content only
- **Vector databases** (Chroma, Qdrant) — raw storage, no pipeline

Pliny extracts, tags, embeds, and indexes everything into one searchable SQLite database with FTS5 full-text search and vector similarity.

---

## Key Capabilities

**Ingest** — URLs auto-detected by source (X, YouTube, GitHub, Reddit, web). Source-specific extractors for each.

**Search** — Hybrid FTS5 + vector embeddings (384-dim ANN). Filter by type, tag, source, date range. Sort by date, size, title.

**Karakeep Sync** — Bidirectional sync. Pliny pushes ingested URLs to Karakeep; Karakeep bookmarks appear in Pliny via webhook.

**Synthesis** — Weekly cross-pollination agent finds complementary entry pairs, generates novel insight, saves with source backlinks.

---

## Quick Start

### Docker (recommended)

```bash
# Clone and start
git clone https://github.com/brsbyrk/pliny.git
cd pliny
cp .env.example .env   # add your DEEPSEEK_API_KEY

docker compose up -d    # → http://localhost:3131

# Optional: cron scheduler for nightly synthesis + extraction
docker compose --profile cron up -d pliny-cron
```

### Local

```bash
cd ~/workspace/pliny

# Install dependencies
uv sync

# Launch dashboard
python3 src/dashboard/server.py     # → http://localhost:3131

# Ingest a URL
python3 src/cli/ingest_cli.py https://example.com/article

# Search
python3 src/query.py search "your query"
python3 src/query.py hybrid "your query"
```

### RSS Feed Monitor

```bash
# One-shot: poll feeds from feeds.txt
python3 src/ingest/rss.py feeds.txt --once

# Continuous monitoring (1h interval)
python3 src/ingest/rss.py feeds.txt

# Add a single feed
python3 src/ingest/rss.py --url https://simonwillison.net/atom/everything/ --once
```

---

## Entry Types

| Type | Source | Content |
|------|--------|---------|
| `bookmark` | General web page | Full article via readability |
| `x_thread` | X/Twitter (≥200 chars) | Multi-tweet thread |
| `x_observation` | X/Twitter (<200 chars) | Short post |
| `youtube` | YouTube video | Transcript via yt-dlp |
| `reddit` | Reddit post | Post body |
| `github` | GitHub repository | README content |
| `synthesis` | Pliny-generated | Cross-pollination insight |

---

## Architecture

| Layer | Component | Technology |
|-------|-----------|------------|
| Storage | SQLite + FTS5 + vec0 | Local, portable |
| Embedding | all-MiniLM-L6-v2 | ONNX Runtime (88MB) |
| Search | QueryEngine | Hybrid FTS + vector |
| Ingest | url_ingest.py | Source-specific extractors |
| Tagging | auto_tag.py | c-TF-IDF clustering |
| Sync | sync.py | Karakeep bidirectional |
| Synthesis | synthesize.py | LLM cross-pollination |
| Dashboard | FastAPI + vanilla HTML | Port 3131 |

---

## For Agents

Agents can search Pliny's corpus via the HTTP API or Python SDK. See [AGENTS.md](AGENTS.md).

---

## Quick Reference

```bash
# Ingest
python3 src/cli/ingest_cli.py <url>
curl -X POST http://localhost:3131/api/ingest/add-url -d '{"url":"..."}'

# Search
python3 src/query.py search "query"
python3 src/query.py hybrid "query"
curl "http://localhost:3131/api/entries?q=query"

# Dashboard
python3 src/dashboard/server.py  # → http://localhost:3131

# API docs
open http://localhost:3131/docs

# Synthesis
python3 src/cron/synthesize.py --days 7 --max-syntheses 10
```
