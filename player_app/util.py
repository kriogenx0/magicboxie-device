"""Small helpers shared across main.py's orchestration loops and the
background views/*_service.py workers."""
from __future__ import annotations

import asyncio


async def sleep_unless_stopped(stop_event: asyncio.Event, seconds: float) -> None:
    """Sleeps for `seconds`, waking early if `stop_event` is set. Shared by
    every "retry/refresh on an interval, but stop immediately if asked to"
    loop, so each one doesn't need its own try/except TimeoutError around
    asyncio.wait_for."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
