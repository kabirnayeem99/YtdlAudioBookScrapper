"""Utility helpers shared across modules."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

DEFAULT_SEGMENT_MINUTES = 20
DEFAULT_AUDIO_QUALITY = "5"  # yt-dlp uses 0(best) to 9(worst); 5 ~= medium


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
    """Lowercase and strip problematic characters while keeping intent."""

    lowered = content.strip().lower()
    lowered = lowered.replace(" ", "_")
    lowered = re.sub(r"[^a-z0-9._-]", "", lowered)
    lowered = re.sub(r"_+", "_", lowered)
    lowered = lowered.strip("._-")
    return lowered or "ytdl_audio"
