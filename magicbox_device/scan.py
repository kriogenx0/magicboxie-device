"""Standalone content-parsing step: scans MAGICBOX_MOVIES_DIR with
ffprobe/ffmpeg and writes a static library index (+ thumbnails) for the
daemon to load at startup. Run via the `magicbox-scan` console script -
e.g. as a systemd ExecStartPre ahead of `magicbox-device` - so the daemon's
own startup is just a JSON read, not a directory walk full of subprocess
calls.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from .models.library import DEFAULT_THUMBNAIL_DIR, MovieLibrary

logger = logging.getLogger(__name__)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    movies_dir = Path(os.environ.get("MAGICBOX_MOVIES_DIR", "/movies"))
    thumbnail_dir = Path(os.environ.get("MAGICBOX_THUMBNAIL_DIR", str(DEFAULT_THUMBNAIL_DIR)))

    if not movies_dir.is_dir():
        raise SystemExit(f"Movies directory does not exist: {movies_dir}")

    library = MovieLibrary(movies_dir, thumbnail_dir=thumbnail_dir)
    library.scan()


if __name__ == "__main__":
    run()
