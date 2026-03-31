# src/server/domain/board_catalog/refresher.py
"""Background refresher for board catalog — periodic sync from akshare to PostgreSQL."""

from __future__ import annotations

import asyncio
from typing import Optional

from src.server.utils.logger import logger

# Default refresh interval: 12 hours
_DEFAULT_INTERVAL = 12 * 3600


class BoardCatalogRefresher:
    """Periodically refreshes the board_catalog table from akshare.

    Lifecycle:
        await refresher.start()   → spawns background task
        await refresher.stop()    → cancels task cleanly
    """

    def __init__(self, service, interval: int = _DEFAULT_INTERVAL):
        self._service = service
        self._interval = interval
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(f"BoardCatalogRefresher: started (interval={self._interval}s)")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("BoardCatalogRefresher: stopped")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._service.refresh_catalog()
            except Exception as e:
                logger.warning(f"BoardCatalogRefresher: refresh failed: {e}")
            await asyncio.sleep(self._interval)
