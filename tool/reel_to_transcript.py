#!/usr/bin/env python3
"""Download an Instagram reel, extract audio, and transcribe it with OpenAI Whisper.

Saves the video, audio, and transcript under tool/saves/<shortcode>/.

Requires ffmpeg on PATH and the yt-dlp package:

    pip install yt-dlp

Uses CREATIVE_AGENT_OPENAI_API_KEY or OPENAI_API_KEY from the environment or .env.

Examples:

    python tool/reel_to_transcript.py https://www.instagram.com/reel/SHORTCODE/
    python tool/reel_to_transcript.py URL --cookies-from-browser chrome
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SAVES_DIR = Path(__file__).resolve().parent / "saves"
WHISPER_MODEL = "whisper-1"
WHISPER_MAX_BYTES = 25 * 1024 * 1024
_SHORTCODE = re.compile(
    r"(?:instagram\.com|instagr\.am)/(?:reel|reels|p|tv)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)
_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


def _shortcode(url: str) -> str:
    match = _SHORTCODE.search(url.strip())
    if not match:
        raise SystemExit(
            "Pass a public Instagram reel URL, for example "
            "https://www.instagram.com/reel/SHORTCODE/"
        )
    return match.group(1)


def _require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is not on PATH. Install it, then run this script again.")
    return ffmpeg


def _download(
    url: str,
    save_dir: Path,
    *,
    cookies_from_browser: str | None,
    cookies_file: Path | None,
) -> tuple[Path, str]:
    try:
        import yt_dlp
    except ImportError as exc:
        raise SystemExit("yt-dlp is not installed. Run: pip install yt-dlp") from exc

    for old in save_dir.glob("source.*"):
        old.unlink()

    options: dict = {
        "outtmpl": str(save_dir / "source.%(ext)s"),
        "noplaylist": True,
        "restrictfilenames": True,
        "format": "best[ext=mp4]/best",
        "quiet": False,
        "no_warnings": False,
    }
    if cookies_from_browser:
        options["cookiesfrombrowser"] = (cookies_from_browser,)
    if cookies_file:
        options["cookiefile"] = str(cookies_file)

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)

    title = ""
    if isinstance(info, dict):
        title = str(info.get("title") or "")

    media = [
        path
        for path in save_dir.iterdir()
        if path.is_file() and path.suffix.lower() in _VIDEO_SUFFIXES and path.name.startswith("source.")
    ]
    if not media:
        raise SystemExit(f"Download finished but no video file was written in {save_dir}")
    return media[0], title


def _extract_audio(ffmpeg: str, video_path: Path, audio_path: Path) -> None:
    if audio_path.exists():
        audio_path.unlink()
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        str(audio_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0 or not audio_path.exists():
        detail = (completed.stderr or completed.stdout or "").strip()
        raise SystemExit(f"ffmpeg could not extract audio.\n{detail}")
    size = audio_path.stat().st_size
    if size > WHISPER_MAX_BYTES:
        raise SystemExit(
            f"Audio is {size} bytes. OpenAI Whisper accepts files up to {WHISPER_MAX_BYTES} bytes."
        )


def _transcribe(audio_path: Path, *, language: str | None) -> dict:
    from openai import OpenAI

    from transcript_composer.llm_config import require_openai_api_key

    client = OpenAI(api_key=require_openai_api_key())
    request: dict = {"model": WHISPER_MODEL, "response_format": "verbose_json"}
    if language:
        request["language"] = language
    with audio_path.open("rb") as audio_file:
        result = client.audio.transcriptions.create(file=audio_file, **request)

    segments = []
    for segment in getattr(result, "segments", None) or []:
        if isinstance(segment, dict):
            segments.append(
                {
                    "start": segment.get("start"),
                    "end": segment.get("end"),
                    "text": segment.get("text"),
                }
            )
        else:
            segments.append(
                {
                    "start": getattr(segment, "start", None),
                    "end": getattr(segment, "end", None),
                    "text": getattr(segment, "text", None),
                }
            )
    return {
        "text": (getattr(result, "text", None) or "").strip(),
        "language": getattr(result, "language", None),
        "duration_seconds": getattr(result, "duration", None),
        "segments": segments,
    }


def transcribe_reel(
    url: str,
    *,
    language: str | None = None,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
) -> Path:
    shortcode = _shortcode(url)
    ffmpeg = _require_ffmpeg()
    save_dir = SAVES_DIR / shortcode
    save_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading {shortcode}...")
    video_path, title = _download(
        url,
        save_dir,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
    )
    audio_path = save_dir / "audio.mp3"
    print(f"Extracting audio from {video_path.name}...")
    _extract_audio(ffmpeg, video_path, audio_path)

    print("Transcribing with OpenAI Whisper...")
    transcript = _transcribe(audio_path, language=language)
    payload = {
        "source_url": url.strip(),
        "shortcode": shortcode,
        "title": title,
        "model": WHISPER_MODEL,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video_file": video_path.name,
        "audio_file": audio_path.name,
        **transcript,
    }
    transcript_json = save_dir / "transcript.json"
    transcript_txt = save_dir / "transcript.txt"
    transcript_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    transcript_txt.write_text(payload["text"] + "\n", encoding="utf-8")
    print(f"Saved {transcript_txt}")
    return transcript_txt


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe an Instagram reel with OpenAI Whisper.")
    parser.add_argument("url", help="Public Instagram reel URL")
    parser.add_argument("--language", default=None, help="Spoken language hint, for example en")
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        help="Browser to read Instagram cookies from when the reel requires a login, for example chrome",
    )
    parser.add_argument(
        "--cookies",
        type=Path,
        default=None,
        help="Netscape cookies file exported for instagram.com",
    )
    args = parser.parse_args()
    transcribe_reel(
        args.url,
        language=args.language,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies,
    )


if __name__ == "__main__":
    main()
