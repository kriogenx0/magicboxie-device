"""Transport-agnostic playback control: wraps the movie library and mpv,
independent of whether commands arrive over BLE or plain HTTP."""
from __future__ import annotations

import logging
from typing import List, Optional

from ..models.library import MovieLibrary
from ..models.player import MpvController
from ..models.protocol import Command, Movie, Opcode, PlaybackState, PlaybackStatus

logger = logging.getLogger(__name__)


class PlaybackController:
    def __init__(self, library: MovieLibrary, player: MpvController):
        self.library = library
        self.player = player
        self._current_movie_id: Optional[int] = None

    @property
    def movies(self) -> List[Movie]:
        return self.library.movies

    async def handle_command(self, cmd: Command) -> None:
        if cmd.opcode == Opcode.SELECT_MOVIE and cmd.argument is not None:
            self._current_movie_id = cmd.argument
            await self.player.load(self.library.path_for(cmd.argument))
        elif cmd.opcode == Opcode.PLAY:
            await self.player.play()
        elif cmd.opcode == Opcode.PAUSE:
            await self.player.pause()
        elif cmd.opcode == Opcode.STOP:
            await self.player.stop()
            self._current_movie_id = None
        elif cmd.opcode == Opcode.SEEK and cmd.argument is not None:
            await self.player.seek(cmd.argument)

    async def refresh_status(self) -> PlaybackState:
        idle = await self.player.get_idle()
        if idle:
            self._current_movie_id = None
            return PlaybackState.idle()

        paused = await self.player.get_paused()
        position = await self.player.get_position()
        return PlaybackState(
            status=PlaybackStatus.PAUSED if paused else PlaybackStatus.PLAYING,
            movie_id=self._current_movie_id,
            position_seconds=position,
        )
