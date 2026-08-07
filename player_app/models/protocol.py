"""Wire format shared with the MagicBoxie iOS app's MediaControlProtocol.swift.

Any change here must be mirrored there, and vice versa - the two sides only
agree on how to interpret bytes because both encode/decode identically.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional

SERVICE_UUID = "3e2c1a00-3b42-4b7e-9c3e-000000000001"
COMMAND_CHARACTERISTIC_UUID = "3e2c1a00-3b42-4b7e-9c3e-000000000002"
STATUS_CHARACTERISTIC_UUID = "3e2c1a00-3b42-4b7e-9c3e-000000000003"
LIBRARY_CHARACTERISTIC_UUID = "3e2c1a00-3b42-4b7e-9c3e-000000000004"
# Read-only: the device's own "http://host:port" base URL, so a BLE-connected
# app can discover it and offer to switch to WiFi for the bulk-data transports
# (thumbnails, library, status polling) that BLE's tiny ATT payloads can't carry.
NETWORK_INFO_CHARACTERISTIC_UUID = "3e2c1a00-3b42-4b7e-9c3e-000000000005"

# iOS long-reads cap out at 512 bytes (BLE ATT maximum attribute value length).
MAX_CHARACTERISTIC_BYTES = 512

_NO_MOVIE_SENTINEL = 0xFFFF


class Opcode(IntEnum):
    PLAY = 0x01
    PAUSE = 0x02
    STOP = 0x03
    SELECT_MOVIE = 0x04
    SEEK = 0x05


class PlaybackStatus(IntEnum):
    STOPPED = 0x00
    PLAYING = 0x01
    PAUSED = 0x02


@dataclass
class Command:
    opcode: Opcode
    argument: Optional[int] = None


@dataclass
class Movie:
    id: int
    title: str
    duration_seconds: int


@dataclass
class PlaybackState:
    status: PlaybackStatus
    movie_id: Optional[int]
    position_seconds: int

    @classmethod
    def idle(cls) -> "PlaybackState":
        return cls(status=PlaybackStatus.STOPPED, movie_id=None, position_seconds=0)


def decode_command(data: bytes) -> Command:
    """1-byte opcode, optionally followed by a little-endian uint32 argument."""
    if not data:
        raise ValueError("empty command payload")
    opcode = Opcode(data[0])
    if len(data) >= 5:
        argument = int.from_bytes(data[1:5], byteorder="little", signed=False)
        return Command(opcode=opcode, argument=argument)
    return Command(opcode=opcode)


def encode_status(state: PlaybackState) -> bytes:
    """1 byte status + 2 bytes movie id (0xFFFF = none) + 4 bytes position, all little-endian."""
    movie_id = _NO_MOVIE_SENTINEL if state.movie_id is None else state.movie_id
    return bytes(
        [state.status]
    ) + movie_id.to_bytes(2, "little") + state.position_seconds.to_bytes(4, "little")


def decode_status(data: bytes) -> PlaybackState:
    if len(data) < 7:
        raise ValueError("status payload too short")
    status = PlaybackStatus(data[0])
    movie_id_raw = int.from_bytes(data[1:3], "little")
    position = int.from_bytes(data[3:7], "little")
    movie_id = None if movie_id_raw == _NO_MOVIE_SENTINEL else movie_id_raw
    return PlaybackState(status=status, movie_id=movie_id, position_seconds=position)


def encode_library(movies: List[Movie], max_bytes: int = MAX_CHARACTERISTIC_BYTES) -> bytes:
    """UTF-8 text, one movie per line: "id|title|durationSeconds".

    Movies are included in order until adding the next one would exceed
    max_bytes; anything past that point is silently dropped rather than
    corrupting the payload for movies that already fit.
    """
    lines: List[str] = []
    total = 0
    for movie in movies:
        line = f"{movie.id}|{movie.title}|{movie.duration_seconds}"
        encoded_len = len(line.encode("utf-8")) + 1  # +1 for the newline separator
        if total + encoded_len > max_bytes:
            break
        lines.append(line)
        total += encoded_len
    return "\n".join(lines).encode("utf-8")


def decode_library(data: bytes) -> List[Movie]:
    text = data.decode("utf-8")
    movies = []
    for line in text.split("\n"):
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        try:
            movies.append(Movie(id=int(parts[0]), title=parts[1], duration_seconds=int(parts[2])))
        except ValueError:
            continue
    return movies
