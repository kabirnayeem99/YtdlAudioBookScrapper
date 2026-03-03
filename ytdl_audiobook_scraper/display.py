"""Terminal display helpers for monitoring parallel jobs."""

from __future__ import annotations

import asyncio
import shutil
import sys
from collections import deque
from typing import Deque, List, MutableSequence

from .jobs import Job

try:
    import curses
except ImportError:  # pragma: no cover - depends on OS support
    curses = None

STATE_STYLES = {
    "pending": (" ..", "queued"),
    "downloading": ("==>", "download"),
    "renaming": (" ->", "rename"),
    "speeding": (" >>", "speedup"),
    "splitting": (" ::", "split"),
    "completed": ("[ok]", "done"),
    "error": ("[!!]", "error"),
}


def truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return "." * width
    return text[: width - 3] + "..."


def colorize(text: str, status: str, *, disable: bool) -> str:
    if disable:
        return text
    palette = {
        "completed": "\x1b[32m",
        "downloading": "\x1b[36m",
        "speeding": "\x1b[34m",
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
    """Terminal UI with live status updates and URL input while jobs run."""

    def __init__(self, jobs: MutableSequence[Job], *, disable_color: bool = False) -> None:
        self.jobs = jobs
        self.disable_color = disable_color
        self._lines_drawn = 0
        self._stopped = asyncio.Event()
        self._submitted_urls: Deque[str] = deque()
        self._input_buffer = ""
        self._notice = "Paste URL and press Enter to queue it."

    def stop(self) -> None:
        self._stopped.set()

    def drain_submitted_urls(self) -> List[str]:
        queued = list(self._submitted_urls)
        self._submitted_urls.clear()
        return queued

    async def run(self) -> None:
        if self._supports_curses_ui():
            await self._run_curses_ui()
        else:
            await self._run_plain_ui()

    async def _run_plain_ui(self) -> None:
        hide_cursor()
        try:
            while not self._stopped.is_set():
                self._draw_plain()
                await asyncio.sleep(0.2)
        finally:
            self._draw_plain()
            show_cursor()

    def _draw_plain(self) -> None:
        lines: List[str] = []
        width = shutil.get_terminal_size((80, 20)).columns
        for job in self.jobs:
            line = self._format_job_line(job, width)
            lines.append(colorize(line, job.status, disable=self.disable_color))

        if self._lines_drawn:
            sys.stdout.write(f"\x1b[{self._lines_drawn}F")
            sys.stdout.write("\x1b[J")
        for line in lines:
            sys.stdout.write(line + "\n")
        if not lines:
            sys.stdout.write("Waiting for jobs...\n")
        sys.stdout.flush()
        self._lines_drawn = max(1, len(lines))

    def _supports_curses_ui(self) -> bool:
        if curses is None:
            return False
        return sys.stdin.isatty() and sys.stdout.isatty()

    async def _run_curses_ui(self) -> None:
        if curses is None:
            await self._run_plain_ui()
            return

        screen = curses.initscr()
        curses.noecho()
        curses.cbreak()
        screen.keypad(True)
        screen.nodelay(True)

        has_colors = False
        if not self.disable_color and curses.has_colors():
            has_colors = True
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                has_colors = False
            if has_colors:
                curses.init_pair(1, curses.COLOR_CYAN, -1)  # downloading
                curses.init_pair(2, curses.COLOR_MAGENTA, -1)  # renaming
                curses.init_pair(3, curses.COLOR_BLUE, -1)  # speeding
                curses.init_pair(4, curses.COLOR_YELLOW, -1)  # splitting
                curses.init_pair(5, curses.COLOR_GREEN, -1)  # completed
                curses.init_pair(6, curses.COLOR_RED, -1)  # error

        try:
            while not self._stopped.is_set():
                self._capture_curses_input(screen)
                self._draw_curses(screen, has_colors=has_colors)
                await asyncio.sleep(0.1)
        finally:
            screen.keypad(False)
            curses.nocbreak()
            curses.echo()
            curses.endwin()

    def _capture_curses_input(self, screen: "curses.window") -> None:
        if curses is None:
            return

        while True:
            try:
                key = screen.get_wch()
            except curses.error:
                break

            if key in ("\n", "\r"):
                self._submit_buffer()
                continue

            if key in ("\b", "\x7f") or key == curses.KEY_BACKSPACE:
                self._input_buffer = self._input_buffer[:-1]
                continue

            if key == curses.KEY_RESIZE:
                continue

            if isinstance(key, str) and key.isprintable():
                self._input_buffer += key

    def _submit_buffer(self) -> None:
        text = self._input_buffer.strip()
        self._input_buffer = ""
        if not text:
            return
        self._submitted_urls.append(text)
        self._notice = f"Queued: {truncate(text, 70)}"

    def _draw_curses(self, screen: "curses.window", *, has_colors: bool) -> None:
        if curses is None:
            return

        screen.erase()
        height, width = screen.getmaxyx()
        if height < 3 or width < 20:
            return

        completed = sum(1 for job in self.jobs if job.status == "completed")
        failed = sum(1 for job in self.jobs if job.status == "error")
        running = sum(
            1
            for job in self.jobs
            if job.status in {"downloading", "renaming", "speeding", "splitting"}
        )
        queued = sum(1 for job in self.jobs if job.status == "pending")
        header = (
            f"YtdlAudioBook TUI | Total {len(self.jobs)} | Running {running} "
            f"| Queued {queued} | Done {completed} | Failed {failed}"
        )
        screen.addnstr(0, 0, truncate(header, width), width)

        rows_for_jobs = max(0, height - 3)
        start = max(0, len(self.jobs) - rows_for_jobs)
        for row, job in enumerate(self.jobs[start : start + rows_for_jobs], start=1):
            line = self._format_job_line(job, width)
            style = self._status_style(job.status, has_colors=has_colors)
            screen.addnstr(row, 0, truncate(line, width), width, style)

        prompt = f"URL> {self._input_buffer}"
        notice = self._notice
        screen.addnstr(height - 2, 0, truncate(prompt, width), width)
        screen.addnstr(height - 1, 0, truncate(notice, width), width)
        screen.refresh()

    def _status_style(self, status: str, *, has_colors: bool) -> int:
        if curses is None or not has_colors:
            return 0
        mapping = {
            "downloading": curses.color_pair(1),
            "renaming": curses.color_pair(2),
            "speeding": curses.color_pair(3),
            "splitting": curses.color_pair(4),
            "completed": curses.color_pair(5),
            "error": curses.color_pair(6),
        }
        return mapping.get(status, 0)

    def _format_job_line(self, job: Job, width: int) -> str:
        prefix, stage = STATE_STYLES.get(job.status, ("??", job.status))
        base = f"[{job.index}/{job.total}] {prefix} {stage:<9} {job.label()}"
        message = job.message
        if not message:
            return base
        remaining = max(0, width - len(base) - 5)
        snippet = truncate(message, remaining)
        if not snippet:
            return base
        return f"{base} :: {snippet}"
