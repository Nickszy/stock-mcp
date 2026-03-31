from __future__ import annotations

from datetime import datetime, UTC

import pytest


class FakeRedisClient:
    def __init__(self):
        self.kv: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    async def ping(self):
        return True

    async def get(self, key: str):
        return self.kv.get(key)

    async def set(self, key: str, value: str):
        self.kv[key] = value
        return True

    async def delete(self, key: str):
        existed = key in self.kv
        self.kv.pop(key, None)
        return 1 if existed else 0

    async def sadd(self, key: str, *values: str):
        bucket = self.sets.setdefault(key, set())
        before = len(bucket)
        bucket.update(values)
        return len(bucket) - before

    async def srem(self, key: str, *values: str):
        bucket = self.sets.setdefault(key, set())
        removed = 0
        for value in values:
            if value in bucket:
                bucket.remove(value)
                removed += 1
        return removed

    async def smembers(self, key: str):
        return self.sets.get(key, set())


class FakeRedisConnection:
    def __init__(self):
        self.connected = True
        self._client = FakeRedisClient()

    async def connect(self) -> bool:
        self.connected = True
        return True

    def get_client(self):
        return self._client


@pytest.mark.asyncio
async def test_watchlist_position_normalizes_ticker_and_defaults():
    from src.server.domain.watchlist.models import WatchlistPosition

    position = WatchlistPosition(ticker="szse:000001", quantity=100, average_cost=12.34)

    assert position.ticker == "SZSE:000001"
    assert position.quantity == 100
    assert position.average_cost == 12.34
    assert position.tags == []


@pytest.mark.asyncio
async def test_repository_saves_and_lists_watchlists():
    from src.server.domain.watchlist.models import Watchlist
    from src.server.domain.watchlist.repository import RedisWatchlistRepository

    repo = RedisWatchlistRepository(FakeRedisConnection())
    watchlist = Watchlist(user_id="u1", name="核心持仓")

    await repo.save_watchlist(watchlist)

    loaded = await repo.get_watchlist("u1", watchlist.watchlist_id)
    listed = await repo.list_watchlists("u1")

    assert loaded is not None
    assert loaded.name == "核心持仓"
    assert len(listed) == 1
    assert listed[0].watchlist_id == watchlist.watchlist_id


@pytest.mark.asyncio
async def test_repository_upserts_and_removes_positions():
    from src.server.domain.watchlist.models import Watchlist, WatchlistPosition
    from src.server.domain.watchlist.repository import RedisWatchlistRepository

    repo = RedisWatchlistRepository(FakeRedisConnection())
    watchlist = Watchlist(user_id="u1", name="观察")
    await repo.save_watchlist(watchlist)

    first = WatchlistPosition(ticker="SSE:600519", quantity=10, average_cost=1500)
    updated = WatchlistPosition(ticker="SSE:600519", quantity=12, average_cost=1490)

    await repo.upsert_position("u1", watchlist.watchlist_id, first)
    await repo.upsert_position("u1", watchlist.watchlist_id, updated)

    loaded = await repo.get_watchlist("u1", watchlist.watchlist_id)
    assert loaded is not None
    assert len(loaded.positions) == 1
    assert loaded.positions[0].quantity == 12
    assert loaded.positions[0].average_cost == 1490

    removed = await repo.remove_position("u1", watchlist.watchlist_id, "sse:600519")
    reloaded = await repo.get_watchlist("u1", watchlist.watchlist_id)

    assert removed is True
    assert reloaded is not None
    assert reloaded.positions == []


@pytest.mark.asyncio
async def test_service_creates_watchlist_and_manages_positions():
    from src.server.domain.watchlist.repository import RedisWatchlistRepository
    from src.server.domain.watchlist.service import WatchlistService

    service = WatchlistService(RedisWatchlistRepository(FakeRedisConnection()))

    watchlist = await service.create_watchlist(user_id="u1", name="长期组合", description="核心仓位")
    assert watchlist.user_id == "u1"
    assert watchlist.name == "长期组合"
    assert watchlist.description == "核心仓位"

    await service.add_position(
        user_id="u1",
        watchlist_id=watchlist.watchlist_id,
        ticker="szse:000001",
        quantity=200,
        average_cost=10.5,
        notes="银行配置",
        tags=["价值", "分红"],
    )

    loaded = await service.get_watchlist("u1", watchlist.watchlist_id)
    assert loaded is not None
    assert loaded.positions[0].ticker == "SZSE:000001"
    assert loaded.positions[0].notes == "银行配置"
    assert loaded.positions[0].tags == ["价值", "分红"]


@pytest.mark.asyncio
async def test_service_updates_existing_position_timestamp():
    from src.server.domain.watchlist.models import WatchlistPosition
    from src.server.domain.watchlist.repository import RedisWatchlistRepository
    from src.server.domain.watchlist.service import WatchlistService

    service = WatchlistService(RedisWatchlistRepository(FakeRedisConnection()))
    watchlist = await service.create_watchlist(user_id="u1", name="波段")

    original_time = datetime(2026, 3, 31, 0, 0, tzinfo=UTC)
    updated_time = datetime(2026, 3, 31, 1, 0, tzinfo=UTC)

    await service.repository.upsert_position(
        "u1",
        watchlist.watchlist_id,
        WatchlistPosition(
            ticker="NASDAQ:AAPL",
            quantity=5,
            average_cost=180,
            added_at=original_time,
            updated_at=original_time,
        ),
    )

    await service.add_position(
        user_id="u1",
        watchlist_id=watchlist.watchlist_id,
        ticker="NASDAQ:AAPL",
        quantity=8,
        average_cost=175,
        updated_at=updated_time,
    )

    loaded = await service.get_watchlist("u1", watchlist.watchlist_id)
    assert loaded is not None
    assert loaded.positions[0].quantity == 8
    assert loaded.positions[0].updated_at == updated_time
    assert loaded.positions[0].added_at == original_time
