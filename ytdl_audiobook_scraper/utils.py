"""Utility helpers shared across modules."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

DEFAULT_SEGMENT_MINUTES = 20
DEFAULT_AUDIO_QUALITY = "6"  # yt-dlp uses 0(best) to 10(worst); optimized for speech


def ensure_dependency(binary: str) -> None:
    """Ensure external binaries like yt-dlp/ffmpeg are available."""

    if shutil.which(binary) is None:
        raise RuntimeError(f"Missing required dependency: {binary} (check PATH)")


def default_download_dir() -> Path:
    """Resolve the destination directory, honoring the DOWNLOADS env override."""

    download_env = os.environ.get("DOWNLOADS")
    if download_env:
        return Path(download_env).expanduser()
    return (Path.home() / "Downloads").expanduser()


def normalize_name(content: str) -> str:
    cleaned = content.strip()
    cleaned = cleaned.replace(" ", "_").replace("-", "_").replace("/", "_").replace("\\", "_")
    cleaned = re.sub(r"[^a-zA-Z0-9ঀ-৿._]", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)
    cleaned = cleaned.strip("._")
    return cleaned or "ytdl_audio"
