import asyncio

from aiohttp.test_utils import TestClient, TestServer
from fakes import FakeLibrary, FakeMpv

from magicbox_device.controllers.playback_controller import PlaybackController
from magicbox_device.models.library import MovieLibrary
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


def test_post_thumbnail_upload_then_get_returns_uploaded_bytes(tmp_path):
    async def scenario():
        client, _ = await _make_client(FakeLibrary(thumbnail_dir=tmp_path))
        try:
            resp = await client.post("/movies/0/thumbnail", data=b"official-poster-bytes")
            assert resp.status == 200
            resp = await client.get("/movies/0/thumbnail")
            assert resp.status == 200
            return await resp.read()
        finally:
            await client.close()

    assert asyncio.run(scenario()) == b"official-poster-bytes"


def test_post_thumbnail_unknown_movie_returns_404():
    async def scenario():
        client, _ = await _make_client()
        try:
            resp = await client.post("/movies/99/thumbnail", data=b"bytes")
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 404


def test_post_thumbnail_invalid_id_returns_400():
    async def scenario():
        client, _ = await _make_client()
        try:
            resp = await client.post("/movies/not-a-number/thumbnail", data=b"bytes")
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 400


def test_post_thumbnail_empty_body_returns_400(tmp_path):
    async def scenario():
        client, _ = await _make_client(FakeLibrary(thumbnail_dir=tmp_path))
        try:
            resp = await client.post("/movies/0/thumbnail", data=b"")
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 400


def _real_library(tmp_path):
    movies_dir = tmp_path / "movies"
    movies_dir.mkdir()
    library = MovieLibrary(movies_dir, thumbnail_dir=tmp_path / "thumbnails")
    library.scan()
    return library


def test_post_movie_uploads_and_appears_in_library(tmp_path):
    library = _real_library(tmp_path)

    async def scenario():
        client, _ = await _make_client(library)
        try:
            resp = await client.post(
                "/movies",
                data=b"fake-video-bytes",
                headers={"X-Filename": "New Movie.mp4"},
            )
            assert resp.status == 201
            body = await resp.json()
            assert body["title"] == "New Movie"

            resp = await client.get("/movies")
            return await resp.json()
        finally:
            await client.close()

    movies = asyncio.run(scenario())
    assert [m["title"] for m in movies] == ["New Movie"]
    assert (tmp_path / "movies" / "New Movie.mp4").read_bytes() == b"fake-video-bytes"


def test_post_movie_missing_filename_header_returns_400(tmp_path):
    library = _real_library(tmp_path)

    async def scenario():
        client, _ = await _make_client(library)
        try:
            resp = await client.post("/movies", data=b"bytes")
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 400


def test_post_movie_unsupported_extension_returns_400(tmp_path):
    library = _real_library(tmp_path)

    async def scenario():
        client, _ = await _make_client(library)
        try:
            resp = await client.post(
                "/movies", data=b"bytes", headers={"X-Filename": "not-a-video.txt"}
            )
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 400


def test_post_movie_duplicate_filename_returns_409(tmp_path):
    library = _real_library(tmp_path)
    (tmp_path / "movies" / "Existing.mp4").write_bytes(b"already-here")

    async def scenario():
        client, _ = await _make_client(library)
        try:
            resp = await client.post(
                "/movies", data=b"new-bytes", headers={"X-Filename": "Existing.mp4"}
            )
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 409


def test_post_movie_empty_body_returns_400(tmp_path):
    library = _real_library(tmp_path)

    async def scenario():
        client, _ = await _make_client(library)
        try:
            resp = await client.post(
                "/movies", data=b"", headers={"X-Filename": "Empty.mp4"}
            )
            return resp.status
        finally:
            await client.close()

    assert asyncio.run(scenario()) == 400
    assert not (tmp_path / "movies" / "Empty.mp4").exists()
