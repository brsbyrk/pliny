"""YouTube extractor — fetch + format for video metadata and transcripts."""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

from lib.paths import MEDIA_DIR

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    parsed = urlparse(url)
    if "youtu.be" in parsed.netloc:
        return parsed.path.strip("/").split("?")[0]
    if "youtube.com" in parsed.netloc:
        if "/shorts/" in parsed.path:
            return parsed.path.split("/shorts/")[1].split("?")[0].split("/")[0]
        qs = parse_qs(parsed.query)
        return qs.get("v", [None])[0]
    return None


def _fetch_youtube_transcript(video_id: str) -> str | None:
    """Fetch YouTube transcript as plain text via yt-dlp."""
    tmp = tempfile.mktemp(suffix=".vtt", prefix=f"pliny-yt-{video_id}-")
    try:
        subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                "--write-auto-sub",
                "--sub-lang", "en",
                "--convert-subs", "vtt",
                "-o", tmp.replace(".vtt", ""),
                "--quiet",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True, text=True, timeout=120,
        )

        vtt_path = tmp.replace(".vtt", ".en.vtt")
        if not Path(vtt_path).exists():
            vtt_path = tmp.replace(".vtt", ".en.vtt")
            if not Path(vtt_path).exists():
                vtt_path = tmp

        if Path(vtt_path).exists():
            text = _parse_vtt(Path(vtt_path).read_text(encoding="utf-8", errors="replace"))
            Path(vtt_path).unlink(missing_ok=True)
            if text and len(text.strip()) > 20:
                return text.strip()
        return None
    except Exception:
        return None
    finally:
        Path(tmp).unlink(missing_ok=True)
        Path(tmp.replace(".vtt", ".en.vtt")).unlink(missing_ok=True)


def _parse_vtt(vtt_text: str) -> str:
    """Strip VTT timestamps and formatting, return plain text."""
    lines = []
    for line in vtt_text.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if "-->" in line:
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"^\s*>>\s*\w+:\s*", "", line)
        if line:
            lines.append(line)

    deduped = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    return "\n".join(deduped)


def _download_youtube_video(video_id: str) -> str | None:
    """Download YouTube video to Media/youtube/<id>.mp4.

    Returns the absolute path to the downloaded file, or None on failure.
    """
    media_dir = MEDIA_DIR / "youtube"
    media_dir.mkdir(parents=True, exist_ok=True)
    output_path = media_dir / f"{video_id}.mp4"

    if output_path.exists():
        return str(output_path)

    try:
        r = subprocess.run(
            [
                "yt-dlp",
                "-f", "best[height<=720]",
                "-o", str(output_path),
                "--quiet",
                "--no-playlist",
                "--no-warnings",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True, text=True, timeout=300,
        )
        if r.returncode == 0 and output_path.exists():
            return str(output_path)
        return None
    except Exception:
        return None


def _whisper_transcribe(video_id: str, video_path: str) -> str | None:
    """Fallback: extract audio and transcribe with faster-whisper."""
    video_path_obj = Path(video_path)
    if not video_path_obj.exists():
        return None

    audio_path = video_path_obj.with_suffix(".wav")
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-i", str(video_path_obj),
                "-vn", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1",
                "-y", str(audio_path),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0 or not audio_path.exists():
            return None

        if not hasattr(_whisper_transcribe, "_model"):
            from faster_whisper import WhisperModel as _WM
            _whisper_transcribe._model = _WM("base", device="cpu", compute_type="int8")
        segments, _info = _whisper_transcribe._model.transcribe(
            str(audio_path), beam_size=5,
            language="en", vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        text = " ".join(seg.text.strip() for seg in segments)
        if text and len(text.strip()) > 20:
            return text.strip()
        return None
    except Exception:
        return None
    finally:
        audio_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch(url: str) -> dict | None:
    """Fetch raw YouTube video metadata and transcript.

    Returns a dict with video_id, title (from oembed/yt-dlp), author,
    description, transcript, media_path.
    Returns None if the video can't be identified.
    """
    vid = _extract_video_id(url)
    if not vid:
        return None

    result: dict = {"video_id": vid}

    # Step 1: Get metadata via oembed + yt-dlp fallback
    watch_url = f"https://www.youtube.com/watch?v={vid}"
    video_title = ""
    author = ""
    description = ""

    oembed_url = f"https://www.youtube.com/oembed?url={watch_url}&format=json"
    try:
        resp = requests.get(oembed_url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            video_title = data.get("title", "")
            author = data.get("author_name", "")
            description = data.get("description", "") or ""
    except Exception as e:
        logger.debug("youtube oembed parse failed: %s", e)

    if not video_title:
        try:
            title_r = subprocess.run(
                ["yt-dlp", "--print", "title", "--quiet", watch_url],
                capture_output=True, text=True, timeout=30,
            )
            if title_r.returncode == 0 and title_r.stdout.strip():
                video_title = title_r.stdout.strip()
        except Exception as e:
            logger.debug("yt-dlp title fetch failed: %s", e)

    # Step 2: Extract transcript
    transcript = _fetch_youtube_transcript(vid)

    # Step 3: Download video
    media_path = _download_youtube_video(vid)

    # Step 4: Whisper fallback
    whisper_text = None
    if not transcript and vid and media_path:
        try:
            whisper_text = _whisper_transcribe(vid, media_path)
        except Exception as e:
            logger.debug("whisper transcription failed for %s: %s", vid, e)

    result["title"] = video_title
    result["author"] = author
    result["description"] = description
    result["transcript"] = transcript or whisper_text
    result["transcript_source"] = "whisper" if whisper_text else ("ytdlp" if transcript else None)
    result["media_path"] = media_path

    return result


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


def format(raw: dict, url: str) -> dict:
    """Convert raw YouTube data into standard {title, content, status} shape.

    Handles media_path and status encoding (youtube_transcript,
    youtube_whisper, youtube_oembed, etc.).
    """
    video_title = raw.get("title", "")
    author = raw.get("author", "")
    description = raw.get("description", "")
    transcript = raw.get("transcript")
    transcript_source = raw.get("transcript_source")
    media_path = raw.get("media_path")

    # Check if video exists
    if not video_title:
        if not raw.get("video_id"):
            return {"title": None, "content": None, "status": "youtube_no_id"}
        return {"title": None, "content": None, "status": "youtube_unavailable"}

    # Build content
    parts = []
    if video_title:
        parts.append(f"# {video_title}")
    if author:
        parts.append(f"**By:** {author}")

    if transcript:
        parts.append(f"\n## Transcript\n{transcript}")
        if transcript_source == "whisper":
            status = "youtube_whisper"
        else:
            status = "youtube_transcript"
    elif description:
        parts.append(f"\n**Description:** {description}")
        status = "youtube_oembed"
    else:
        status = "youtube_metadata_only"

    content = "\n\n".join(parts) if parts else None

    result: dict = {"title": video_title, "content": content, "status": status}
    if media_path:
        result["media_path"] = media_path
    return result
