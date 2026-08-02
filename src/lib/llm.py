"""Shared LLM client for Pliny — DeepSeek chat API."""

import json
import logging
import os
import urllib.request
from pathlib import Path
from dotenv import load_dotenv
from lib.config import LLM_API_URL, LLM_MODEL

logger = logging.getLogger(__name__)

# Load once at import time
ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")


def call_llm(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 512,
    temperature: float = 0.3,
) -> str:
    """Call DeepSeek chat API and return response text.

    Args:
        system_prompt: System-level instruction
        user_prompt: User message content
        max_tokens: Max tokens in response (default 512)
        temperature: Sampling temperature (default 0.3)

    Returns:
        Response text string, or empty string on failure/missing key.
    """
    if not DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY not configured")
        return ""

    payload = json.dumps({
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(
        LLM_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode())
        choices = result.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "").strip()
