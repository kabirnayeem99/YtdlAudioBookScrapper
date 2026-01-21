#!/usr/bin/env bash
set -euo pipefail

TARGET_NAME=${TARGET_NAME:-ytdl-audiobook}
SCRIPT_NAME=${SCRIPT_NAME:-ytdl_audiobook_scraper.py}
PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SOURCE_PATH="$PROJECT_ROOT/$SCRIPT_NAME"

usage() {
    cat <<'USAGE'
Usage: ./build.sh [--prefix DIR]

Detects macOS vs Linux and installs the ytdl audiobook CLI accordingly.
Environment overrides:
  TARGET_NAME   Binary name to install (default: ytdl-audiobook)
  SCRIPT_NAME   Entry script to install (default: ytdl_audiobook_scraper.py)
  PREFIX        Install prefix override
USAGE
    exit 1
}

PREFIX_OVERRIDE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            ;;
        --prefix)
            shift || usage
            PREFIX_OVERRIDE="$1"
            ;;
        *)
            echo "Unknown flag: $1" >&2
            usage
            ;;
    esac
    shift || true
}

if [[ ! -f "$SOURCE_PATH" ]]; then
    echo "Source script not found: $SOURCE_PATH" >&2
    exit 1
fi

if ! command -v install >/dev/null 2>&1; then
    echo "POSIX install(1) is required but was not found in PATH." >&2
    exit 1
fi

install_file() {
    local dest_path="$1"
    local dest_dir
    dest_dir=$(dirname "$dest_path")
    if [[ -d "$dest_dir" && ! -w "$dest_dir" ]]; then
        echo "Need write access to $dest_dir (try: sudo ./build.sh)" >&2
        exit 1
    fi
    install -d "$dest_dir"
    install -m 755 "$SOURCE_PATH" "$dest_path"
    echo "Installed $TARGET_NAME -> $dest_path"
}

uname_out=$(uname -s)
case "$uname_out" in
    Darwin)
        PREFIX=${PREFIX_OVERRIDE:-${PREFIX:-/opt/homebrew}}
        DEST="$PREFIX/bin/$TARGET_NAME"
        install_file "$DEST"
        ;;
    Linux)
        PREFIX=${PREFIX_OVERRIDE:-${PREFIX:-/usr/local}}
        DEST="$PREFIX/bin/$TARGET_NAME"
        install_file "$DEST"
        ;;
    *)
        echo "Unsupported OS: $uname_out" >&2
        exit 1
        ;;
esac

echo "Done. Make sure yt-dlp and ffmpeg are on your PATH."
