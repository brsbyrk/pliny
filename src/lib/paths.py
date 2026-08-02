"""Pliny paths and configuration."""

from __future__ import annotations

import os
from pathlib import Path

# Derive PLINY_ROOT from file location (works when cloned anywhere).
# Override via PLINY_ROOT env var.
_HERE = Path(__file__).resolve().parent.parent.parent  # src/lib/../../.. → project root
PLINY_ROOT = Path(os.getenv("PLINY_ROOT", str(_HERE)))
DATA_DIR = PLINY_ROOT / "data"
DB_PATH = DATA_DIR / "pliny.db"
QUEUES_DIR = DATA_DIR / "queues"
USER_DIR = DATA_DIR / "user"
CENTROIDS_PATH = PLINY_ROOT / "models" / "centroids" / "cluster_centroids.json"
MEDIA_DIR = PLINY_ROOT / "media"

# Vault remains an optional export target
VAULT_CARDS = Path.home() / "vault" / "BBB" / "00-Projects" / "pliny-inbox" / "cards"
