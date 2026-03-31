from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from src.server.domain.watchlist.models import Watchlist, WatchlistPosition
from src.server.domain.watchlist.repository import RedisWatchlistRepository


class WatchlistService:
    def __init__(self, repository: RedisWatchlistRepository):
        self.repository = repository

    async def create_watchlist(
        self,
        *,
        user_id: str,
        name: str,
        description: Optional[str] = None,
    ) -> Watchlist:
        watchlist = Watchlist(user_id=user_id, name=name, description=description)
        return await self.repository.save_watchlist(watchlist)

    async def get_watchlist(self, user_id: str, watchlist_id: str) -> Optional[Watchlist]:
        return await self.repository.get_watchlist(user_id, watchlist_id)

    async def list_watchlists(self, user_id: str) -> list[Watchlist]:
        return await self.repository.list_watchlists(user_id)

    async def add_position(
        self,
        *,
        user_id: str,
        watchlist_id: str,
        ticker: str,
        quantity: float,
        average_cost: float,
        notes: Optional[str] = None,
        tags: Optional[list[str]] = None,
        updated_at: Optional[datetime] = None,
    ) -> Watchlist:
        existing = await self.repository.get_watchlist(user_id, watchlist_id)
        if existing is None:
            raise ValueError("Watchlist not found")

        previous = next((p for p in existing.positions if p.ticker == ticker.upper()), None)
        now = updated_at or datetime.now(UTC)
        position = WatchlistPosition(
            ticker=ticker,
            quantity=quantity,
            average_cost=average_cost,
            notes=notes,
            tags=tags or [],
            added_at=previous.added_at if previous else now,
            updated_at=now,
        )
        return await self.repository.upsert_position(user_id, watchlist_id, position)

    async def remove_position(self, user_id: str, watchlist_id: str, ticker: str) -> bool:
        return await self.repository.remove_position(user_id, watchlist_id, ticker)
