#!/usr/bin/env python3
"""Compatibility shim that executes the packaged CLI."""

import sys

from ytdl_audiobook_scraper.cli import main
from ytdl_audiobook_scraper.display import show_cursor


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        show_cursor()
        sys.exit(130)
