"""Fakes for testing PlaybackController/transports without real mpv or BlueZ."""
from pathlib import Path

from magicbox_device.protocol import Movie


class FakeMpv:
    def __init__(self):
        self.loaded_path = None
        self.paused = True
        self.idle = True
        self.position = 0

    async def load(self, path):
        self.loaded_path = path
        self.idle = False
        self.paused = False

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
    def __init__(self):
        self._paths = {0: Path("/movies/a.mp4"), 1: Path("/movies/b.mp4")}

    @property
    def movies(self):
        return [
            Movie(id=0, title="A", duration_seconds=100),
            Movie(id=1, title="B", duration_seconds=200),
        ]

    def path_for(self, movie_id):
        return self._paths[movie_id]
