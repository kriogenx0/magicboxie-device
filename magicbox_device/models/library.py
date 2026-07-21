"""Scans a directory of video files and exposes them via protocol.Movie."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Dict, List

from .protocol import Movie

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".m4v"}


class MovieLibrary:
    def __init__(self, root: Path):
        self.root = root
        self._movies: List[Movie] = []
        self._paths: Dict[int, Path] = {}

    def scan(self) -> List[Movie]:
        files = sorted(
            p for p in self.root.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        )

        movies = []
        paths = {}
        for index, path in enumerate(files):
            movies.append(
                Movie(id=index, title=path.stem, duration_seconds=self._probe_duration(path))
            )
            paths[index] = path

        self._movies = movies
        self._paths = paths
        logger.info("Scanned %d movie(s) in %s", len(movies), self.root)
        return movies

    @property
    def movies(self) -> List[Movie]:
        return self._movies

    def path_for(self, movie_id: int) -> Path:
        return self._paths[movie_id]

    @staticmethod
    def _probe_duration(path: Path) -> int:
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            return int(float(result.stdout.strip()))
        except (subprocess.SubprocessError, ValueError, FileNotFoundError) as exc:
            logger.warning("ffprobe failed for %s: %s", path, exc)
            return 0
