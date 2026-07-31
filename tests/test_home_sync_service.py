import asyncio

from aioresponses import aioresponses

from magicbox_device.models.library import MovieLibrary
from magicbox_device.views.home_sync_service import HomeServerSync

BASE_URL = "http://home.example.com:8080"


def _library(tmp_path):
    movies_dir = tmp_path / "movies"
    movies_dir.mkdir()
    return MovieLibrary(movies_dir, thumbnail_dir=tmp_path / "thumbnails")


def test_check_in_downloads_ready_movie_and_saves_metadata(tmp_path):
    library = _library(tmp_path)
    sync = HomeServerSync(library, BASE_URL, "secret")

    with aioresponses() as mocked:
        mocked.post(f"{BASE_URL}/api/v1/auth/login", payload={"token": "tok123"})
        mocked.get(
            f"{BASE_URL}/api/v1/movies",
            payload=[
                {
                    "id": 1,
                    "title": "Alpha",
                    "overview": "A movie.",
                    "year": 1999,
                    "duration_seconds": 123.4,
                    "original_filename": "alpha.mkv",
                    "status": "ready",
                },
                {
                    "id": 2,
                    "title": "Still Transcoding",
                    "status": "needs_transcode",
                },
            ],
        )
        mocked.get(f"{BASE_URL}/api/v1/movies/1/stream", body=b"fake-video-bytes")

        asyncio.run(sync.check_in())

    titles = [m.title for m in library.movies]
    assert titles == ["Alpha"]
    assert (tmp_path / "movies" / "Alpha.mkv").read_bytes() == b"fake-video-bytes"

    movie = library.movies[0]
    assert library.metadata_for(movie.id) == {
        "title": "Alpha",
        "description": "A movie.",
        "year": 1999,
        "duration_seconds": 123,
    }


def test_check_in_skips_movie_already_present_locally(tmp_path):
    library = _library(tmp_path)
    (tmp_path / "movies" / "Alpha.mp4").write_bytes(b"already-here")
    library.scan()
    sync = HomeServerSync(library, BASE_URL, "secret")

    with aioresponses() as mocked:
        mocked.post(f"{BASE_URL}/api/v1/auth/login", payload={"token": "tok123"})
        mocked.get(
            f"{BASE_URL}/api/v1/movies",
            payload=[{"id": 1, "title": "Alpha", "status": "ready", "original_filename": "alpha.mp4"}],
        )
        # No /stream mock registered - if the code tries to download despite
        # the movie already being local, aioresponses raises for the
        # unmatched request and the test fails.
        asyncio.run(sync.check_in())

    assert (tmp_path / "movies" / "Alpha.mp4").read_bytes() == b"already-here"


def test_check_in_does_nothing_when_login_fails(tmp_path):
    library = _library(tmp_path)
    sync = HomeServerSync(library, BASE_URL, "wrong-password")

    with aioresponses() as mocked:
        mocked.post(f"{BASE_URL}/api/v1/auth/login", status=401, payload={"error": "invalid password"})
        # No /movies mock registered - a login failure must stop check_in()
        # before it lists movies, or aioresponses raises for the unmatched call.
        asyncio.run(sync.check_in())

    assert library.movies == []


def test_check_in_handles_unreachable_movies_list(tmp_path):
    library = _library(tmp_path)
    sync = HomeServerSync(library, BASE_URL, "secret")

    with aioresponses() as mocked:
        mocked.post(f"{BASE_URL}/api/v1/auth/login", payload={"token": "tok123"})
        mocked.get(f"{BASE_URL}/api/v1/movies", status=500)
        asyncio.run(sync.check_in())

    assert library.movies == []
