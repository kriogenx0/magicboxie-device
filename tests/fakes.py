"""Fakes for testing PlaybackController/transports without real mpv or BlueZ."""
from pathlib import Path

from magicboxie_device.models.protocol import Movie


class FakeMpv:
    def __init__(self):
        self.loaded_path = None
        self.shown_image_path = None
        self.paused = True
        self.idle = True
        self.position = 0

    async def load(self, path):
        self.loaded_path = path
        self.idle = False
        self.paused = False

    async def show_image(self, path):
        self.shown_image_path = path
        self.idle = False
        self.paused = True

    async def play(self):
        self.paused = False

    async def pause(self):
        self.paused = True

    async def stop(self):
        self.idle = True
        self.paused = True
        self.position = 0

    async def seek(self, position_seconds):
        self.position = position_seconds

    async def get_position(self):
        return self.position

    async def get_paused(self):
        return self.paused

    async def get_idle(self):
        return self.idle


class FakeLibrary:
    def __init__(self, thumbnail_paths=None, thumbnail_dir=None, metadata=None):
        self._paths = {0: Path("/movies/a.mp4"), 1: Path("/movies/b.mp4")}
        self._thumbnail_paths = thumbnail_paths or {}
        self._thumbnail_dir = thumbnail_dir
        self._metadata = metadata or {}

    @property
    def movies(self):
        return [
            Movie(id=0, title="A", duration_seconds=100),
            Movie(id=1, title="B", duration_seconds=200),
        ]

    def path_for(self, movie_id):
        return self._paths[movie_id]

    def thumbnail_path_for(self, movie_id):
        return self._thumbnail_paths.get(movie_id)

    def save_uploaded_thumbnail(self, movie_id, data):
        if self._thumbnail_dir is None:
            raise RuntimeError("FakeLibrary needs thumbnail_dir to save uploads")
        path = self._thumbnail_dir / f"{movie_id}.jpg"
        path.write_bytes(data)
        self._thumbnail_paths[movie_id] = path

    def metadata_for(self, movie_id):
        return self._metadata.get(movie_id, {})

    def save_metadata(self, movie_id, **fields):
        updated = {**self._metadata.get(movie_id, {}), **fields}
        self._metadata[movie_id] = updated
        return updated
