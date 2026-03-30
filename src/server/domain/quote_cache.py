# src/server/domain/quote_cache.py
"""Unified quote cache with single-flight (request coalescing) protection.

Sits at the MarketGateway level — cache key is canonical ticker
(``EXCHANGE:SYMBOL``),, independent of which adapter eventually fetches.

Flow:
    1. Check Redis (``quote:{exchange}:{symbol}``)
    2. Cache miss -> acquire per-ticker asyncio.Lock
    3. Double-check cache (another coroutine may have filled it)
    4. Still miss -> call fetch_fn ( adapter/router )
    5. Store in Redis with market-aware TTL
    6. Release lock + cleanup inflight entry

Observable via ``.metrics`` property ( hits / misses / coalesced / errors).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Awaitable, Dict, Optional

from src.server.infrastructure.cache.redis_cache import AsyncRedisCache, market_aware_ttl
from src.server.utils.logger import logger

# Market-specific TTL defaults (seconds)
_MARKET_TTL: Dict[str, int] = {
    "SSE": 60,
    "SZSE": 60,
    "BSE": 60,
    "NASDAQ": 15,
    "NYSE": 15,
    "AMEX": 15,
    "HKEX": 30,
    "CRYPTO": 10,
}

# Prefix for Redis keys
_KEY_PREFIX = "quote"


@dataclass
class QuoteCacheMetrics:
    """Counters for observability — safe in single-process async (no concurrent +=)."""

    hits: int = 0
    misses: int = 0
    coalesced: int = 0  # requests that waited on an in-flight fetch
    errors: int = 0

    def snapshot(self) -> Dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "coalesced": self.coalesced,
            "errors": self.errors,
        }


class QuoteCache:
    """Gateway-level quote cache with single-flight protection."""

    def __init__(self, cache: AsyncRedisCache):
        self._cache = cache
        self._inflight: Dict[str, asyncio.Lock] = {}
        self.metrics = QuoteCacheMetrics()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_or_fetch(
        self,
        ticker: str,
        fetch_fn: Callable[[], Awaitable[Optional[Any]]],
    ) -> Optional[Any]:
        """Return cached quote or fetch + cache.

        ``fetch_fn`` is called only when Redis has no entry for *ticker*.
        Concurrent callers for the same ticker coalesce — they wait on the
        first caller's fetch rather than triggering N parallel API calls.
        """
        cached = await self._cache_get(ticker)
        if cached is not None:
            self.metrics.hits += 1
            return cached

        # Cache miss — acquire per-ticker lock
        lock = self._get_lock(ticker)
        if lock.locked():
            self.metrics.coalesced += 1

        try:
            async with lock:
                # Double-check after acquiring lock
                cached = await self._cache_get(ticker)
                if cached is not None:
                    self.metrics.hits += 1
                    return cached

                self.metrics.misses += 1
                try:
                    result = await fetch_fn()
                except Exception:
                    self.metrics.errors += 1
                    raise

                if result is not None:
                    await self._cache_set(ticker, result)

                return result
        finally:
            self._cleanup_lock(ticker)

    async def invalidate(self, ticker: str) -> bool:
        """Remove cached quote for *ticker*."""
        key = self._make_key(ticker)
        return await self._cache.delete(key)

    # ------------------------------------------------------------------
    # Snapshot (EOD) support
    # ------------------------------------------------------------------

    async def store_snapshot(
        self,
        ticker: str,
        data: Any,
        ttl: int = 86400,
    ) -> bool:
        """Store a daily snapshot with longer TTL (default 24h)."""
        key = f"{_KEY_PREFIX}:snap:{ticker}"
        return await self._cache.set(key, data, ttl=ttl)

    async def get_snapshot(self, ticker: str) -> Optional[Any]:
        """Retrieve a stored daily snapshot."""
        key = f"{_KEY_PREFIX}:snap:{ticker}"
        return await self._cache.get(key)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get_lock(self, ticker: str) -> asyncio.Lock:
        """Get or create a per-ticker lock.

        Safe in single-threaded async (no await between check and dict insert).
        """
        if ticker not in self._inflight:
            self._inflight[ticker] = asyncio.Lock()
        return self._inflight[ticker]

    def _make_key(self, ticker: str) -> str:
        return f"{_KEY_PREFIX}:{ticker}"

    def _ttl_for_ticker(self, ticker: str) -> int:
        """Market-aware TTL based on exchange prefix of ticker."""
        exchange = ticker.split(":")[0] if ":" in ticker else ""
        base_ttl = _MARKET_TTL.get(exchange, 60)

        # A-share: use existing market_aware_ttl logic
        if exchange in ("SSE", "SZSE", "BSE"):
            return market_aware_ttl(trading_ttl=base_ttl)

        return base_ttl

    async def _cache_get(self, ticker: str) -> Optional[Any]:
        key = self._make_key(ticker)
        try:
            return await self._cache.get(key)
        except Exception:
            logger.warning("quote_cache: Redis GET failed", ticker=ticker, exc_info=True)
            return None

    async def _cache_set(self, ticker: str, data: Any) -> None:
        key = self._make_key(ticker)
        ttl = self._ttl_for_ticker(ticker)
        try:
            await self._cache.set(key, data, ttl=ttl)
        except Exception:
            logger.warning("quote_cache: Redis SET failed", ticker=ticker, exc_info=True)

    def _cleanup_lock(self, ticker: str) -> None:
        """Remove lock entry to prevent unbounded growth."""
        self._inflight.pop(ticker, None)
