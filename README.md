# YtdlAudioBookScrapper

Download YouTube audio as MP3, normalize file names, speed audio up to `1.25x`, and split each track into fixed-length audiobook-friendly parts.

## What It Does

- Downloads one or more YouTube URLs with `yt-dlp`
- Extracts compact, speech-focused MP3 audio
- Normalizes output names to safe lowercase slugs
- Speeds each track up to `1.25x` before segmentation
- Splits each MP3 into segments with `ffmpeg`
- Deletes the full-length MP3 after segmentation
- Expands YouTube playlist URLs into per-video jobs nested under the playlist folder
- Runs downloads concurrently in a live TUI where you can paste more URLs while jobs run

## Requirements

- Python `3.9+`
- [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) available in `PATH`
- [`ffmpeg`](https://ffmpeg.org/) available in `PATH`

## Installation

### macOS / Linux

```bash
git clone https://github.com/kabir/YtdlAudioBookScrapper.git
cd YtdlAudioBookScrapper
./build.sh
```

Optional custom install prefix:

```bash
PREFIX=/usr/local ./build.sh
# or
./build.sh --prefix /usr/local
```

### Windows (PowerShell)

```powershell
git clone https://github.com/kabir/YtdlAudioBookScrapper.git
cd YtdlAudioBookScrapper
.\build.ps1
```

Optional custom target path:

```powershell
.\build.ps1 -Target "C:\\bin\\ytdl-audiobook.py"
```

## Usage

```bash
ytdl-audiobook [OPTIONS] URL [URL ...]
```

Or run directly without installing:

```bash
python3 ytdl_audiobook_scraper.py [OPTIONS] URL [URL ...]
```

### Options

- `-d, --directory DIR`: Destination directory (default: `~/Downloads` or `$DOWNLOADS`)
- `-f, --file FILE`: Text file with one URL per line (`#` comments are ignored)
- `-j, --jobs N`: Parallel job count (default: half CPU cores, minimum `1`)
- `--segment-minutes N`: Segment length in minutes (default: `20`)
- `--audio-quality N`: `yt-dlp` quality (`0` best, `10` worst; default `6` for speech)
- `--no-color`: Disable ANSI colors in the live progress view

### Examples

```bash
# Single URL
ytdl-audiobook "https://youtu.be/VIDEO_ID"

# Multiple URLs
ytdl-audiobook "https://youtu.be/A" "https://youtu.be/B"

# Read URLs from file
ytdl-audiobook --file videos_to_download.txt

# Custom output directory + segment size
ytdl-audiobook --directory ~/AudioBooks --segment-minutes 15 --jobs 4 --file videos_to_download.txt

# Playlist URL (each video becomes a queued job in its playlist folder)
ytdl-audiobook "https://www.youtube.com/playlist?list=PLAYLIST_ID"
```

## Output Layout

Standalone URLs create a folder under the destination directory:

```text
<destination>/<normalized-title>/
  <normalized-title>_part_000.mp3
  <normalized-title>_part_001.mp3
  ...
```

Playlist videos retain their playlist folder, then use the same per-video folder and 20-minute segments:

```text
<destination>/<normalized-playlist-title>/<normalized-video-title>/
  <normalized-video-title>_part_000.mp3
  <normalized-video-title>_part_001.mp3
  ...
```

Name normalization rules:

- Lowercase
- Spaces become `_`
- Characters outside `[a-z0-9._-]` are removed
- Empty results fall back to `ytdl_audio`

## Exit Codes

- `0`: All jobs completed successfully
- `1`: One or more jobs failed
- `130`: Interrupted by user (`Ctrl+C`)

## Development

Useful local checks:

```bash
python3 -m py_compile ytdl_audiobook_scraper.py
python3 -m compileall ytdl_audiobook_scraper
python3 ytdl_audiobook_scraper.py --help
```

## Project Structure

- `ytdl_audiobook_scraper/cli.py`: Argument parsing and process entry logic
- `ytdl_audiobook_scraper/downloader.py`: Async orchestration and subprocess execution
- `ytdl_audiobook_scraper/jobs.py`: Job model
- `ytdl_audiobook_scraper/display.py`: Live terminal UI
- `ytdl_audiobook_scraper/utils.py`: Shared helpers and constants
- `build.sh` / `build.ps1`: Installation scripts
