"""Shared LLM API configuration for Pliny."""

from __future__ import annotations

import os

# LLM API base URL. Default: https://api.deepseek.com (OpenAI-compatible).
# Override via LLM_BASE_URL env var (e.g. for local LLM proxies).
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
LLM_API_URL = f"{LLM_BASE_URL}/chat/completions"
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
