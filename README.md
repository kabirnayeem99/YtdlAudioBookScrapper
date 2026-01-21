# YtdlAudioBookScrapper

Rip YouTube audio, normalize the mess, and slice it into tidy 20-minute `.mp3` chunks with a neon progress board.

## Gear Check
- Python 3.9+
- `yt-dlp` + `ffmpeg` somewhere in `PATH`

## Install
### macOS / Linux
```bash
git clone https://github.com/kabir/YtdlAudioBookScrapper.git
cd YtdlAudioBookScrapper
./build.sh                 # sudo ./build.sh if /usr/local/bin needs it
```
Need a different prefix? `PREFIX=/some/path ./build.sh`.

### Windows
```powershell
git clone https://github.com/kabir/YtdlAudioBookScrapper.git
cd YtdlAudioBookScrapper
.\build.ps1                # optionally pass -Target C:\bin\ytdl-audiobook.py
```
By default this drops `ytdl-audiobook.py` into `~\AppData\Local\Microsoft\WindowsApps`. Keep `yt-dlp` + `ffmpeg` installed via Scoop/Chocolatey/manual.

## Run It
```bash
ytdl-audiobook [flags] URL [URL...]
```
Quick tricks:
- `ytdl-audiobook --file urls.txt --directory ~/AudioBooks`
- `ytdl-audiobook --segment-minutes 15 --jobs 6 https://youtu.be/abc`

## Flags Cheat Sheet
- `-d, --directory DIR` -> where the folders land (default `~/Downloads`).
- `-f, --file FILE` -> newline URLs with optional `#` comments.
- `-j, --jobs N` -> parallel pulls (auto ~ half your cores).
- `--segment-minutes N` -> slice length, default `20`.
- `--audio-quality N` -> yt-dlp quality knob (`0` best ... `9` worst, default `5`).
- `--no-color` -> kill ANSI glam if your terminal complains.

## Output Vibes
```
<destination>/<normalized-title>/
  normalized-title.mp3
  normalized-title_part_000.mp3
  normalized-title_part_001.mp3
  ...
```
Exit is `0` if every URL behaved, non-zero if any exploded (you'll see which ones).
