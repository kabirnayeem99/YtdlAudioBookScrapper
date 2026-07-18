"""Async orchestration and job lifecycle management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import signal
import shutil
import tempfile
from pathlib import Path
from typing import List, Set
from urllib.parse import parse_qs, urlparse

from .config import DownloadSettings
from .display import LivePrinter
from .jobs import Job
from .utils import ensure_dependency, normalize_name

SPEED_MULTIPLIER = "1.25"


@dataclass(frozen=True)
class PlaylistEntry:
    """A video URL and its optional playlist output folder."""

    url: str
    playlist_name: str | None = None


async def run_command(cmd: List[str], job: Job, phase: str) -> None:
    """Run a subprocess and stream stderr/stdout snippets into the job message."""

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def forward(stream: asyncio.StreamReader) -> List[str]:
        last_lines: List[str] = []
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                job.message = f"{phase}: {text}"
                last_lines.append(text)
                last_lines = last_lines[-5:]
        return last_lines

    stdout_stream = process.stdout
    stderr_stream = process.stderr
    if stdout_stream is None or stderr_stream is None:
        raise RuntimeError("Subprocess pipes not initialized")

    stdout_task = asyncio.create_task(forward(stdout_stream))
    stderr_task = asyncio.create_task(forward(stderr_stream))
    exit_code = await process.wait()
    stdout_tail, stderr_tail = await asyncio.gather(stdout_task, stderr_task)
    if exit_code != 0:
        combined = "\n".join(stdout_tail + stderr_tail)
        raise RuntimeError(f"{' '.join(cmd)} failed (exit {exit_code})\n{combined}")


async def run_capture_output(cmd: List[str]) -> List[str]:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_data, stderr_data = await process.communicate()
    output_lines = [
        line.strip()
        for line in stdout_data.decode("utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    if process.returncode != 0:
        stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"{' '.join(cmd)} failed (exit {process.returncode})"
            + (f"\n{stderr_text}" if stderr_text else "")
        )
    return output_lines


def is_youtube_playlist_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtube.com" not in host and "youtu.be" not in host:
        return False
    query = parse_qs(parsed.query)
    return "list" in query or parsed.path.startswith("/playlist")


def normalize_playlist_entry(url_or_id: str) -> str:
    if url_or_id.startswith(("http://", "https://")):
        return url_or_id
    return f"https://www.youtube.com/watch?v={url_or_id}"


async def expand_playlist_url(url: str) -> List[PlaylistEntry]:
    if not is_youtube_playlist_url(url):
        return [PlaylistEntry(url)]

    lines = await run_capture_output(
        [
            "yt-dlp",
            "--flat-playlist",
            "--print",
            "%(playlist_title)s\t%(webpage_url)s",
            "--skip-download",
            "--no-warnings",
            url,
        ]
    )
    if not lines:
        return [PlaylistEntry(url)]

    expanded: List[PlaylistEntry] = []
    seen: Set[str] = set()
    for line in lines:
        playlist_title, separator, entry_url = line.partition("\t")
        normalized = normalize_playlist_entry(entry_url if separator else playlist_title)
        if normalized in seen:
            continue
        seen.add(normalized)
        playlist_name = normalize_name(playlist_title) if separator and playlist_title else "playlist"
        expanded.append(PlaylistEntry(normalized, playlist_name))
    return expanded or [PlaylistEntry(url)]


def parse_submitted_urls(submissions: List[str]) -> List[str]:
    urls: List[str] = []
    for raw in submissions:
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            urls.extend(part for part in stripped.split() if part)
    return urls


async def process_job(job: Job, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        with tempfile.TemporaryDirectory(prefix="ytdl-job-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            try:
                # Resume check: fetch title and see if segments already exist
                job.status = "downloading"
                job.message = "checking..."
                try:
                    title_lines = await run_capture_output([
                        "yt-dlp", "--print", "title",
                        "--no-playlist", "--no-warnings", job.url,
                    ])
                    if title_lines:
                        candidate = normalize_name(title_lines[0])
                        candidate_dir = job.base_dir / candidate
                        if list(candidate_dir.glob(f"{candidate}_part_*.mp3")):
                            job.display_name = candidate
                            job.output_dir = candidate_dir
                            job.status = "completed"
                            job.message = f"resumed: {candidate_dir}"
                            return
                except Exception:
                    pass

                job.message = ""
                # Prefer an audio-only stream at or below 128 kbps and fetch
                # fragments concurrently; speech remains clear after the final mono encode.
                await run_command(
                    [
                        "yt-dlp",
                        "--format",
                        "ba[abr<=128]/ba/b",
                        "--concurrent-fragments",
                        "4",
                        job.url,
                        "--no-playlist",
                        "--newline",
                        "--extract-audio",
                        "--audio-format",
                        "mp3",
                        "--audio-quality",
                        job.audio_quality,
                        "--output",
                        str(tmp_path / "%(title)s.%(ext)s"),
                    ],
                    job,
                    "yt-dlp",
                )

                mp3_files = sorted(tmp_path.glob("*.mp3"))
                if not mp3_files:
                    raise RuntimeError("yt-dlp did not produce an MP3 file")
                downloaded = mp3_files[0]
                original_stem = downloaded.stem
                safe_name = normalize_name(original_stem)
                job.display_name = safe_name
                target_dir = job.base_dir / safe_name
                target_dir.mkdir(parents=True, exist_ok=True)
                job.status = "renaming"
                final_file = target_dir / f"{safe_name}.mp3"
                shutil.move(str(downloaded), final_file)
                job.output_dir = target_dir

                job.status = "speeding"
                segment_pattern = target_dir / f"{safe_name}_part_%03d.mp3"
                await run_command(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(final_file),
                        "-filter:a",
                        f"atempo={SPEED_MULTIPLIER}",
                        "-ac",
                        "1",
                        "-q:a",
                        "5",
                        "-f",
                        "segment",
                        "-segment_time",
                        str(job.segment_seconds),
                        str(segment_pattern),
                    ],
                    job,
                    "ffmpeg",
                )

                if final_file.exists():
                    final_file.unlink()

                job.status = "completed"
                job.message = str(target_dir)
            except Exception as exc:  # noqa: BLE001
                job.status = "error"
                job.message = str(exc)
                job.error = str(exc)


def install_sigint_handler(loop: asyncio.AbstractEventLoop) -> None:
    def _handler() -> None:
        for task in asyncio.all_tasks(loop):
            task.cancel()

    try:
        loop.add_signal_handler(signal.SIGINT, _handler)
    except NotImplementedError:
        pass


async def orchestrate(settings: DownloadSettings) -> List[Job]:
    settings.destination.mkdir(parents=True, exist_ok=True)

    ensure_dependency("yt-dlp")
    ensure_dependency("ffmpeg")

    jobs: List[Job] = []
    semaphore = asyncio.Semaphore(settings.jobs)
    active_tasks: Set[asyncio.Task[None]] = set()
    all_tasks: List[asyncio.Task[None]] = []

    def refresh_totals() -> None:
        total = len(jobs)
        for job in jobs:
            job.total = total

    def schedule_job(url: str, base_dir: Path) -> None:
        job = Job(
            index=len(jobs) + 1,
            total=0,
            url=url,
            base_dir=base_dir,
            segment_seconds=settings.segment_seconds,
            audio_quality=settings.audio_quality,
        )
        jobs.append(job)
        refresh_totals()
        task = asyncio.create_task(process_job(job, semaphore))
        active_tasks.add(task)
        all_tasks.append(task)
        task.add_done_callback(active_tasks.discard)

    async def schedule_urls(urls: List[str]) -> None:
        for url in urls:
            try:
                expanded_urls = await expand_playlist_url(url)
            except Exception:
                expanded_urls = [PlaylistEntry(url)]
            for entry in expanded_urls:
                playlist_dir = (
                    settings.destination / entry.playlist_name
                    if entry.playlist_name
                    else settings.destination
                )
                schedule_job(entry.url, playlist_dir)

    printer = LivePrinter(jobs, disable_color=settings.disable_color)
    printer_task = asyncio.create_task(printer.run())
    loop = asyncio.get_running_loop()
    idle_started_at: float | None = None
    try:
        await schedule_urls(settings.urls)
        while True:
            submitted_urls = parse_submitted_urls(printer.drain_submitted_urls())
            if submitted_urls:
                await schedule_urls(submitted_urls)

            if active_tasks:
                idle_started_at = None
            else:
                if idle_started_at is None:
                    idle_started_at = loop.time()
                elif loop.time() - idle_started_at >= 2.0:
                    break
            await asyncio.sleep(0.1)
    except asyncio.CancelledError:
        for task in list(active_tasks):
            task.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)
        for job in jobs:
            if job.status not in {"completed", "error"}:
                job.status = "error"
                job.message = "Cancelled by user"
                job.error = "Cancelled by user"
        raise
    finally:
        await asyncio.gather(*all_tasks, return_exceptions=True)
        printer.stop()
        await printer_task
    return jobs
