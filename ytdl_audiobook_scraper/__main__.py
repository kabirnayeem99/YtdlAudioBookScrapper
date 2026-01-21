"""Module entry-point for `python -m ytdl_audiobook_scraper`."""

import sys

from .cli import main
from .display import show_cursor


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        show_cursor()
        sys.exit(130)
