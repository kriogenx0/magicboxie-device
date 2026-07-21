import asyncio

from fakes import FakeLibrary, FakeMpv

from magicbox_device.controllers.playback_controller import PlaybackController
from magicbox_device.models.protocol import Command, Opcode, PlaybackStatus


def test_select_and_play_updates_status():
    async def scenario():
        controller = PlaybackController(FakeLibrary(), FakeMpv())
        await controller.handle_command(Command(opcode=Opcode.SELECT_MOVIE, argument=1))
        return await controller.refresh_status()

    state = asyncio.run(scenario())
    assert state.status == PlaybackStatus.PLAYING
    assert state.movie_id == 1


def test_stop_clears_movie_id():
    async def scenario():
        controller = PlaybackController(FakeLibrary(), FakeMpv())
        await controller.handle_command(Command(opcode=Opcode.SELECT_MOVIE, argument=0))
        await controller.handle_command(Command(opcode=Opcode.STOP))
        return await controller.refresh_status()

    state = asyncio.run(scenario())
    assert state.status == PlaybackStatus.STOPPED
    assert state.movie_id is None


def test_pause_reflected_in_status():
    async def scenario():
        controller = PlaybackController(FakeLibrary(), FakeMpv())
        await controller.handle_command(Command(opcode=Opcode.SELECT_MOVIE, argument=0))
        await controller.handle_command(Command(opcode=Opcode.PAUSE))
        return await controller.refresh_status()

    state = asyncio.run(scenario())
    assert state.status == PlaybackStatus.PAUSED


def test_seek_updates_position():
    async def scenario():
        controller = PlaybackController(FakeLibrary(), FakeMpv())
        await controller.handle_command(Command(opcode=Opcode.SELECT_MOVIE, argument=0))
        await controller.handle_command(Command(opcode=Opcode.SEEK, argument=42))
        return await controller.refresh_status()

    state = asyncio.run(scenario())
    assert state.position_seconds == 42
