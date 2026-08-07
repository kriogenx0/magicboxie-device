from PIL import Image

from player_app.models.idle_screen import render_idle_screen

from fakes import FakeLibrary


class _EmptyLibrary:
    movies = []

    def thumbnail_path_for(self, movie_id):
        return None


def test_render_idle_screen_creates_an_image(tmp_path):
    output_path = tmp_path / "idle.png"

    result_path = render_idle_screen(FakeLibrary(), output_path=output_path)

    assert result_path == output_path
    assert output_path.exists()
    with Image.open(output_path) as image:
        image.verify()


def test_render_idle_screen_with_no_movies_does_not_crash(tmp_path):
    output_path = tmp_path / "idle.png"

    render_idle_screen(_EmptyLibrary(), output_path=output_path)

    assert output_path.exists()


def test_render_idle_screen_composites_real_thumbnails(tmp_path):
    thumbnail_path = tmp_path / "0.jpg"
    # A solid, distinctly-colored square so its presence in the composited
    # grid is unambiguous - not a coincidental match with the background.
    Image.new("RGB", (100, 100), (255, 0, 0)).save(thumbnail_path)
    library = FakeLibrary(thumbnail_paths={0: thumbnail_path})
    output_path = tmp_path / "idle.png"

    render_idle_screen(library, output_path=output_path)

    # JPEG re-encoding is lossy, so the pasted thumbnail won't survive as an
    # exact (255, 0, 0) - just confirm a clearly red pixel made it in.
    with Image.open(output_path) as image:
        colors = image.convert("RGB").getcolors(maxcolors=1_000_000)
    assert any(r > 200 and g < 60 and b < 60 for _count, (r, g, b) in colors)
