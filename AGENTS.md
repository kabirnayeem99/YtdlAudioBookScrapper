# AGENTS.md

Guidance for contributors and coding agents working in this repository.

## Project Context

This project is a Python CLI that turns YouTube videos into audiobook-style MP3 chunks using `yt-dlp`, `demucs`, and `ffmpeg`.

Core flow:

1. Parse CLI inputs (`urls` + optional `--file`)
2. Validate dependencies (`yt-dlp`, `ffmpeg`, and `demucs` unless `--no-vocal-isolation`)
3. Download low-bitrate audio to a temporary directory
4. Normalize title -> deterministic safe output name
5. Run `demucs` two-stems vocal isolation to strip background music (unless disabled)
6. Segment the (isolated) audio into fixed-duration, mono, low-bitrate parts directly into the destination folder
7. Render live multi-job progress in terminal

## Engineering Rules

- Keep code strongly typed with Python type hints.
- Avoid `Any` and avoid broad unchecked casts.
- Prefer small, single-purpose functions.
- Isolate side effects (filesystem/process/network) from pure logic when practical.
- Keep naming explicit and domain-oriented (`segment_seconds`, `destination`, `audio_quality`).
- Prefer standard library solutions first; do not add dependencies without strong justification.

## Concurrency and Cancellation

- Use `asyncio` structured concurrency patterns already present in `downloader.py`.
- Preserve cancellation behavior:
  - propagate `CancelledError`
  - cancel active job tasks on shutdown
  - map cancelled in-flight jobs to deterministic error state
- Do not introduce shared mutable global state.

## CLI and UX Invariants

- `--jobs` and `--segment-minutes` must remain validated as `>= 1`.
- URL input must continue supporting both positional args and `--file`.
- `--file` format: one URL per line, ignore blank lines and `#` comments.
- Keep output naming normalization deterministic and filesystem-safe.
- Preserve exit code contract:
  - `0` success
  - `1` failures
  - `130` user interrupt

## Dependency Policy

- Runtime dependencies are Python stdlib + external binaries (`yt-dlp`, `ffmpeg`, `demucs`).
- `demucs` was added to isolate vocals and strip background music from downloaded audiobooks; it can be skipped per-run via `--no-vocal-isolation` for users who don't want the extra install/runtime cost.
- If a Python package addition is proposed, document why stdlib is insufficient.

## Validation Checklist (Before Finishing Changes)

Run at minimum:

```bash
python3 -m py_compile ytdl_audiobook_scraper.py
python3 -m compileall ytdl_audiobook_scraper
python3 ytdl_audiobook_scraper.py --help
```

If behavior changes, also run a small end-to-end check with a test URL or a short URL file.

## File Ownership Guide

- `ytdl_audiobook_scraper/cli.py`: args, settings parsing, exit behavior
- `ytdl_audiobook_scraper/config.py`: immutable runtime settings model
- `ytdl_audiobook_scraper/downloader.py`: job lifecycle + subprocess orchestration
- `ytdl_audiobook_scraper/display.py`: terminal rendering
- `ytdl_audiobook_scraper/utils.py`: shared constants and pure helpers

Keep changes localized to the owning module when possible.
