import asyncio
from unittest.mock import AsyncMock, patch

from fakes import FakeLibrary, FakeMpv

from player_app.controllers.playback_controller import PAUSE_DIM_PERCENT, PlaybackController
from player_app.models.protocol import Command, Opcode, PlaybackStatus


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


def test_stop_shows_idle_screen():
    async def scenario():
        mpv = FakeMpv()
        controller = PlaybackController(FakeLibrary(), mpv)
        await controller.handle_command(Command(opcode=Opcode.SELECT_MOVIE, argument=0))
        await controller.handle_command(Command(opcode=Opcode.STOP))
        return mpv

    mpv = asyncio.run(scenario())
    assert mpv.shown_image_path is not None


def test_status_stays_idle_while_idle_screen_is_shown():
    """The idle-screen image is itself loaded into mpv as a "file" (see
    MpvController.show_image), which would otherwise report as "not idle" -
    refresh_status must not mistake it for a movie playing."""
    async def scenario():
        controller = PlaybackController(FakeLibrary(), FakeMpv())
        await controller.show_idle_screen()
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


def test_pause_dims_and_shows_pause_icon():
    async def scenario():
        mpv = FakeMpv()
        controller = PlaybackController(FakeLibrary(), mpv)
        await controller.handle_command(Command(opcode=Opcode.SELECT_MOVIE, argument=0))
        await controller.handle_command(Command(opcode=Opcode.PAUSE))
        return mpv

    mpv = asyncio.run(scenario())
    assert mpv.dim_percent == PAUSE_DIM_PERCENT
    assert mpv.pause_icon_shown


def test_play_clears_dim_and_pause_icon():
    async def scenario():
        mpv = FakeMpv()
        controller = PlaybackController(FakeLibrary(), mpv)
        await controller.handle_command(Command(opcode=Opcode.SELECT_MOVIE, argument=0))
        await controller.handle_command(Command(opcode=Opcode.PAUSE))
        await controller.handle_command(Command(opcode=Opcode.PLAY))
        return mpv

    mpv = asyncio.run(scenario())
    assert mpv.dim_percent == 0
    assert not mpv.pause_icon_shown


def test_stop_clears_dim_and_pause_icon_left_over_from_a_pause():
    async def scenario():
        mpv = FakeMpv()
        controller = PlaybackController(FakeLibrary(), mpv)
        await controller.handle_command(Command(opcode=Opcode.SELECT_MOVIE, argument=0))
        await controller.handle_command(Command(opcode=Opcode.PAUSE))
        await controller.handle_command(Command(opcode=Opcode.STOP))
        return mpv

    mpv = asyncio.run(scenario())
    assert mpv.dim_percent == 0
    assert not mpv.pause_icon_shown


def test_any_command_updates_last_input_at():
    async def scenario():
        controller = PlaybackController(FakeLibrary(), FakeMpv())
        controller.last_input_at = 0
        await controller.handle_command(Command(opcode=Opcode.SELECT_MOVIE, argument=0))
        return controller.last_input_at

    last_input_at = asyncio.run(scenario())
    assert last_input_at > 0


def test_shutdown_invokes_systemctl_poweroff_via_sudo():
    # Patched out so this test never actually powers off the machine
    # running it.
    async def scenario():
        controller = PlaybackController(FakeLibrary(), FakeMpv())
        with patch(
            "player_app.controllers.playback_controller.asyncio.create_subprocess_exec",
            new=AsyncMock(),
        ) as mock_exec:
            await controller.handle_command(Command(opcode=Opcode.SHUTDOWN))
            return mock_exec

    mock_exec = asyncio.run(scenario())
    mock_exec.assert_awaited_once_with("sudo", "systemctl", "poweroff")
