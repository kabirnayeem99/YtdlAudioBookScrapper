"""Async orchestration and job lifecycle management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import shutil
import signal
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Set
from urllib.parse import parse_qs, urlparse

from .config import DownloadSettings
from .display import LivePrinter
from .jobs import Job
from .utils import ensure_dependency, normalize_name

SPEED_MULTIPLIER = "1.25"

# Marker dropped in a job's output folder once vocal isolation has actually
# succeeded, so a later resumed run can tell "downloaded" apart from "fully
# done" without needing to re-download anything to check.
ISOLATED_MARKER_NAME = ".isolated"

# MDX-Net model used for vocal isolation. audio-separator auto-detects the
# best available backend itself (CoreML/MPS on Apple Silicon, CUDA, else CPU).
AUDIO_SEPARATOR_MODEL = "UVR-MDX-NET-Voc_FT.onnx"


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


async def speed_and_segment(source: Path, segment_pattern: Path, job: Job) -> None:
    await run_command(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-filter:a",
            f"atempo={SPEED_MULTIPLIER}",
            "-ac",
            "1",
            "-ar",
            "22050",
            "-b:a",
            "40k",
            "-f",
            "segment",
            "-segment_time",
            str(job.segment_seconds),
            str(segment_pattern),
        ],
        job,
        "ffmpeg",
    )


async def isolate_vocals(downloaded: Path, tmp_path: Path, job: Job) -> Optional[Path]:
    """Run audio-separator on the downloaded audio; return the vocals-only file, or None if unavailable."""

    separated_dir = tmp_path / "separated"
    separated_dir.mkdir(parents=True, exist_ok=True)
    await run_command(
        [
            "audio-separator",
            "-m",
            AUDIO_SEPARATOR_MODEL,
            "--single_stem",
            "vocals",
            "--output_format",
            "WAV",
            "--output_dir",
            str(separated_dir),
            str(downloaded),
        ],
        job,
        "audio-separator",
    )

    vocals_file = separated_dir / f"{downloaded.stem}_(Vocals).wav"
    return vocals_file if vocals_file.exists() else None


async def process_job(
    job: Job, download_semaphore: asyncio.Semaphore, isolate_semaphore: asyncio.Semaphore
) -> None:
    with tempfile.TemporaryDirectory(prefix="ytdl-job-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        downloaded: Optional[Path] = None
        target_dir: Optional[Path] = None
        safe_name: Optional[str] = None

        # Phase 1: download + segment. Releases the download slot for the next
        # job as soon as it's done, so downloads never wait on vocal isolation.
        async with download_semaphore:
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
                            isolated = (candidate_dir / ISOLATED_MARKER_NAME).exists()
                            if not job.isolate_vocals or isolated:
                                job.status = "completed"
                                job.message = f"resumed: {candidate_dir}"
                            else:
                                # Downloaded and segmented in a prior run, but that
                                # run never finished vocal isolation. Nothing left
                                # to re-download here; a fresh run is needed to
                                # actually isolate these (the raw pre-isolation
                                # audio was only ever a temp file).
                                job.status = "ready"
                                job.message = (
                                    f"resumed, not vocal-isolated (delete folder and re-run "
                                    f"to isolate): {candidate_dir}"
                                )
                            return
                except Exception:
                    pass

                job.message = ""
                # Prefer a low-bitrate audio-only stream and fetch fragments
                # concurrently; speech stays intelligible well below music-grade
                # bitrates, and a smaller source also speeds up vocal isolation.
                await run_command(
                    [
                        "yt-dlp",
                        "--format",
                        "ba[abr<=96]/ba/b",
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
                safe_name = normalize_name(downloaded.stem)
                job.display_name = safe_name
                target_dir = job.base_dir / safe_name
                target_dir.mkdir(parents=True, exist_ok=True)
                job.output_dir = target_dir

                job.status = "speeding"
                segment_pattern = target_dir / f"{safe_name}_part_%03d.mp3"
                await speed_and_segment(downloaded, segment_pattern, job)

                # "ready" means usable but not yet vocal-isolated; "completed"
                # is reserved for jobs where isolation is done, skipped, or off.
                job.status = "ready" if job.isolate_vocals else "completed"
                job.message = str(target_dir)
            except Exception as exc:  # noqa: BLE001
                job.status = "error"
                job.message = str(exc)
                job.error = str(exc)
                return

        # Phase 2: vocal isolation is a best-effort quality upgrade on top of
        # the already-usable output above. It runs on its own (typically
        # smaller, GPU-bound) concurrency pool and never fails the job -- if
        # audio-separator is missing or errors out, the original audio stays in place.
        if not job.isolate_vocals or downloaded is None:
            return

        async with isolate_semaphore:
            try:
                job.status = "isolating"
                job.message = "removing background music..."
                vocals_file = await isolate_vocals(downloaded, tmp_path, job)
                if vocals_file is None:
                    job.status = "completed"
                    job.message = f"{target_dir} (vocal isolation produced no output; kept original audio)"
                    return

                job.status = "isolating"
                job.message = "re-encoding isolated vocals..."
                for stale in target_dir.glob(f"{safe_name}_part_*.mp3"):
                    stale.unlink()
                segment_pattern = target_dir / f"{safe_name}_part_%03d.mp3"
                await speed_and_segment(vocals_file, segment_pattern, job)
                (target_dir / ISOLATED_MARKER_NAME).touch()

                job.status = "completed"
                job.message = f"{target_dir} (background music removed)"
            except Exception as exc:  # noqa: BLE001
                job.status = "completed"
                job.message = f"{target_dir} (vocal isolation failed, kept original audio: {exc})"


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
    if settings.isolate_vocals and shutil.which("audio-separator") is None:
        # Not a hard requirement: downloads and segmenting work fine without
        # it, vocal isolation just won't run for any job until it's on PATH.
        print(
            "Warning: audio-separator not found on PATH; downloads will proceed without vocal isolation.",
            file=sys.stderr,
        )

    jobs: List[Job] = []
    download_semaphore = asyncio.Semaphore(settings.jobs)
    isolate_semaphore = asyncio.Semaphore(settings.isolate_jobs)
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
            isolate_vocals=settings.isolate_vocals,
        )
        jobs.append(job)
        refresh_totals()
        task = asyncio.create_task(process_job(job, download_semaphore, isolate_semaphore))
        active_tasks.add(task)
        all_tasks.append(task)
        task.add_done_callback(active_tasks.discard)

    async def schedule_urls(urls: List[str]) -> None:
        # Queue standalone videos first so they start downloading immediately;
        # playlists (which can expand into many jobs) are scheduled after.
        single_urls = [url for url in urls if not is_youtube_playlist_url(url)]
        playlist_urls = [url for url in urls if is_youtube_playlist_url(url)]

        for url in single_urls:
            schedule_job(url, settings.destination)

        for url in playlist_urls:
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
