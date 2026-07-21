"""Plain HTTP transport for dev/testing without Bluetooth.

Enable with MAGICBOX_TRANSPORT=http (see main.py). Mirrors the same
PlaybackController the BLE GATT service uses, just over JSON/REST instead of
GATT characteristics - useful when there's no BlueZ available (e.g. running
in Docker Desktop on macOS) or no BLE-capable client at hand.
"""
from __future__ import annotations

import logging

from aiohttp import web

from ..controllers.playback_controller import PlaybackController
from ..models.protocol import Command, Opcode

logger = logging.getLogger(__name__)

_OPCODE_BY_NAME = {opcode.name.lower(): opcode for opcode in Opcode}
_CONTROLLER_KEY = web.AppKey("controller", PlaybackController)


def create_app(controller: PlaybackController) -> web.Application:
    app = web.Application()
    app[_CONTROLLER_KEY] = controller

    app.router.add_get("/movies", _get_movies)
    app.router.add_get("/movies/{id}/thumbnail", _get_thumbnail)
    app.router.add_get("/status", _get_status)
    app.router.add_post("/command", _post_command)
    return app


async def _get_movies(request: web.Request) -> web.Response:
    controller = request.app[_CONTROLLER_KEY]
    return web.json_response([
        {"id": movie.id, "title": movie.title, "duration_seconds": movie.duration_seconds}
        for movie in controller.movies
    ])


async def _get_thumbnail(request: web.Request) -> web.StreamResponse:
    controller = request.app[_CONTROLLER_KEY]
    try:
        movie_id = int(request.match_info["id"])
    except ValueError:
        return web.json_response({"error": "invalid movie id"}, status=400)

    thumbnail_path = controller.library.thumbnail_path_for(movie_id)
    if thumbnail_path is None:
        return web.json_response({"error": "no thumbnail for this movie"}, status=404)
    return web.FileResponse(thumbnail_path)


async def _get_status(request: web.Request) -> web.Response:
    controller = request.app[_CONTROLLER_KEY]
    state = await controller.refresh_status()
    return web.json_response({
        "status": state.status.name.lower(),
        "movie_id": state.movie_id,
        "position_seconds": state.position_seconds,
    })


async def _post_command(request: web.Request) -> web.Response:
    controller = request.app[_CONTROLLER_KEY]
    payload = await request.json()
    opcode_name = str(payload.get("opcode", "")).lower()
    opcode = _OPCODE_BY_NAME.get(opcode_name)
    if opcode is None:
        return web.json_response({"error": f"unknown opcode {opcode_name!r}"}, status=400)

    argument = payload.get("argument")
    cmd = Command(opcode=opcode, argument=None if argument is None else int(argument))
    await controller.handle_command(cmd)
    return web.json_response({"ok": True})
