from player_app.models.library import MovieLibrary


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


def test_save_metadata_merges_with_existing_fields(tmp_path):
    movies_dir = tmp_path / "movies"
    movies_dir.mkdir()
    library = MovieLibrary(movies_dir, thumbnail_dir=tmp_path / "thumbnails")
    library.scan()

    library.save_metadata(0, title="Alpha", year=1999)
    library.save_metadata(0, description="A movie.")

    assert library.metadata_for(0) == {"title": "Alpha", "year": 1999, "description": "A movie."}


def test_save_metadata_persists_across_rescan(tmp_path):
    movies_dir = tmp_path / "movies"
    movies_dir.mkdir()
    (movies_dir / "a.mp4").write_bytes(b"fake-video-bytes")
    thumbnail_dir = tmp_path / "thumbnails"
    library = MovieLibrary(movies_dir, thumbnail_dir=thumbnail_dir)
    library.scan()
    movie_id = library.movies[0].id
    library.save_metadata(movie_id, title="Alpha")

    reloaded = MovieLibrary(movies_dir, thumbnail_dir=thumbnail_dir)
    reloaded.scan()

    assert reloaded.metadata_for(movie_id) == {"title": "Alpha"}


def test_movie_id_is_stable_across_rescans_when_files_are_added(tmp_path):
    """The id scheme must be filename-derived, not positional - otherwise
    adding a file that sorts earlier shifts every later movie's id,
    silently reattaching its thumbnail/metadata/selection to whatever
    movie now lands on that id instead."""
    movies_dir = tmp_path / "movies"
    movies_dir.mkdir()
    (movies_dir / "z_movie.mp4").write_bytes(b"fake-video-bytes")
    library = MovieLibrary(movies_dir, thumbnail_dir=tmp_path / "thumbnails")
    library.scan()
    original_id = library.movies[0].id

    (movies_dir / "a_movie.mp4").write_bytes(b"fake-video-bytes")
    library.scan()

    rescanned = next(m for m in library.movies if m.title == "z_movie")
    assert rescanned.id == original_id
