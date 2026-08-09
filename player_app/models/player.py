"""Drives mpv over its JSON IPC socket. See https://mpv.io/manual/master/#json-ipc."""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# How long to wait for mpv to create its IPC socket before giving up. Was
# 5s, which turned out too tight under real-world load: DRM/KMS
# initialization on a Pi Zero W can legitimately take upwards of 15s (e.g.
# right after a reboot or a burst of other activity, like a systemd restart
# storm - a slow startup that trips this timeout kills the whole daemon,
# which then immediately retries and adds more load, making the next
# startup even slower). Confirmed via a manual run that mpv itself starts
# cleanly - it just needed more time, not a different invocation.
MPV_STARTUP_TIMEOUT_SECONDS = 30


class MpvController:
    def __init__(self, socket_path: str = "/tmp/magicboxie-mpv.sock", extra_args: Optional[List[str]] = None):
        self._socket_path = socket_path
        self._extra_args = extra_args or []
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = itertools.count(1)
        self._pending: Dict[int, "asyncio.Future"] = {}
        self._listen_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        socket_path = Path(self._socket_path)
        if socket_path.exists():
            socket_path.unlink()

        self._process = await asyncio.create_subprocess_exec(
            "mpv",
            "--idle=yes",
            "--force-window=no",
            "--no-terminal",
            f"--input-ipc-server={self._socket_path}",
            *self._extra_args,
            stdout=asyncio.subprocess.DEVNULL,
            # Piped (not DEVNULL) and drained by _log_stderr for the life of
            # the process - both so a startup failure (e.g. mpv can't open
            # its DRM/KMS output) is visible in `journalctl` instead of
            # silently discarded, and so the pipe never fills up and blocks
            # mpv if it warns about anything later during normal playback.
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.create_task(self._log_stderr())

        for _ in range(MPV_STARTUP_TIMEOUT_SECONDS * 10):
            if socket_path.exists():
                break
            if self._process.returncode is not None:
                raise RuntimeError(f"mpv exited immediately with code {self._process.returncode} - see logs above for its stderr")
            await asyncio.sleep(0.1)
        else:
            self._process.kill()
            raise RuntimeError("mpv did not create its IPC socket in time - see logs above for its stderr")

        self._reader, self._writer = await asyncio.open_unix_connection(self._socket_path)
        self._listen_task = asyncio.create_task(self._listen())

    async def _log_stderr(self) -> None:
        assert self._process is not None and self._process.stderr is not None
        while True:
            line = await self._process.stderr.readline()
            if not line:
                break
            logger.warning("mpv: %s", line.decode(errors="replace").rstrip())

    async def stop_process(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
        if self._stderr_task:
            self._stderr_task.cancel()
        if self._writer:
            self._writer.close()
        if self._process and self._process.returncode is None:
            self._process.terminate()
            await self._process.wait()

    async def _listen(self) -> None:
        assert self._reader is not None
        while True:
            line = await self._reader.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = message.get("request_id")
            if request_id is not None and request_id in self._pending:
                self._pending.pop(request_id).set_result(message)

    async def _command(self, *args) -> dict:
        assert self._writer is not None
        request_id = next(self._request_id)
        future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future
        payload = json.dumps({"command": list(args), "request_id": request_id}) + "\n"
        self._writer.write(payload.encode("utf-8"))
        await self._writer.drain()
        try:
            return await asyncio.wait_for(future, timeout=5)
        finally:
            self._pending.pop(request_id, None)

    async def load(self, path: Path) -> None:
        # pause=no is passed as part of loadfile's own options rather than as
        # a separate play() call afterward: loadfile acknowledges near-
        # instantly, but actually opening/probing the file happens
        # asynchronously and can take real time for a large file on this
        # hardware (same reason PROBE_TIMEOUT_SECONDS in library.py had to
        # grow) - a separate pause=no sent right after often landed before
        # that finished, and got silently reset to paused once mpv's own
        # load transition completed. Setting it as a loadfile option applies
        # atomically as part of the same load, so there's no race to lose.
        await self._command("loadfile", str(path), "replace", "pause=no")

    async def show_image(self, path: Path) -> None:
        """Like load(), but for a still image meant to sit on screen
        indefinitely (the idle/home screen) rather than play through and
        stop - mpv's default image-display-duration is finite, which would
        otherwise drop it back to idle almost immediately."""
        await self._command("loadfile", str(path), "replace", "image-display-duration=inf")

    async def play(self) -> None:
        await self._command("set_property", "pause", False)

    async def pause(self) -> None:
        await self._command("set_property", "pause", True)

    async def stop(self) -> None:
        await self._command("stop")

    async def seek(self, position_seconds: int) -> None:
        await self._command("seek", position_seconds, "absolute")

    async def get_position(self) -> int:
        try:
            response = await self._command("get_property", "time-pos")
            return int(response.get("data") or 0)
        except (asyncio.TimeoutError, TypeError):
            return 0

    async def get_paused(self) -> bool:
        try:
            response = await self._command("get_property", "pause")
            return bool(response.get("data"))
        except asyncio.TimeoutError:
            return True

    async def get_idle(self) -> bool:
        try:
            response = await self._command("get_property", "idle-active")
            return bool(response.get("data"))
        except asyncio.TimeoutError:
            return True
