"""Configuration helpers for the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class DownloadSettings:
    urls: List[str]
    destination: Path
    jobs: int
    segment_minutes: int
    audio_quality: str
    disable_color: bool
    isolate_vocals: bool = True
    # None means "pick automatically based on available memory" -- see
    # downloader.default_isolate_jobs().
    isolate_jobs: Optional[int] = None

    @property
    def segment_seconds(self) -> int:
        return self.segment_minutes * 60
