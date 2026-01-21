"""Job model definitions used by the downloader."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Job:
    index: int
    total: int
    url: str
    base_dir: Path
    segment_seconds: int
    audio_quality: str
    display_name: str = field(default_factory=str)
    status: str = "pending"
    message: str = "queued"
    output_dir: Optional[Path] = None
    error: Optional[str] = None

    def label(self) -> str:
        return self.display_name or self.url
