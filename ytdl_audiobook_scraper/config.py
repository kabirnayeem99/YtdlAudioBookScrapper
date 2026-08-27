"""Configuration helpers for the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass(frozen=True)
class DownloadSettings:
    urls: List[str]
    destination: Path
    jobs: int
    segment_minutes: int
    audio_quality: str
    disable_color: bool
    isolate_vocals: bool = True
    isolate_jobs: int = 4

    @property
    def segment_seconds(self) -> int:
        return self.segment_minutes * 60
