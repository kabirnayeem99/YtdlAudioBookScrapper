#!/usr/bin/env bash
set -euo pipefail

TARGET_NAME=${TARGET_NAME:-ytdl-audiobook}
PACKAGE_DIR_NAME=${PACKAGE_DIR_NAME:-ytdl_audiobook_scraper}
PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PACKAGE_SOURCE_PATH="$PROJECT_ROOT/$PACKAGE_DIR_NAME"

usage() {
    cat <<'USAGE'
Usage: ./build.sh [--prefix DIR]

Detects macOS vs Linux and installs the ytdl audiobook CLI accordingly.
Environment overrides:
  TARGET_NAME       Binary name to install (default: ytdl-audiobook)
  PACKAGE_DIR_NAME  Package directory to install (default: ytdl_audiobook_scraper)
  PREFIX            Install prefix override
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
done

if [[ ! -d "$PACKAGE_SOURCE_PATH" ]]; then
    echo "Package directory not found: $PACKAGE_SOURCE_PATH" >&2
    exit 1
fi

if ! command -v install >/dev/null 2>&1; then
    echo "POSIX install(1) is required but was not found in PATH." >&2
    exit 1
fi

install_package_tree() {
    local prefix="$1"
    local libexec_dir="$prefix/libexec/$TARGET_NAME"
    local installed_package="$libexec_dir/$PACKAGE_DIR_NAME"

    if [[ -d "$libexec_dir" && ! -w "$libexec_dir" ]]; then
        echo "Need write access to $libexec_dir (try: sudo ./build.sh)" >&2
        exit 1
    fi

    install -d "$libexec_dir"
    rm -rf "$installed_package"
    cp -R "$PACKAGE_SOURCE_PATH" "$libexec_dir/"
    echo "Installed package -> $installed_package"
}

install_launcher() {
    local prefix="$1"
    local dest_path="$2"
    local dest_dir
    dest_dir=$(dirname "$dest_path")

    if [[ -d "$dest_dir" && ! -w "$dest_dir" ]]; then
        echo "Need write access to $dest_dir (try: sudo ./build.sh)" >&2
        exit 1
    fi

    install -d "$dest_dir"
    cat > "$dest_path" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail

PREFIX_DIR="$prefix"
LIBEXEC_DIR="\$PREFIX_DIR/libexec/$TARGET_NAME"
export PYTHONPATH="\$LIBEXEC_DIR\${PYTHONPATH:+:\$PYTHONPATH}"
exec "\${PYTHON:-python3}" -m $PACKAGE_DIR_NAME "\$@"
LAUNCHER
    chmod 755 "$dest_path"
    echo "Installed launcher -> $dest_path"
}

uname_out=$(uname -s)
case "$uname_out" in
    Darwin)
        PREFIX=${PREFIX_OVERRIDE:-${PREFIX:-/opt/homebrew}}
        DEST="$PREFIX/bin/$TARGET_NAME"
        ;;
    Linux)
        PREFIX=${PREFIX_OVERRIDE:-${PREFIX:-/usr/local}}
        DEST="$PREFIX/bin/$TARGET_NAME"
        ;;
    *)
        echo "Unsupported OS: $uname_out" >&2
        exit 1
        ;;
esac

install_package_tree "$PREFIX"
install_launcher "$PREFIX" "$DEST"

echo "Done. Make sure yt-dlp and ffmpeg are on your PATH."
