"""Route modules for Pliny Dashboard.

Each module exposes an APIRouter instance named `router`.
Import them here for convenience.
"""

from .entries import router as entries_router
from .tags import router as tags_router
from .search import router as search_router
from .subscriptions import router as subscriptions_router
from .ingest import router as ingest_router
from .pipeline import router as pipeline_router
from .stats import router as stats_router

__all__ = [
    "entries_router",
    "tags_router",
    "search_router",
    "subscriptions_router",
    "ingest_router",
    "pipeline_router",
    "stats_router",
]
