# ── Pliny — Shared Knowledge Infrastructure ──
# Multi-stage build: compile deps separate from runtime

# ──── Stage 1: Builder ────
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

# System deps for building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy

# Install project dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source
COPY src/ ./src/
COPY tests/ ./tests/
RUN uv sync --frozen --no-dev


# ──── Stage 2: Runtime ────
FROM python:3.11-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="Pliny"
LABEL org.opencontainers.image.description="Shared knowledge infrastructure for humans and AI agents"
LABEL org.opencontainers.image.source="https://github.com/brsbyrk/pliny"

# Runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    yt-dlp \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create pliny user (non-root)
RUN useradd --create-home --shell /bin/bash pliny

WORKDIR /home/pliny

# Copy venv from builder
COPY --from=builder --chown=pliny:pliny /build/.venv /home/pliny/.venv
COPY --from=builder --chown=pliny:pliny /build/src /home/pliny/src

# Copy project metadata
COPY --chown=pliny:pliny pyproject.toml README.md ./

# Create data and model directories
RUN mkdir -p /home/pliny/data /home/pliny/models/onnx && \
    chown -R pliny:pliny /home/pliny/data /home/pliny/models

USER pliny

ENV PATH="/home/pliny/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PLINY_ROOT=/home/pliny
ENV PLINY_HOST=0.0.0.0
ENV PLINY_PORT=3131

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:3131/api/stats')" || exit 1

EXPOSE 3131

VOLUME ["/home/pliny/data", "/home/pliny/models"]

CMD ["python3", "src/dashboard/server.py"]
