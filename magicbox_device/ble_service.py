"""The GATT service exposed to the iOS app: wires BLE characteristics to a
PlaybackController. Wire format only concerns itself here - actual movie
library/mpv logic lives in PlaybackController so it can be shared with the
HTTP transport too."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from bluez_peripheral.gatt.characteristic import CharacteristicFlags as CharFlags
from bluez_peripheral.gatt.characteristic import characteristic
from bluez_peripheral.gatt.service import Service

from . import protocol
from .playback_controller import PlaybackController
from .protocol import PlaybackState

logger = logging.getLogger(__name__)

STATUS_POLL_INTERVAL_SECONDS = 1.0


class MagicBoxService(Service):
    def __init__(self, controller: PlaybackController):
        super().__init__(protocol.SERVICE_UUID, True)
        self._controller = controller
        self._library_bytes = protocol.encode_library(controller.movies)
        self._status_bytes = protocol.encode_status(PlaybackState.idle())
        self._poll_task: Optional[asyncio.Task] = None

    def start_status_polling(self) -> None:
        self._poll_task = asyncio.create_task(self._poll_status_loop())

    async def stop_status_polling(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()

    def refresh_library(self) -> None:
        self._library_bytes = protocol.encode_library(self._controller.movies)
        self.library.changed(self._library_bytes)

    async def _poll_status_loop(self) -> None:
        while True:
            await asyncio.sleep(STATUS_POLL_INTERVAL_SECONDS)
            await self._refresh_status()

    async def _refresh_status(self) -> None:
        state = await self._controller.refresh_status()
        new_bytes = protocol.encode_status(state)
        if new_bytes != self._status_bytes:
            self._status_bytes = new_bytes
            self.status.changed(new_bytes)

    async def _handle_and_refresh(self, cmd: protocol.Command) -> None:
        await self._controller.handle_command(cmd)
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
        asyncio.create_task(self._handle_and_refresh(cmd))

    @characteristic(protocol.STATUS_CHARACTERISTIC_UUID, CharFlags.READ | CharFlags.NOTIFY)
    def status(self, options):
        return self._status_bytes

    @characteristic(protocol.LIBRARY_CHARACTERISTIC_UUID, CharFlags.READ)
    def library(self, options):
        return self._library_bytes
