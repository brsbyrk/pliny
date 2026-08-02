"""
Pliny Dashboard — Local web dashboard for Pliny's bookmark database.

Usage:
    cd ~/workspace/_projects/pliny && python3 src/dashboard/server.py

Then open http://localhost:3131
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv
from lib.schema import get_db as _schema_get_db
from lib.paths import DB_PATH, PLINY_ROOT
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from dashboard.routes import (
    entries_router,
    tags_router,
    search_router,
    subscriptions_router,
    ingest_router,
    pipeline_router,
    stats_router,
)

# ── App ───────────────────────────────────────

app = FastAPI(title="Pliny Dashboard — search, explore, graph, pipeline")

HERE = Path(__file__).resolve().parent

# ── Schema migrations on startup ──
_schema_get_db(DB_PATH).close()

# ── Static files ──────────────────────────────

app.mount("/static", StaticFiles(directory=str(HERE)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = HERE / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text())
    return HTMLResponse("<h1>Pliny Dashboard</h1><p>index.html not found</p>")


# ── Mount route modules ───────────────────────

app.include_router(entries_router)
app.include_router(tags_router)
app.include_router(search_router)
app.include_router(subscriptions_router)
app.include_router(ingest_router)
app.include_router(pipeline_router)
app.include_router(stats_router)


if __name__ == "__main__":
    import os
    import socket

    import uvicorn

    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = "192.168.1.105"
    pliny_host = os.getenv("PLINY_HOST", "0.0.0.0")
    pliny_port = int(os.getenv("PLINY_PORT", "3131"))
    print("╔══════════════════════════════════════════════════╗")
    print(f"║  Pliny Dashboard — http://{local_ip}:{pliny_port}               ║")
    print(f"║  API docs  — http://{local_ip}:{pliny_port}/docs          ║")
    print("║                                                   ║")
    print("║  Reachable from any device on your LAN            ║")
    print("╚══════════════════════════════════════════════════╝")
    uvicorn.run(app, host=pliny_host, port=pliny_port)
