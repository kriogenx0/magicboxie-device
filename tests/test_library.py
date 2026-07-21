from magicbox_device.models.library import MovieLibrary


def test_save_uploaded_thumbnail_overwrites_cache(tmp_path):
    movies_dir = tmp_path / "movies"
    movies_dir.mkdir()
    thumbnail_dir = tmp_path / "thumbnails"
    library = MovieLibrary(movies_dir, thumbnail_dir=thumbnail_dir)
    library.scan()

    library.save_uploaded_thumbnail(0, b"official-poster-bytes")

    path = library.thumbnail_path_for(0)
    assert path is not None
    assert path.read_bytes() == b"official-poster-bytes"


def test_save_uploaded_thumbnail_replaces_existing_file(tmp_path):
    movies_dir = tmp_path / "movies"
    movies_dir.mkdir()
    thumbnail_dir = tmp_path / "thumbnails"
    library = MovieLibrary(movies_dir, thumbnail_dir=thumbnail_dir)
    library.scan()

    library.save_uploaded_thumbnail(0, b"first-version")
    library.save_uploaded_thumbnail(0, b"second-version")

    assert library.thumbnail_path_for(0).read_bytes() == b"second-version"
