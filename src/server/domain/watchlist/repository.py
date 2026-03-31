from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Optional

from src.server.domain.watchlist.models import Watchlist, WatchlistPosition
from src.server.utils.logger import logger


class RedisWatchlistRepository:
    def __init__(self, redis_conn):
        self._redis_conn = redis_conn

    async def _get_client(self):
        if not self._redis_conn.connected:
            ok = await self._redis_conn.connect()
            if not ok:
                raise RuntimeError("Redis not available")
        client = self._redis_conn.get_client()
        if client is None:
            raise RuntimeError("Redis client not available")
        return client

    def _watchlist_key(self, user_id: str, watchlist_id: str) -> str:
        return f"watchlist:{user_id}:{watchlist_id}"

    def _watchlists_key(self, user_id: str) -> str:
        return f"watchlists:{user_id}"

    async def save_watchlist(self, watchlist: Watchlist) -> Watchlist:
        client = await self._get_client()
        payload = watchlist.model_dump(mode="json")
        await client.set(
            self._watchlist_key(watchlist.user_id, watchlist.watchlist_id),
            json.dumps(payload),
        )
        await client.sadd(self._watchlists_key(watchlist.user_id), watchlist.watchlist_id)
        return watchlist

    async def get_watchlist(self, user_id: str, watchlist_id: str) -> Optional[Watchlist]:
        client = await self._get_client()
        raw = await client.get(self._watchlist_key(user_id, watchlist_id))
        if not raw:
            return None
        return Watchlist.model_validate(json.loads(raw))

    async def list_watchlists(self, user_id: str) -> list[Watchlist]:
        client = await self._get_client()
        watchlist_ids = sorted(await client.smembers(self._watchlists_key(user_id)))
        items: list[Watchlist] = []
        for watchlist_id in watchlist_ids:
            watchlist = await self.get_watchlist(user_id, watchlist_id)
            if watchlist is not None:
                items.append(watchlist)
        return items

    async def upsert_position(
        self,
        user_id: str,
        watchlist_id: str,
        position: WatchlistPosition,
    ) -> Watchlist:
        watchlist = await self.get_watchlist(user_id, watchlist_id)
        if watchlist is None:
            raise ValueError("Watchlist not found")

        replaced = False
        positions: list[WatchlistPosition] = []
        for existing in watchlist.positions:
            if existing.ticker == position.ticker:
                positions.append(position)
                replaced = True
            else:
                positions.append(existing)
        if not replaced:
            positions.append(position)

        watchlist.positions = positions
        watchlist.updated_at = datetime.now(UTC)
        await self.save_watchlist(watchlist)
        return watchlist

    async def remove_position(self, user_id: str, watchlist_id: str, ticker: str) -> bool:
        watchlist = await self.get_watchlist(user_id, watchlist_id)
        if watchlist is None:
            return False

        normalized = ticker.upper()
        remaining = [p for p in watchlist.positions if p.ticker != normalized]
        if len(remaining) == len(watchlist.positions):
            return False

        watchlist.positions = remaining
        watchlist.updated_at = datetime.now(UTC)
        await self.save_watchlist(watchlist)
        return True
