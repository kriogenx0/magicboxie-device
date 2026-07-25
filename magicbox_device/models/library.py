"""Scans a directory of video files and exposes them via protocol.Movie.

Scanning (ffprobe for duration, ffmpeg for thumbnails) is slow enough on a
Pi Zero that it shouldn't happen on every daemon boot. `scan()` does the
real work and persists its result to a JSON index; `load()` is the fast
path the daemon uses at startup, reading that index instead of re-probing
every file. See `magicbox_device.scan`, the standalone CLI that runs
`scan()` as a systemd ExecStartPre step ahead of the daemon itself.
"""
from __future__ import annotations

import json
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
    def __init__(
        self,
        root: Path,
        thumbnail_dir: Path = DEFAULT_THUMBNAIL_DIR,
        index_path: Optional[Path] = None,
    ):
        # The movies directory is typically mounted read-only, so thumbnails
        # are cached in a separate, writable location instead of alongside it.
        self.root = root
        self._movies: List[Movie] = []
        self._paths: Dict[int, Path] = {}
        self._thumbnail_paths: Dict[int, Path] = {}
        self._thumbnail_dir = thumbnail_dir
        # Defaults alongside the thumbnail cache rather than a fixed system
        # path, so passing a tmp_path thumbnail_dir (as tests do) keeps the
        # index out of /var/lib too.
        self._index_path = index_path if index_path is not None else thumbnail_dir.parent / "library.json"

    def scan(self) -> List[Movie]:
        """Full (re)scan: probes every file with ffprobe/ffmpeg and persists
        the result to the JSON index for a later load() to pick up."""
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
        self._write_index()
        return movies

    def load(self) -> List[Movie]:
        """Fast startup path: reads the JSON index scan() last wrote instead
        of touching ffprobe/ffmpeg. Falls back to a full scan() if there's
        no index yet (e.g. local/dev runs that skip the separate scan step)."""
        if not self._index_path.is_file():
            logger.info("No library index at %s - scanning %s directly", self._index_path, self.root)
            return self.scan()

        entries = json.loads(self._index_path.read_text())

        movies = []
        paths = {}
        thumbnail_paths = {}
        for entry in entries:
            movie_id = entry["id"]
            movies.append(Movie(id=movie_id, title=entry["title"], duration_seconds=entry["duration_seconds"]))
            paths[movie_id] = self.root / entry["filename"]

            thumbnail_path = self._thumbnail_dir / f"{movie_id}.jpg"
            if thumbnail_path.is_file():
                thumbnail_paths[movie_id] = thumbnail_path

        self._movies = movies
        self._paths = paths
        self._thumbnail_paths = thumbnail_paths
        logger.info("Loaded %d movie(s) from index %s", len(movies), self._index_path)
        return movies

    def _write_index(self) -> None:
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            {
                "id": movie.id,
                "filename": self._paths[movie.id].name,
                "title": movie.title,
                "duration_seconds": movie.duration_seconds,
            }
            for movie in self._movies
        ]
        self._index_path.write_text(json.dumps(entries, indent=2))

    @property
    def movies(self) -> List[Movie]:
        return self._movies

    def path_for(self, movie_id: int) -> Path:
        return self._paths[movie_id]

    def thumbnail_path_for(self, movie_id: int) -> Optional[Path]:
        return self._thumbnail_paths.get(movie_id)

    def save_uploaded_thumbnail(self, movie_id: int, data: bytes) -> None:
        """Overwrites the cached thumbnail with a phone-supplied "official" one
        (e.g. fetched from TMDB), so future requests - from any device - get
        it instead of the local ffmpeg frame grab."""
        self._thumbnail_dir.mkdir(parents=True, exist_ok=True)
        thumbnail_path = self._thumbnail_dir / f"{movie_id}.jpg"
        thumbnail_path.write_bytes(data)
        self._thumbnail_paths[movie_id] = thumbnail_path

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
