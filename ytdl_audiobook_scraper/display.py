"""Terminal display helpers for monitoring parallel jobs."""

from __future__ import annotations

import asyncio
import shutil
import sys
from typing import List, MutableSequence

from .jobs import Job

STATE_STYLES = {
    "pending": (" ..", "queued"),
    "downloading": ("==>", "download"),
    "renaming": (" ->", "rename"),
    "splitting": (" ::", "split"),
    "completed": ("[ok]", "done"),
    "error": ("[!!]", "error"),
}


def truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return "…"
    return text[: width - 1] + "…"


def colorize(text: str, status: str, *, disable: bool) -> str:
    if disable:
        return text
    palette = {
        "completed": "\x1b[32m",
        "downloading": "\x1b[36m",
        "splitting": "\x1b[33m",
        "renaming": "\x1b[35m",
        "error": "\x1b[31m",
    }
    color = palette.get(status)
    if not color:
        return text
    return f"{color}{text}\x1b[0m"


def hide_cursor() -> None:
    sys.stdout.write("\x1b[?25l")
    sys.stdout.flush()


def show_cursor() -> None:
    sys.stdout.write("\x1b[?25h")
    sys.stdout.flush()


class LivePrinter:
    """Minimal `top` style refresher showing status per job."""

    def __init__(self, jobs: MutableSequence[Job], *, disable_color: bool = False) -> None:
        self.jobs = jobs
        self.disable_color = disable_color
        self._lines_drawn = 0
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        hide_cursor()
        try:
            while not self._stopped.is_set():
                self.draw()
                await asyncio.sleep(0.2)
        finally:
            self.draw()
            show_cursor()

    def stop(self) -> None:
        self._stopped.set()

    def draw(self) -> None:
        lines: List[str] = []
        width = shutil.get_terminal_size((80, 20)).columns
        for job in self.jobs:
            prefix, stage = STATE_STYLES.get(job.status, ("??", job.status))
            base = f"[{job.index}/{job.total}] {prefix} {stage:<9} {job.label()}"
            message = job.message
            if message:
                remaining = max(0, width - len(base) - 5)
                snippet = truncate(message, remaining)
                if snippet:
                    base = f"{base} :: {snippet}"
            lines.append(colorize(base, job.status, disable=self.disable_color))

        if self._lines_drawn:
            sys.stdout.write(f"\x1b[{self._lines_drawn}F")
            sys.stdout.write("\x1b[J")
        for line in lines:
            sys.stdout.write(line + "\n")
        sys.stdout.flush()
        self._lines_drawn = len(lines)
