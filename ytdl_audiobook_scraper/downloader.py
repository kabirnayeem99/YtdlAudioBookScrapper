"""Async orchestration and job lifecycle management."""

from __future__ import annotations

import asyncio
import signal
import shutil
import tempfile
from pathlib import Path
from typing import List

from .config import DownloadSettings
from .display import LivePrinter
from .jobs import Job
from .utils import ensure_dependency, normalize_name


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


async def process_job(job: Job, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        with tempfile.TemporaryDirectory(prefix="ytdl-job-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            try:
                job.status = "downloading"
                await run_command(
                    [
                        "yt-dlp",
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

                job.status = "splitting"
                segment_pattern = target_dir / f"{safe_name}_part_%03d.mp3"
                await run_command(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        str(final_file),
                        "-f",
                        "segment",
                        "-segment_time",
                        str(job.segment_seconds),
                        "-c",
                        "copy",
                        str(segment_pattern),
                    ],
                    job,
                    "ffmpeg",
                )

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

    jobs = [
        Job(
            index=i + 1,
            total=len(settings.urls),
            url=url,
            base_dir=settings.destination,
            segment_seconds=settings.segment_seconds,
            audio_quality=settings.audio_quality,
        )
        for i, url in enumerate(settings.urls)
    ]

    printer = LivePrinter(jobs, disable_color=settings.disable_color)
    printer_task = asyncio.create_task(printer.run())
    semaphore = asyncio.Semaphore(min(settings.jobs, len(jobs)))

    job_tasks = [asyncio.create_task(process_job(job, semaphore)) for job in jobs]
    try:
        await asyncio.gather(*job_tasks)
    except asyncio.CancelledError:
        for task in job_tasks:
            task.cancel()
        await asyncio.gather(*job_tasks, return_exceptions=True)
        for job in jobs:
            if job.status not in {"completed", "error"}:
                job.status = "error"
                job.message = "Cancelled by user"
                job.error = "Cancelled by user"
        raise
    finally:
        printer.stop()
        await printer_task
    return jobs
