"""Entrypoint: wires the movie library, mpv, and either the BLE GATT service
or a plain HTTP web service (dev/testing, no Bluetooth) together."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path
from typing import List

from .controllers.playback_controller import PlaybackController
from .models.library import MovieLibrary
from .models.player import MpvController

logger = logging.getLogger(__name__)

DEVICE_NAME = os.environ.get("MAGICBOX_DEVICE_NAME", "MagicBox")
MOVIES_DIR = Path(os.environ.get("MAGICBOX_MOVIES_DIR", "/movies"))

# "ble" (default, real device) or "http" (dev/testing - no Bluetooth required,
# e.g. when there's no BlueZ available such as Docker Desktop on macOS).
TRANSPORT = os.environ.get("MAGICBOX_TRANSPORT", "ble")
HTTP_PORT = int(os.environ.get("MAGICBOX_HTTP_PORT", "8000"))

# bluez expires an advert after its Timeout elapses; re-registering periodically
# (well before that) keeps the device discoverable indefinitely.
ADVERT_TIMEOUT_SECONDS = 180
ADVERT_REFRESH_SECONDS = 150


def _mpv_output_args() -> List[str]:
    # Defaults target rendering straight to the framebuffer via DRM/KMS, which is
    # what feeds an HDMI-to-Component converter on a Pi with no desktop running.
    # Override with MAGICBOX_MPV_ARGS if your hardware needs a different --vo/--gpu-context.
    raw = os.environ.get("MAGICBOX_MPV_ARGS", "--vo=gpu --gpu-context=drm")
    return raw.split()


async def _run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not MOVIES_DIR.is_dir():
        raise SystemExit(f"Movies directory does not exist: {MOVIES_DIR}")

    library = MovieLibrary(MOVIES_DIR)
    library.scan()

    player = MpvController(extra_args=_mpv_output_args())
    await player.start()

    controller = PlaybackController(library, player)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        if TRANSPORT == "http":
            await _run_http(controller, stop_event)
        else:
            await _run_ble(controller, stop_event)
    finally:
        await player.stop_process()


async def _run_http(controller: PlaybackController, stop_event: asyncio.Event) -> None:
    from aiohttp import web

    from .views.web_service import create_app

    app = create_app(controller)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_PORT)
    await site.start()
    logger.info("Serving MagicBox web API on port %d (no Bluetooth)", HTTP_PORT)

    await stop_event.wait()
    await runner.cleanup()


async def _run_ble(controller: PlaybackController, stop_event: asyncio.Event) -> None:
    from bluez_peripheral.advert import Advertisement
    from bluez_peripheral.agent import NoIoAgent
    from bluez_peripheral.util import Adapter, get_message_bus

    from .models import protocol
    from .views.ble_service import MagicBoxService

    service = MagicBoxService(controller)

    bus = await get_message_bus()
    await service.register(bus)

    # Required for bluez to complete pairing requests; "no IO" since this
    # device has no screen/keyboard of its own to confirm a passkey with.
    agent = NoIoAgent()
    await agent.register(bus)

    adapter = await Adapter.get_first(bus)
    await adapter.set_alias(DEVICE_NAME)

    service.start_status_polling()

    try:
        while not stop_event.is_set():
            advert = Advertisement(DEVICE_NAME, [protocol.SERVICE_UUID], 0x0000, ADVERT_TIMEOUT_SECONDS)
            await advert.register(bus, adapter)
            logger.info("Advertising as %r", DEVICE_NAME)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=ADVERT_REFRESH_SECONDS)
            except asyncio.TimeoutError:
                continue
    finally:
        await service.stop_status_polling()


def run() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    run()
