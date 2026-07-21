"""Scans a directory of video files and exposes them via protocol.Movie."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .protocol import Movie

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".m4v"}

DEFAULT_THUMBNAIL_DIR = Path("/var/lib/magicbox/thumbnails")
THUMBNAIL_TIMESTAMP_SECONDS = 60
THUMBNAIL_WIDTH = 200


class MovieLibrary:
    def __init__(self, root: Path, thumbnail_dir: Path = DEFAULT_THUMBNAIL_DIR):
        # The movies directory is typically mounted read-only, so thumbnails
        # are cached in a separate, writable location instead of alongside it.
        self.root = root
        self._movies: List[Movie] = []
        self._paths: Dict[int, Path] = {}
        self._thumbnail_paths: Dict[int, Path] = {}
        self._thumbnail_dir = thumbnail_dir

    def scan(self) -> List[Movie]:
        self._thumbnail_dir.mkdir(parents=True, exist_ok=True)

        files = sorted(
            p for p in self.root.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        )

        movies = []
        paths = {}
        thumbnail_paths = {}
        for index, path in enumerate(files):
            movies.append(
                Movie(id=index, title=path.stem, duration_seconds=self._probe_duration(path))
            )
            paths[index] = path

            thumbnail = self._ensure_thumbnail(index, path)
            if thumbnail is not None:
                thumbnail_paths[index] = thumbnail

        self._movies = movies
        self._paths = paths
        self._thumbnail_paths = thumbnail_paths
        logger.info("Scanned %d movie(s) in %s", len(movies), self.root)
        return movies

    @property
    def movies(self) -> List[Movie]:
        return self._movies

    def path_for(self, movie_id: int) -> Path:
        return self._paths[movie_id]

    def thumbnail_path_for(self, movie_id: int) -> Optional[Path]:
        return self._thumbnail_paths.get(movie_id)

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

    def _ensure_thumbnail(self, movie_id: int, path: Path) -> Optional[Path]:
        thumbnail_path = self._thumbnail_dir / f"{movie_id}.jpg"
        if thumbnail_path.exists():
            return thumbnail_path
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error",
                    "-ss", str(THUMBNAIL_TIMESTAMP_SECONDS),
                    "-i", str(path),
                    "-frames:v", "1",
                    "-vf", f"scale={THUMBNAIL_WIDTH}:-1",
                    str(thumbnail_path),
                ],
                capture_output=True,
                timeout=30,
                check=True,
            )
            return thumbnail_path
        except (subprocess.SubprocessError, FileNotFoundError) as exc:
            logger.warning("Thumbnail generation failed for %s: %s", path, exc)
            return None
