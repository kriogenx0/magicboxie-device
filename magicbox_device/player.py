"""Drives mpv over its JSON IPC socket. See https://mpv.io/manual/master/#json-ipc."""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MpvController:
    def __init__(self, socket_path: str = "/tmp/magicbox-mpv.sock", extra_args: Optional[List[str]] = None):
        self._socket_path = socket_path
        self._extra_args = extra_args or []
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = itertools.count(1)
        self._pending: Dict[int, "asyncio.Future"] = {}
        self._listen_task: Optional[asyncio.Task] = None

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
            stderr=asyncio.subprocess.DEVNULL,
        )

        for _ in range(50):  # wait up to ~5s for mpv to create the socket
            if socket_path.exists():
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("mpv did not create its IPC socket in time")

        self._reader, self._writer = await asyncio.open_unix_connection(self._socket_path)
        self._listen_task = asyncio.create_task(self._listen())

    async def stop_process(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
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
        await self._command("loadfile", str(path), "replace")

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
