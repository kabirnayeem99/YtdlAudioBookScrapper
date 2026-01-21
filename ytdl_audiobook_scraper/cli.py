"""Command-line glue code for the yt-dlp audiobook helper."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from .config import DownloadSettings
from .downloader import install_sigint_handler, orchestrate
from .jobs import Job
from .utils import DEFAULT_AUDIO_QUALITY, DEFAULT_SEGMENT_MINUTES, default_download_dir


def parse_settings(argv: Optional[Iterable[str]] = None) -> DownloadSettings:
    parser = argparse.ArgumentParser(
        description="Download YouTube audio as MP3, normalize naming, and split into chapters.",
    )
    parser.add_argument("urls", nargs="*", help="One or more YouTube video URLs.")
    parser.add_argument(
        "-d",
        "--directory",
        help="Destination directory (default: ~/Downloads or $DOWNLOADS)",
    )
    parser.add_argument(
        "-f",
        "--file",
        help="Plain-text file containing one YouTube URL per line (optional).",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=default_job_count(),
        help="Parallel jobs (default: half the host CPU count, at least 1).",
    )
    parser.add_argument(
        "--segment-minutes",
        type=int,
        default=DEFAULT_SEGMENT_MINUTES,
        help="Length of each slice in minutes (default: 20).",
    )
    parser.add_argument(
        "--audio-quality",
        default=DEFAULT_AUDIO_QUALITY,
        help="yt-dlp audio quality knob (0=best, 9=worst, default: 5 for medium).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color escapes in the progress board.",
    )

    args = parser.parse_args(argv)

    url_candidates: List[str] = list(args.urls)
    if args.file:
        url_candidates.extend(read_urls_from_file(Path(args.file), parser))

    url_candidates = [url.strip() for url in url_candidates if url and url.strip()]
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")
    if args.segment_minutes < 1:
        parser.error("--segment-minutes must be >= 1")
    if not url_candidates:
        parser.error("Provide at least one URL via arguments or --file")

    destination = Path(args.directory).expanduser() if args.directory else default_download_dir()

    return DownloadSettings(
        urls=url_candidates,
        destination=destination,
        jobs=args.jobs,
        segment_minutes=args.segment_minutes,
        audio_quality=args.audio_quality,
        disable_color=args.no_color,
    )


def default_job_count() -> int:
    count = os.cpu_count() or 2
    return max(1, count // 2)


def read_urls_from_file(path: Path, parser: argparse.ArgumentParser) -> List[str]:
    file_path = path.expanduser()
    if not file_path.exists():
        parser.error(f"URL file not found: {file_path}")
    if not file_path.is_file():
        parser.error(f"URL file is not a regular file: {file_path}")

    urls: List[str] = []
    with file_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def main(argv: Optional[Iterable[str]] = None) -> None:
    settings = parse_settings(argv)
    loop = asyncio.new_event_loop()
    install_sigint_handler(loop)
    asyncio.set_event_loop(loop)

    cancelled = False
    jobs: List[Job] = []
    try:
        jobs = loop.run_until_complete(orchestrate(settings))
    except asyncio.CancelledError:
        cancelled = True
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

    if cancelled:
        sys.stdout.write("\nCancelled by user. Active downloads aborted.\n")
        sys.exit(130)

    failures = [job for job in jobs if job.status == "error"]
    sys.stdout.write("\n")
    if failures:
        sys.stdout.write("Failures:\n")
        for job in failures:
            sys.stdout.write(f" - {job.url}: {job.error}\n")
        sys.exit(1)
    else:
        sys.stdout.write("All downloads finished successfully.\n")
        sys.exit(0)
