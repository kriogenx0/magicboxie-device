"""Opportunistic sync with the home server (MagicBox-web): when the device
has internet, downloads any "ready" movies it doesn't have locally yet,
along with their metadata (title/description/year/duration). The device
spends most of its life offline, so a failed check-in (server unreachable,
DNS failure, etc.) is the normal case, not an error - see _run_home_sync in
main.py, which retries on an interval and just logs and moves on.

MagicBox-web speaks the real Jellyfin REST API (see its
internal/controllers/items_controller.go) plus a handful of additive
"MagicBox*"-prefixed fields real Jellyfin clients don't have -- status,
progress, and original filename -- which this sync relies on to decide
what's actually downloadable and how to name the local file.

Thumbnails aren't fetched here - once a movie's file lands locally, the next
MovieLibrary.scan() grabs a frame from it with ffmpeg like any other movie.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import aiohttp

from ..models.library import VIDEO_EXTENSIONS, MovieLibrary

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 10
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_READY_STATUS = "ready"
_USER_ID = "1"  # MagicBox-web has one shared login, not per-user accounts
_TICKS_PER_SECOND = 10_000_000  # Jellyfin's RunTimeTicks unit is 100ns


class HomeServerSync:
    def __init__(self, library: MovieLibrary, base_url: str, password: str):
        self._library = library
        self._base_url = base_url.rstrip("/")
        self._password = password

    async def check_in(self) -> None:
        async with aiohttp.ClientSession() as session:
            token = await self._authenticate(session)
            if token is None:
                return
            headers = {"Authorization": f"Bearer {token}"}

            try:
                remote_movies = await self._list_ready_movies(session, headers)
            except (aiohttp.ClientError, TimeoutError) as exc:
                logger.info("Home server check-in: couldn't list movies (%s)", exc)
                return

            existing_titles = {movie.title for movie in self._library.movies}
            to_download = [m for m in remote_movies if m["Name"] not in existing_titles]
            if not to_download:
                logger.info("Home server check-in: nothing new")
                return

            logger.info("Home server check-in: downloading %d new movie(s)", len(to_download))
            downloaded = [
                movie for movie in to_download if await self._download_movie(session, headers, movie)
            ]
            if not downloaded:
                return

            self._library.scan()
            for remote_movie in downloaded:
                self._save_metadata(remote_movie)

    async def _authenticate(self, session: aiohttp.ClientSession):
        try:
            async with session.post(
                f"{self._base_url}/Users/AuthenticateByName",
                json={"Username": "magicbox-device", "Pw": self._password},
                timeout=aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status != 200:
                    logger.info("Home server check-in: login failed (HTTP %d)", resp.status)
                    return None
                data = await resp.json()
                return data.get("AccessToken")
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.info("Home server check-in: unreachable (%s)", exc)
            return None

    async def _list_ready_movies(self, session: aiohttp.ClientSession, headers: dict) -> List[dict]:
        async with session.get(
            f"{self._base_url}/Users/{_USER_ID}/Items",
            params={"IncludeItemTypes": "Movie", "Recursive": "true"},
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        items = data.get("Items", [])
        return [item for item in items if item.get("MagicBoxStatus") == _READY_STATUS]

    async def _download_movie(self, session: aiohttp.ClientSession, headers: dict, movie: dict) -> bool:
        dest_path = self._library.root / self._local_filename(movie)
        if dest_path.exists():
            return False

        logger.info("Home server check-in: downloading %r", movie["Name"])
        try:
            async with session.get(
                f"{self._base_url}/Videos/{movie['Id']}/stream",
                params={"static": "true"},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=None),
            ) as resp:
                if resp.status != 200:
                    logger.warning("Home server check-in: download of %r failed (HTTP %d)", movie["Name"], resp.status)
                    return False
                with dest_path.open("wb") as f:
                    async for chunk in resp.content.iter_chunked(_DOWNLOAD_CHUNK_BYTES):
                        f.write(chunk)
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            logger.warning("Home server check-in: download of %r failed (%s)", movie["Name"], exc)
            dest_path.unlink(missing_ok=True)
            return False
        return True

    def _save_metadata(self, remote_movie: dict) -> None:
        local_movie = next(
            (m for m in self._library.movies if m.title == remote_movie["Name"]), None
        )
        if local_movie is None:
            return
        self._library.save_metadata(
            local_movie.id,
            title=remote_movie["Name"],
            description=remote_movie.get("Overview") or "",
            year=int(remote_movie.get("ProductionYear") or 0),
            duration_seconds=int((remote_movie.get("RunTimeTicks") or 0) / _TICKS_PER_SECOND),
        )

    @staticmethod
    def _local_filename(movie: dict) -> str:
        original = Path(movie.get("MagicBoxOriginalFilename") or "")
        extension = original.suffix.lower() if original.suffix.lower() in VIDEO_EXTENSIONS else ".mp4"
        # Titles come from the home server's own TMDB matching/filename
        # parsing and may contain "/" (e.g. "Fast/Furious") - not valid in a
        # single path component, so it gets swapped for a dash.
        safe_title = movie["Name"].replace("/", "-").lstrip(".")
        return f"{safe_title}{extension}"
