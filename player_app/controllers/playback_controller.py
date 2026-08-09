"""Transport-agnostic playback control: wraps the movie library and mpv,
independent of whether commands arrive over BLE or plain HTTP."""
from __future__ import annotations

import logging
from typing import List, Optional

from ..models.idle_screen import render_idle_screen
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

    @property
    def is_idle(self) -> bool:
        """Whether anything is currently selected to play - checked by
        TranscodeService before starting (or continuing) a background
        transcode, since that's CPU-intensive enough to compete directly
        with playback decode on this device's single core."""
        return self._current_movie_id is None

    async def handle_command(self, cmd: Command) -> None:
        if cmd.opcode == Opcode.SELECT_MOVIE and cmd.argument is not None:
            self._current_movie_id = cmd.argument
            await self.player.load(self.library.playable_path_for(cmd.argument))
        elif cmd.opcode == Opcode.PLAY:
            await self.player.play()
        elif cmd.opcode == Opcode.PAUSE:
            await self.player.pause()
        elif cmd.opcode == Opcode.STOP:
            await self.stop_and_show_idle_screen()
        elif cmd.opcode == Opcode.SEEK and cmd.argument is not None:
            await self.player.seek(cmd.argument)

    async def show_idle_screen(self) -> None:
        """Displays the thumbnail-grid home screen - the device's resting
        state whenever nothing is selected to play (at startup, and after
        stop_and_show_idle_screen())."""
        image_path = render_idle_screen(self.library)
        await self.player.show_image(image_path)

    async def stop_and_show_idle_screen(self) -> None:
        """What both an explicit stop command and the local keyboard's
        Escape key do - stop whatever's playing and return to the thumbnail
        grid, so the screen never just goes blank or freezes on the last
        frame."""
        await self.player.stop()
        self._current_movie_id = None
        await self.show_idle_screen()

    async def refresh_status(self) -> PlaybackState:
        # Nothing selected - already known to be idle without asking mpv,
        # which would otherwise report "not idle" while the idle-screen
        # image itself is loaded (see MpvController.show_image).
        if self._current_movie_id is None:
            return PlaybackState.idle()

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
