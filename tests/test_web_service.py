import asyncio

from aiohttp.test_utils import TestClient, TestServer
from fakes import FakeLibrary, FakeMpv

from magicbox_device.controllers.playback_controller import PlaybackController
from magicbox_device.views.web_service import create_app


async def _make_client(library=None):
    controller = PlaybackController(library or FakeLibrary(), FakeMpv())
    app = create_app(controller)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, controller


def test_get_movies():
    async def scenario():
        client, _ = await _make_client()
        try:
            resp = await client.get("/movies")
            assert resp.status == 200
            return await resp.json()
        finally:
            await client.close()

    data = asyncio.run(scenario())
    assert data == [
        {"id": 0, "title": "A", "duration_seconds": 100},
        {"id": 1, "title": "B", "duration_seconds": 200},
    ]


def test_post_command_select_and_play_reflected_in_status():
    async def scenario():
        client, _ = await _make_client()
        try:
            resp = await client.post("/command", json={"opcode": "select_movie", "argument": 1})
            assert resp.status == 200
            resp = await client.get("/status")
            return await resp.json()
        finally:
            await client.close()

    data = asyncio.run(scenario())
    assert data["status"] == "playing"
    assert data["movie_id"] == 1


def test_post_command_unknown_opcode_returns_400():
    async def scenario():
        client, _ = await _make_client()
        try:
            resp = await client.post("/command", json={"opcode": "not_a_real_command"})
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 400


def test_get_thumbnail_returns_file_bytes(tmp_path):
    thumbnail_path = tmp_path / "0.jpg"
    thumbnail_path.write_bytes(b"fake-jpeg-bytes")

    async def scenario():
        client, _ = await _make_client(FakeLibrary(thumbnail_paths={0: thumbnail_path}))
        try:
            resp = await client.get("/movies/0/thumbnail")
            assert resp.status == 200
            return await resp.read()
        finally:
            await client.close()

    assert asyncio.run(scenario()) == b"fake-jpeg-bytes"


def test_get_thumbnail_missing_returns_404():
    async def scenario():
        client, _ = await _make_client()
        try:
            resp = await client.get("/movies/0/thumbnail")
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 404


def test_get_thumbnail_invalid_id_returns_400():
    async def scenario():
        client, _ = await _make_client()
        try:
            resp = await client.get("/movies/not-a-number/thumbnail")
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 400
