from __future__ import annotations

import asyncio
import logging

from yahoo_shopping_mcp.memory.repository import PreferenceGraphRepository

logger = logging.getLogger(__name__)


async def run_cleanup_loop(
    repository: PreferenceGraphRepository,
    *,
    interval_seconds: int,
    stop: asyncio.Event,
) -> None:
    """Clean short-lived memory records without affecting product search availability."""

    while not stop.is_set():
        try:
            await repository.cleanup_expired()
        except Exception:
            logger.warning("Agentic Memory cleanup failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
