"""The GATT service exposed to the iOS app: wires BLE characteristics to the
movie library and the mpv player controller."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from bluez_peripheral.gatt.characteristic import CharacteristicFlags as CharFlags
from bluez_peripheral.gatt.characteristic import characteristic
from bluez_peripheral.gatt.service import Service

from . import protocol
from .library import MovieLibrary
from .player import MpvController
from .protocol import Command, Opcode, PlaybackState, PlaybackStatus

logger = logging.getLogger(__name__)

STATUS_POLL_INTERVAL_SECONDS = 1.0


class MagicBoxService(Service):
    def __init__(self, library: MovieLibrary, player: MpvController):
        super().__init__(protocol.SERVICE_UUID, True)
        self._library = library
        self._player = player
        self._current_movie_id: Optional[int] = None
        self._library_bytes = protocol.encode_library(library.movies)
        self._status_bytes = protocol.encode_status(PlaybackState.idle())
        self._poll_task: Optional[asyncio.Task] = None

    def start_status_polling(self) -> None:
        self._poll_task = asyncio.create_task(self._poll_status_loop())

    async def stop_status_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()

    def refresh_library(self) -> None:
        self._library_bytes = protocol.encode_library(self._library.movies)
        self.library.changed(self._library_bytes)

    async def _poll_status_loop(self) -> None:
        while True:
            await asyncio.sleep(STATUS_POLL_INTERVAL_SECONDS)
            await self._refresh_status()

    async def _refresh_status(self) -> None:
        idle = await self._player.get_idle()
        if idle:
            state = PlaybackState.idle()
            self._current_movie_id = None
        else:
            paused = await self._player.get_paused()
            position = await self._player.get_position()
            state = PlaybackState(
                status=PlaybackStatus.PAUSED if paused else PlaybackStatus.PLAYING,
                movie_id=self._current_movie_id,
                position_seconds=position,
            )

        new_bytes = protocol.encode_status(state)
        if new_bytes != self._status_bytes:
            self._status_bytes = new_bytes
            self.status.changed(new_bytes)

    async def _handle_command(self, cmd: Command) -> None:
        if cmd.opcode == Opcode.SELECT_MOVIE and cmd.argument is not None:
            self._current_movie_id = cmd.argument
            await self._player.load(self._library.path_for(cmd.argument))
        elif cmd.opcode == Opcode.PLAY:
            await self._player.play()
        elif cmd.opcode == Opcode.PAUSE:
            await self._player.pause()
        elif cmd.opcode == Opcode.STOP:
            await self._player.stop()
            self._current_movie_id = None
        elif cmd.opcode == Opcode.SEEK and cmd.argument is not None:
            await self._player.seek(cmd.argument)
        await self._refresh_status()

    # MARK: - Characteristics

    @characteristic(protocol.COMMAND_CHARACTERISTIC_UUID, CharFlags.WRITE)
    def command(self, options):
        pass  # write-only; value handled by the setter below

    @command.setter
    def _command_write(self, value, options):
        try:
            cmd = protocol.decode_command(bytes(value))
        except ValueError as exc:
            logger.warning("Dropping malformed command payload: %s", exc)
            return
        asyncio.create_task(self._handle_command(cmd))

    @characteristic(protocol.STATUS_CHARACTERISTIC_UUID, CharFlags.READ | CharFlags.NOTIFY)
    def status(self, options):
        return self._status_bytes

    @characteristic(protocol.LIBRARY_CHARACTERISTIC_UUID, CharFlags.READ)
    def library(self, options):
        return self._library_bytes
