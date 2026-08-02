# AGENTS.md — Pliny Knowledge Base

Pliny is a searchable knowledge base of human-saved content (bookmarks, articles, YouTube videos, threads). Agents can search and retrieve content via the HTTP API and SDK.

## Search API

```http
GET /api/entries?q=<query>&tags=<tags>&entry_type=<type>&page=1&per_page=24
```

Parameters: `q` (FTS5 query), `tags` (comma-separated), `entry_type` (bookmark, youtube, x_thread, etc.), `date_from`/`date_to`, `sort`, `page`/`per_page`.

Full documentation at `http://localhost:3131/docs`.

## Python SDK

```python
from sdk import Pliny

p = Pliny()

# Search
results = p.search(q="AI agents", limit=10)
for entry in results:
    print(f"{entry['title']} ({entry['created_at']})")

# Get single entry
entry = p.get("entry-id-123")
print(entry["title"], entry["content"][:200])

# Ask (LLM Q&A on your corpus)
answer = p.ask("What do I know about reinforcement learning?")
print(answer)
```

## CLI

```bash
python3 src/query.py search "your query"
python3 src/query.py hybrid "your query" --limit 20
python3 src/query.py list --limit 50
python3 src/query.py get <entry-id>
```

## Quick Reference

```bash
curl http://localhost:3131/api/entries?q=trading+systems
python3 src/query.py hybrid "deep learning" --limit 10
```
