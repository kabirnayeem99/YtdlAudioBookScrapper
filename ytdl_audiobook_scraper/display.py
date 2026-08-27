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
except ImportError:  # pragma: no cover
    curses = None

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
ACTIVE_STATES  = {"downloading", "isolating", "speeding", "splitting"}

STATE_LABELS = {
    "pending":     "queued",
    "downloading": "download",
    "isolating":   "isolate",
    "speeding":    "speedup",
    "splitting":   "split",
    "ready":       "ready",
    "completed":   "done",
    "error":       "error",
}

STATE_ICONS = {
    "pending":   "◦",
    "ready":     "◆",
    "completed": "✓",
    "error":     "✗",
}

# curses color pair IDs
_CP_DOWNLOAD = 1
_CP_ISOLATE  = 2
_CP_SPEED    = 3
_CP_SPLIT    = 4
_CP_DONE     = 5
_CP_ERROR    = 6
_CP_HEADER   = 7
_CP_DIM      = 8
_CP_INPUT    = 9
_CP_PROGRESS = 10
_CP_READY    = 11


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
        "completed":   "\x1b[1;32m",
        "downloading": "\x1b[1;36m",
        "speeding":    "\x1b[1;34m",
        "splitting":   "\x1b[1;33m",
        "isolating":   "\x1b[1;35m",
        "ready":       "\x1b[0;32m",
        "error":       "\x1b[1;31m",
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
    """Terminal UI with live status updates, scroll, and URL input."""

    def __init__(self, jobs: MutableSequence[Job], *, disable_color: bool = False) -> None:
        self.jobs = jobs
        self.disable_color = disable_color
        self._lines_drawn = 0
        self._stopped = asyncio.Event()
        self._submitted_urls: Deque[str] = deque()
        self._input_buffer = ""
        self._notice = "Paste URL and press Enter to queue it."
        self._frame = 0
        self._scroll_offset = 0
        self._auto_scroll = True

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

    # ── Plain (non-curses) UI ────────────────────────────────────────────

    async def _run_plain_ui(self) -> None:
        hide_cursor()
        try:
            while not self._stopped.is_set():
                self._draw_plain()
                self._frame += 1
                await asyncio.sleep(0.15)
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

    # ── Curses UI ────────────────────────────────────────────────────────

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
            curses.start_color()
            try:
                curses.use_default_colors()
                has_colors = True
            except curses.error:
                pass
            if has_colors:
                curses.init_pair(_CP_DOWNLOAD, curses.COLOR_CYAN,    -1)
                curses.init_pair(_CP_ISOLATE,  curses.COLOR_MAGENTA, -1)
                curses.init_pair(_CP_SPEED,    curses.COLOR_BLUE,    -1)
                curses.init_pair(_CP_SPLIT,    curses.COLOR_YELLOW,  -1)
                curses.init_pair(_CP_DONE,     curses.COLOR_GREEN,   -1)
                curses.init_pair(_CP_ERROR,    curses.COLOR_RED,     -1)
                curses.init_pair(_CP_HEADER,   curses.COLOR_WHITE,   curses.COLOR_BLUE)
                curses.init_pair(_CP_DIM,      curses.COLOR_WHITE,   -1)
                curses.init_pair(_CP_INPUT,    curses.COLOR_CYAN,    -1)
                curses.init_pair(_CP_PROGRESS, curses.COLOR_GREEN,   -1)
                curses.init_pair(_CP_READY,    curses.COLOR_GREEN,   -1)

        try:
            while not self._stopped.is_set():
                self._capture_curses_input(screen)
                self._draw_curses(screen, has_colors=has_colors)
                self._frame += 1
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
            elif key in ("\b", "\x7f") or key == curses.KEY_BACKSPACE:
                self._input_buffer = self._input_buffer[:-1]
            elif key == curses.KEY_RESIZE:
                pass
            elif key == curses.KEY_UP:
                self._scroll_offset = max(0, self._scroll_offset - 1)
                self._auto_scroll = False
            elif key == curses.KEY_DOWN:
                self._scroll_offset += 1
                self._auto_scroll = False
            elif key == curses.KEY_PPAGE:
                self._scroll_offset = max(0, self._scroll_offset - 10)
                self._auto_scroll = False
            elif key == curses.KEY_NPAGE:
                self._scroll_offset += 10
                self._auto_scroll = False
            elif isinstance(key, str) and key.isprintable():
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
        try:
            self._draw_curses_safe(screen, has_colors=has_colors)
        except curses.error:
            pass

    def _draw_curses_safe(self, screen: "curses.window", *, has_colors: bool) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 6 or width < 20:
            return

        W = width - 1  # safe write width (avoid last-col scroll glitch)

        total  = len(self.jobs)
        done   = sum(1 for j in self.jobs if j.status == "completed")
        ready  = sum(1 for j in self.jobs if j.status == "ready")
        failed = sum(1 for j in self.jobs if j.status == "error")
        active = sum(1 for j in self.jobs if j.status in ACTIVE_STATES)
        queued = sum(1 for j in self.jobs if j.status == "pending")

        # ── Row 0: header ────────────────────────────────────────────────
        hdr = (
            f" ♪ YtdlAudioBook   "
            f"{done}/{total} done  "
            f"{ready} ready  {active} active  {queued} queued  {failed} failed "
        )
        hdr_attr = (curses.color_pair(_CP_HEADER) | curses.A_BOLD) if has_colors else curses.A_BOLD
        screen.addnstr(0, 0, hdr.ljust(W)[:W], W, hdr_attr)

        # ── Row 1: progress bar ──────────────────────────────────────────
        pct      = done / total if total else 0
        bar_w    = max(0, W - 8)
        filled   = int(pct * bar_w)
        bar_str  = f" {int(pct * 100):3d}% [" + "█" * filled + "░" * (bar_w - filled) + "]"
        bar_attr = (curses.color_pair(_CP_PROGRESS) | curses.A_BOLD) if has_colors else 0
        screen.addnstr(1, 0, truncate(bar_str, W), W, bar_attr)

        # ── Job rows: 2 .. height-4 ──────────────────────────────────────
        rows_for_jobs = max(0, height - 5)
        max_scroll = max(0, total - rows_for_jobs)
        if self._auto_scroll:
            self._scroll_offset = max_scroll
        else:
            self._scroll_offset = max(0, min(self._scroll_offset, max_scroll))

        above = self._scroll_offset
        below = max(0, total - above - rows_for_jobs)
        ind_rows = (1 if above > 0 else 0) + (1 if below > 0 else 0)
        job_rows = max(0, rows_for_jobs - ind_rows)
        visible  = list(self.jobs)[above : above + job_rows]

        dim_attr = curses.color_pair(_CP_DIM) if has_colors else 0
        row = 2

        if above > 0:
            screen.addnstr(row, 0, truncate(f"  ↑ {above} more  (↑/↓  PgUp/PgDn)", W), W, dim_attr)
            row += 1

        for job in visible:
            if row >= height - 3:
                break
            line = self._format_job_line(job, W)
            screen.addnstr(row, 0, truncate(line, W), W, self._status_attr(job.status, has_colors=has_colors))
            row += 1

        if below > 0 and row < height - 3:
            actual_below = max(0, total - above - job_rows)
            screen.addnstr(row, 0, truncate(f"  ↓ {actual_below} more  (↑/↓  PgUp/PgDn)", W), W, dim_attr)

        # ── Separator ────────────────────────────────────────────────────
        sep_attr = (curses.color_pair(_CP_HEADER)) if has_colors else 0
        screen.addnstr(height - 3, 0, ("─" * W)[:W], W, sep_attr)

        # ── Input prompt ─────────────────────────────────────────────────
        inp_attr = (curses.color_pair(_CP_INPUT) | curses.A_BOLD) if has_colors else 0
        screen.addnstr(height - 2, 0, truncate(f" ▶ {self._input_buffer}_", W), W, inp_attr)

        # ── Notice ───────────────────────────────────────────────────────
        screen.addnstr(height - 1, 0, truncate(f" {self._notice}", W), W)

        screen.refresh()

    def _status_attr(self, status: str, *, has_colors: bool) -> int:
        if curses is None or not has_colors:
            return 0
        mapping = {
            "downloading": curses.color_pair(_CP_DOWNLOAD) | curses.A_BOLD,
            "isolating":   curses.color_pair(_CP_ISOLATE),
            "speeding":    curses.color_pair(_CP_SPEED)    | curses.A_BOLD,
            "splitting":   curses.color_pair(_CP_SPLIT)    | curses.A_BOLD,
            "ready":       curses.color_pair(_CP_READY),
            "completed":   curses.color_pair(_CP_DONE)     | curses.A_BOLD,
            "error":       curses.color_pair(_CP_ERROR)    | curses.A_BOLD,
            "pending":     curses.color_pair(_CP_DIM),
        }
        return mapping.get(status, 0)

    def _format_job_line(self, job: Job, width: int) -> str:
        if job.status in ACTIVE_STATES:
            icon = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
        else:
            icon = STATE_ICONS.get(job.status, "?")
        label = STATE_LABELS.get(job.status, job.status)
        width_digits = len(str(job.total))
        index_str = str(job.index).zfill(width_digits)
        base = f" {icon} [{index_str}/{job.total}] {label:<9} {job.label()}"
        message = job.message
        if not message:
            return base
        remaining = max(0, width - len(base) - 5)
        snippet = truncate(message, remaining)
        if not snippet:
            return base
        return f"{base} :: {snippet}"
