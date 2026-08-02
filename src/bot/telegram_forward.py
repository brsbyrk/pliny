"""
Pliny Telegram Bot — forward a link → auto-ingested into Pliny.

Usage:
    TELEGRAM_BOT_TOKEN=xxx python3 bot/telegram_forward.py

The bot listens for:
- Any message containing a URL → extracts and ingests
- /help → shows usage
- /stats → shows recent ingest stats

Requires: python-telegram-bot, and Pliny's venv activated.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# ── Paths ──────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python3"
INGEST_SCRIPT = ROOT / "src" / "ingest" / "url_ingest.py"

# ── Config ─────────────────────────────────────────────
import dotenv
dotenv.load_dotenv(ROOT / ".env")
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_USER_IDS = set()
raw = os.environ.get("ALLOWED_USER_IDS", "")
if raw:
    ALLOWED_USER_IDS = set(int(x.strip()) for x in raw.split(",") if x.strip())

# Track recently ingested URLs (in-memory, resets on restart)
recent_ingests: list[dict] = []
MAX_RECENT = 20


# ── Helpers ────────────────────────────────────────────

URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _extract_urls(text: str) -> list[str]:
    """Extract all URLs from a text message."""
    return URL_RE.findall(text)


def _ingest_url(url: str) -> dict:
    """Run Pliny's url_ingest.py and return the result."""
    try:
        result = subprocess.run(
            [str(VENV_PYTHON), str(INGEST_SCRIPT), url],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # Parse JSON from output (url_ingest.py prints JSON on last line)
        out_lines = [l for l in stdout.split("\n") if l.strip()]
        if out_lines:
            try:
                data = json.loads(out_lines[-1])
                return {
                    "url": url,
                    "status": "ok",
                    "id": data.get("id", ""),
                    "title": data.get("title", ""),
                    "detail": data.get("status", ""),
                }
            except (json.JSONDecodeError, IndexError):
                pass

        return {
            "url": url,
            "status": "ok" if result.returncode == 0 else "error",
            "output": stdout or stderr or "(no output)",
        }
    except subprocess.TimeoutExpired:
        return {"url": url, "status": "timeout", "detail": "Ingest took >120s"}
    except Exception as e:
        return {"url": url, "status": "error", "detail": str(e)}


def _format_result(r: dict) -> str:
    """Format a single ingestion result for Telegram display."""
    if r["status"] == "ok":
        title = r.get("title", "") or ""
        detail = r.get("detail", "") or ""
        eid = r.get("id", "") or ""
        parts = ["✅ *Saved*"]
        if title:
            parts.append(f"  _{title}_")
        if eid:
            slug = eid[:40] + "…" if len(eid) > 40 else eid
            parts.append(f"  ID: `{slug}`")
        if detail and detail != "(no status)":
            parts.append(f"  _{detail}_")
        return "\n".join(parts)
    elif r["status"] == "timeout":
        return f"⏱ *Timed out* — _{r['url'][:60]}_\n  Ingest took too long."
    elif r["status"] == "duplicate":
        return f"♻️ *Already in Pliny* — _{r.get('title', r['url'][:60])}_"
    elif r["status"] == "dead":
        return f"💀 *Dead content* — _{r.get('detail', 'No content could be extracted')}_"
    else:
        return f"❌ *Failed* — _{r['url'][:60]}_\n  {r.get('detail', 'Unknown error')}"


# ── Handlers ───────────────────────────────────────────

def _is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True  # Allow all if no whitelist
    return user_id in ALLOWED_USER_IDS


async def handle_message(update: Update, context):
    """Handle incoming messages — extract URLs and ingest."""
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    if user and not _is_allowed(user.id):
        await update.message.reply_text("⛔ Not authorized.")
        return

    text = update.message.text
    urls = _extract_urls(text)

    if not urls:
        return  # Silent on non-URL messages

    # Deduplicate URLs
    seen = set()
    unique_urls = []
    for u in urls:
        normalized = u.rstrip("/")
        if normalized not in seen:
            seen.add(normalized)
            unique_urls.append(u)

    if len(unique_urls) == 1:
        await update.message.reply_text("⏳ Ingesting…")
        result = _ingest_url(unique_urls[0])
        recent_ingests.insert(0, result)
        if len(recent_ingests) > MAX_RECENT:
            recent_ingests.pop()
        await update.message.reply_text(
            _format_result(result),
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    else:
        await update.message.reply_text(
            f"⏳ Ingesting {len(unique_urls)} URLs…"
        )
        results = []
        for url in unique_urls:
            result = _ingest_url(url)
            recent_ingests.insert(0, result)
            results.append(result)
            time.sleep(0.5)  # Brief pause between ingests
        if len(recent_ingests) > MAX_RECENT:
            recent_ingests[:] = recent_ingests[:MAX_RECENT]

        summary = "\n\n".join(_format_result(r) for r in results)
        await update.message.reply_text(
            summary,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )


async def handle_help(update: Update, context):
    """Send help message."""
    await update.message.reply_text(
        "🤖 *Pliny Telegram Bot*\n\n"
        "Forward me any link and I'll save it to Pliny.\n\n"
        "*Commands:*\n"
        "  /help — this message\n"
        "  /stats — recent ingest stats\n\n"
        "Or just send/forward any message with a URL.",
        parse_mode="Markdown",
    )


async def handle_stats(update: Update, context):
    """Show recent ingest stats."""
    if not recent_ingests:
        await update.message.reply_text(
            "No ingests since last restart.",
            parse_mode="Markdown",
        )
        return

    ok_count = sum(1 for r in recent_ingests if r["status"] == "ok")
    fail_count = sum(1 for r in recent_ingests if r["status"] not in ("ok",))
    lines = [
        f"📊 *Recent ingests* (last {len(recent_ingests)})",
        f"  ✅ {ok_count} successful",
        f"  ❌ {fail_count} failed",
        "",
    ]
    for r in recent_ingests[:5]:
        status_icon = "✅" if r["status"] == "ok" else "❌"
        title = r.get("title", r.get("detail", r["url"][:50]))
        lines.append(f"{status_icon} _{title[:60]}_")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


# ── Main ───────────────────────────────────────────────

def main():
    if not TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set.", file=sys.stderr)
        print("   Usage: TELEGRAM_BOT_TOKEN=xxx python3 bot/telegram_forward.py", file=sys.stderr)
        sys.exit(1)

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("stats", handle_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Pliny Telegram Bot starting...")
    print(f"   Allowed users: {list(ALLOWED_USER_IDS) if ALLOWED_USER_IDS else 'anyone'}")
    print("   Press Ctrl+C to stop.")
    print()

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
