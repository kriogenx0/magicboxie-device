"""Scans a directory of video files and exposes them via protocol.Movie."""
from __future__ import annotations

import json
import logging
import subprocess
import zlib
from pathlib import Path
from typing import Dict, List, Optional

from .protocol import Movie

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".m4v"}

DEFAULT_THUMBNAIL_DIR = Path("/var/lib/magicboxie/thumbnails")
DEFAULT_TRANSCODE_DIR = Path("/var/lib/magicboxie/transcoded")
THUMBNAIL_TIMESTAMP_SECONDS = 60
THUMBNAIL_WIDTH = 200

# How long to wait for ffprobe to report a file's duration. Was 10s, which
# sounds generous but isn't on a Pi Zero W: probing a real, multi-hundred-MB
# movie (as opposed to the tiny synthetic clips used in dev) measured ~19s
# there, so every real movie was silently timing out and getting recorded
# with duration=0. A one-shot per-movie cost at scan time, not per playback,
# so there's no reason to keep this tight.
PROBE_TIMEOUT_SECONDS = 60

# Movie ids must stay under this - protocol.encode_status packs movie_id into
# 2 bytes with 0xFFFF reserved to mean "no movie" (see protocol.py's
# _NO_MOVIE_SENTINEL), so valid ids run 0..0xFFFE.
_MOVIE_ID_SPACE = 0xFFFF


class MovieLibrary:
    def __init__(
        self,
        root: Path,
        thumbnail_dir: Path = DEFAULT_THUMBNAIL_DIR,
        transcode_dir: Path = DEFAULT_TRANSCODE_DIR,
    ):
        # The movies directory is typically mounted read-only, so thumbnails
        # (and phone-supplied metadata) are cached in a separate, writable
        # location instead of alongside it.
        self.root = root
        self._movies: List[Movie] = []
        self._paths: Dict[int, Path] = {}
        self._thumbnail_paths: Dict[int, Path] = {}
        self._metadata: Dict[int, dict] = {}
        self._thumbnail_dir = thumbnail_dir
        self._transcode_dir = transcode_dir

    def scan(self) -> List[Movie]:
        """Reads the movies directory from the filesystem and caches the
        result (title, duration, thumbnail, metadata) in memory for fast
        lookups."""
        self._thumbnail_dir.mkdir(parents=True, exist_ok=True)

        files = sorted(
            p for p in self.root.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        )

        movies = []
        paths = {}
        thumbnail_paths = {}
        metadata = {}
        for path in files:
            movie_id = self._stable_id(path, taken=paths)
            movies.append(
                Movie(id=movie_id, title=path.stem, duration_seconds=self._probe_duration(path))
            )
            paths[movie_id] = path

            thumbnail = self._ensure_thumbnail(movie_id, path)
            if thumbnail is not None:
                thumbnail_paths[movie_id] = thumbnail

            metadata[movie_id] = self._load_metadata(movie_id)

        self._movies = movies
        self._paths = paths
        self._thumbnail_paths = thumbnail_paths
        self._metadata = metadata
        logger.info("Scanned %d movie(s) in %s", len(movies), self.root)
        return movies

    @property
    def movies(self) -> List[Movie]:
        return self._movies

    def path_for(self, movie_id: int) -> Path:
        return self._paths[movie_id]

    def transcode_path_for(self, movie_id: int) -> Path:
        """Where TranscodeService writes (or would write) a version of this
        movie re-encoded to something this device's CPU can decode smoothly.
        Doesn't imply the file exists yet - see playable_path_for()."""
        return self._transcode_dir / f"{movie_id}.mp4"

    def playable_path_for(self, movie_id: int) -> Path:
        """What to actually hand mpv: a background-transcoded copy if
        TranscodeService has finished one, otherwise the original. The
        original may be too demanding for this device's weak CPU to decode
        smoothly, which is the whole reason TranscodeService exists."""
        transcoded = self.transcode_path_for(movie_id)
        return transcoded if transcoded.exists() else self._paths[movie_id]

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

    def metadata_for(self, movie_id: int) -> dict:
        return self._metadata.get(movie_id, {})

    def save_metadata(self, movie_id: int, **fields) -> dict:
        """Merges phone-supplied metadata (e.g. title/description/year fetched
        online) into what's cached for this movie and persists it to disk
        alongside the thumbnail, so it survives a rescan/restart and is
        available to any device that connects."""
        self._thumbnail_dir.mkdir(parents=True, exist_ok=True)
        updated = {**self._metadata.get(movie_id, {}), **fields}
        self._metadata[movie_id] = updated
        metadata_path = self._thumbnail_dir / f"{movie_id}.json"
        metadata_path.write_text(json.dumps(updated))
        return updated

    @staticmethod
    def _stable_id(path: Path, taken: Dict[int, Path]) -> int:
        """A movie's id must stay the same across rescans regardless of what
        other files exist - it's used both over the wire (a client that
        selects/reports on an id from one scan needs it to still mean the
        same movie after the next) and to key persisted thumbnail/metadata
        files on disk. The previous scheme (a plain enumerate() index over
        the sorted file list) shifted for every movie whenever a file was
        added or removed anywhere earlier in sort order, silently
        reattaching one movie's thumbnail/metadata/selection to whatever
        movie now landed on its old id. Deriving the id from the filename
        alone fixes that: it only changes if the file itself is renamed.

        taken is the id->path mapping built so far this scan, used to probe
        past a hash collision (rare for a personal-library-sized directory,
        but cheap to handle) rather than letting two files silently share
        an id.
        """
        movie_id = zlib.crc32(path.name.encode("utf-8")) % _MOVIE_ID_SPACE
        while movie_id in taken:
            movie_id = (movie_id + 1) % _MOVIE_ID_SPACE
        return movie_id

    def _load_metadata(self, movie_id: int) -> dict:
        metadata_path = self._thumbnail_dir / f"{movie_id}.json"
        if not metadata_path.is_file():
            return {}
        try:
            return json.loads(metadata_path.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("Could not read metadata for movie %d: %s", movie_id, exc)
            return {}

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
                timeout=PROBE_TIMEOUT_SECONDS,
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
