from player_app.models import protocol
from player_app.models.protocol import (
    Command,
    Movie,
    Opcode,
    PlaybackState,
    PlaybackStatus,
)


def test_decode_command_no_argument():
    cmd = protocol.decode_command(bytes([Opcode.PLAY]))
    assert cmd == Command(opcode=Opcode.PLAY, argument=None)


def test_decode_command_with_argument():
    payload = bytes([Opcode.SEEK]) + (90).to_bytes(4, "little")
    cmd = protocol.decode_command(payload)
    assert cmd == Command(opcode=Opcode.SEEK, argument=90)


def test_decode_select_movie_argument_round_trips_large_ids():
    payload = bytes([Opcode.SELECT_MOVIE]) + (70000).to_bytes(4, "little")
    cmd = protocol.decode_command(payload)
    assert cmd.argument == 70000


def test_status_round_trip_idle():
    state = PlaybackState.idle()
    encoded = protocol.encode_status(state)
    assert len(encoded) == 7
    assert protocol.decode_status(encoded) == state


def test_status_round_trip_playing():
    state = PlaybackState(status=PlaybackStatus.PLAYING, movie_id=3, position_seconds=125)
    encoded = protocol.encode_status(state)
    assert protocol.decode_status(encoded) == state


def test_transcode_status_round_trip_none():
    encoded = protocol.encode_transcode_status(None)
    assert len(encoded) == 2
    assert protocol.decode_transcode_status(encoded) is None


def test_transcode_status_round_trip_movie_id():
    encoded = protocol.encode_transcode_status(7)
    assert protocol.decode_transcode_status(encoded) == 7


def test_api_version_is_a_single_byte_matching_the_constant():
    encoded = protocol.encode_api_version()
    assert encoded == bytes([protocol.API_VERSION])


def test_library_round_trip():
    movies = [
        Movie(id=0, title="Star Wars", duration_seconds=7620),
        Movie(id=1, title="The Room", duration_seconds=5460),
    ]
    encoded = protocol.encode_library(movies)
    assert protocol.decode_library(encoded) == movies


def test_library_truncates_to_fit_max_bytes():
    movies = [Movie(id=i, title=f"Movie {i}" * 5, duration_seconds=100) for i in range(50)]
    encoded = protocol.encode_library(movies, max_bytes=200)
    assert len(encoded) <= 200
    decoded = protocol.decode_library(encoded)
    assert decoded == movies[: len(decoded)]


def test_library_decode_ignores_malformed_lines():
    decoded = protocol.decode_library(b"0|Ok|100\nnot-a-valid-line\n1|Also Ok|200")
    assert decoded == [
        Movie(id=0, title="Ok", duration_seconds=100),
        Movie(id=1, title="Also Ok", duration_seconds=200),
    ]
