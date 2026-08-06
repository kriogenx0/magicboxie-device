import asyncio

from aioresponses import aioresponses

from magicboxie_device.models.library import MovieLibrary
from magicboxie_device.views.home_sync_service import HomeServerSync

BASE_URL = "http://home.example.com:8080"


def _library(tmp_path):
    movies_dir = tmp_path / "movies"
    movies_dir.mkdir()
    return MovieLibrary(movies_dir, thumbnail_dir=tmp_path / "thumbnails")


def test_check_in_downloads_ready_movie_and_saves_metadata(tmp_path):
    library = _library(tmp_path)
    sync = HomeServerSync(library, BASE_URL, "secret")

    with aioresponses() as mocked:
        mocked.post(f"{BASE_URL}/Users/AuthenticateByName", payload={"AccessToken": "tok123"})
        mocked.get(
            f"{BASE_URL}/Users/1/Items?IncludeItemTypes=Movie&Recursive=true",
            payload={
                "Items": [
                    {
                        "Id": "1",
                        "Name": "Alpha",
                        "Overview": "A movie.",
                        "ProductionYear": 1999,
                        "RunTimeTicks": 1234000000,
                        "MagicBoxieOriginalFilename": "alpha.mkv",
                        "MagicBoxieStatus": "ready",
                    },
                    {
                        "Id": "2",
                        "Name": "Still Transcoding",
                        "MagicBoxieStatus": "needs_transcode",
                    },
                ],
                "TotalRecordCount": 2,
                "StartIndex": 0,
            },
        )
        mocked.get(f"{BASE_URL}/Videos/1/stream?static=true", body=b"fake-video-bytes")

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
        mocked.post(f"{BASE_URL}/Users/AuthenticateByName", payload={"AccessToken": "tok123"})
        mocked.get(
            f"{BASE_URL}/Users/1/Items?IncludeItemTypes=Movie&Recursive=true",
            payload={
                "Items": [
                    {
                        "Id": "1",
                        "Name": "Alpha",
                        "MagicBoxieStatus": "ready",
                        "MagicBoxieOriginalFilename": "alpha.mp4",
                    }
                ],
                "TotalRecordCount": 1,
                "StartIndex": 0,
            },
        )
        # No /stream mock registered - if the code tries to download despite
        # the movie already being local, aioresponses raises for the
        # unmatched request and the test fails.
        asyncio.run(sync.check_in())

    assert (tmp_path / "movies" / "Alpha.mp4").read_bytes() == b"already-here"


def test_check_in_registers_and_downloads_content_when_available(tmp_path):
    library = _library(tmp_path)
    sync = HomeServerSync(library, "https://magicboxie.com", "secret")

    with aioresponses() as mocked:
        mocked.post(
            "https://magicboxie.com/devices/register",
            payload={
                "items": [
                    {
                        "Id": "1",
                        "Name": "Beta",
                        "Overview": "A registered movie.",
                        "ProductionYear": 2001,
                        "RunTimeTicks": 987654321,
                        "MagicBoxieOriginalFilename": "beta.mkv",
                        "MagicBoxieStatus": "ready",
                    }
                ]
            },
        )
        mocked.get("https://magicboxie.com/Videos/1/stream?static=true", body=b"registered-video-bytes")

        asyncio.run(sync.check_in())

    assert (tmp_path / "movies" / "Beta.mkv").read_bytes() == b"registered-video-bytes"
    movie = library.movies[0]
    assert library.metadata_for(movie.id) == {
        "title": "Beta",
        "description": "A registered movie.",
        "year": 2001,
        "duration_seconds": 98,
    }


def test_check_in_does_nothing_when_login_fails(tmp_path):
    library = _library(tmp_path)
    sync = HomeServerSync(library, BASE_URL, "wrong-password")

    with aioresponses() as mocked:
        mocked.post(f"{BASE_URL}/Users/AuthenticateByName", status=401, payload={"error": "invalid password"})
        # No /Items mock registered - a login failure must stop check_in()
        # before it lists movies, or aioresponses raises for the unmatched call.
        asyncio.run(sync.check_in())

    assert library.movies == []


def test_check_in_handles_unreachable_movies_list(tmp_path):
    library = _library(tmp_path)
    sync = HomeServerSync(library, BASE_URL, "secret")

    with aioresponses() as mocked:
        mocked.post(f"{BASE_URL}/Users/AuthenticateByName", payload={"AccessToken": "tok123"})
        mocked.get(f"{BASE_URL}/Users/1/Items?IncludeItemTypes=Movie&Recursive=true", status=500)
        asyncio.run(sync.check_in())

    assert library.movies == []
