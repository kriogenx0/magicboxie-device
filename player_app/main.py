"""Entrypoint: wires the movie library, mpv, and the transports together.

Production ("ble") mode runs both the BLE GATT service and the HTTP web
service concurrently: BLE is what the app uses to discover the device and
for control, but its tiny ATT payloads are a poor fit for bulk data (movie
library, thumbnails), so the app reads the device's own HTTP address off a
BLE characteristic and offers to switch to WiFi for those. "http" mode
(dev/testing - no Bluetooth required, e.g. no BlueZ on Docker Desktop/macOS)
runs the HTTP service alone.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from pathlib import Path
from typing import List

from .controllers.playback_controller import PlaybackController
from .models.library import MovieLibrary
from .models.player import MpvController

logger = logging.getLogger(__name__)

DEVICE_NAME = os.environ.get("MAGICBOXIE_DEVICE_NAME", "MagicBoxie")
MOVIES_DIR = Path(os.environ.get("MAGICBOXIE_MOVIES_DIR", "/movies"))
THUMBNAIL_DIR = Path(os.environ.get("MAGICBOXIE_THUMBNAIL_DIR", "/var/lib/magicboxie/thumbnails"))

# "ble" (default, real device) or "http" (dev/testing - no Bluetooth required,
# e.g. when there's no BlueZ available such as Docker Desktop on macOS).
TRANSPORT = os.environ.get("MAGICBOXIE_TRANSPORT", "ble")
HTTP_PORT = int(os.environ.get("MAGICBOXIE_HTTP_PORT", "8000"))

# bluez expires an advert after its Timeout elapses; re-registering periodically
# (well before that) keeps the device discoverable indefinitely.
ADVERT_TIMEOUT_SECONDS = 180
ADVERT_REFRESH_SECONDS = 150

# The home server (MagicBoxie-web) this device checks in with for new content
# when it has internet - see views/home_sync_service.py. Unset by default:
# the device works standalone (BLE/HTTP + whatever's already on disk), this
# is opportunistic on top of that, not a requirement.
HOME_SERVER_URL = os.environ.get("MAGICBOXIE_HOME_SERVER_URL", "")
HOME_SERVER_PASSWORD = os.environ.get("MAGICBOXIE_HOME_SERVER_PASSWORD", "")
HOME_SERVER_CHECKIN_SECONDS = int(os.environ.get("MAGICBOXIE_HOME_SERVER_CHECKIN_SECONDS", "600"))


def _mpv_output_args() -> List[str]:
    # Defaults target rendering straight to the framebuffer via DRM/KMS - the
    # Pi's own HDMI output, with no desktop environment running.
    # Override with MAGICBOXIE_MPV_ARGS if your hardware needs a different --vo/--gpu-context.
    raw = os.environ.get("MAGICBOXIE_MPV_ARGS", "--vo=gpu --gpu-context=drm")
    return raw.split()


def _local_ip() -> str:
    """Best-effort LAN IP: opens a UDP "connection" (no packets sent) to a
    public address just to see which local interface routing would use."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


async def _run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not MOVIES_DIR.is_dir():
        raise SystemExit(f"Movies directory does not exist: {MOVIES_DIR}")

    library = MovieLibrary(MOVIES_DIR, thumbnail_dir=THUMBNAIL_DIR)
    library.scan()

    player = MpvController(extra_args=_mpv_output_args())
    await player.start()

    controller = PlaybackController(library, player)
    # Resting state until something's selected to play - the screen should
    # never just be black/whatever mpv's own idle window looks like.
    await controller.show_idle_screen()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        tasks = [
            _run_http(controller, stop_event),
            _run_keyboard(controller, stop_event),
        ]
        if TRANSPORT != "http":
            tasks.append(_run_ble(controller, stop_event))
        if HOME_SERVER_URL:
            tasks.append(_run_home_sync(controller, stop_event))
        await asyncio.gather(*tasks)
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
    logger.info("Serving MagicBoxie web API on port %d", HTTP_PORT)

    await stop_event.wait()
    await runner.cleanup()


async def _run_keyboard(controller: PlaybackController, stop_event: asyncio.Event) -> None:
    """Escape-to-stop from a directly-attached USB keyboard - the device's
    only local input, independent of BLE/HTTP and the iOS app. Runs in both
    transport modes, and is a no-op if no keyboard is ever attached."""
    from .views.keyboard_service import KeyboardService

    await KeyboardService(controller).run(stop_event)


async def _run_ble(controller: PlaybackController, stop_event: asyncio.Event) -> None:
    from bluez_peripheral.advert import Advertisement
    from bluez_peripheral.agent import NoIoAgent
    from bluez_peripheral.util import Adapter, get_message_bus

    from .models import protocol
    from .views.ble_service import MagicBoxieService

    network_url = f"http://{_local_ip()}:{HTTP_PORT}"
    service = MagicBoxieService(controller, network_url)

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
            logger.info("Advertising as %r (WiFi: %s)", DEVICE_NAME, network_url)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=ADVERT_REFRESH_SECONDS)
            except asyncio.TimeoutError:
                continue
    finally:
        await service.stop_status_polling()


async def _run_home_sync(controller: PlaybackController, stop_event: asyncio.Event) -> None:
    """Retries a home server check-in on an interval. The device is offline
    most of the time, so a failed attempt (no route, DNS failure, etc.) is
    expected and just gets logged - not treated as fatal."""
    from .views.home_sync_service import HomeServerSync

    sync = HomeServerSync(controller.library, HOME_SERVER_URL, HOME_SERVER_PASSWORD)
    while not stop_event.is_set():
        try:
            await sync.check_in()
        except Exception:
            logger.exception("Home server check-in failed unexpectedly")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=HOME_SERVER_CHECKIN_SECONDS)
        except asyncio.TimeoutError:
            continue


def run() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    run()
