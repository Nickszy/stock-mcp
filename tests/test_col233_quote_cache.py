# tests/test_col233_quote_cache.py
"""Tests for COL-233: real-time quote cache with single-flight protection.

Covers:
1. QuoteCache: cache hit / miss / coalescing
2. QuoteCache: concurrent request coalescing (single-flight)
3. QuoteCache: market-aware TTL
4. QuoteCache: metrics observability
5. QuoteCache: snapshot (EOD) support
6. MarketGateway integration: quote_cache parameter accepted
7. MarketGateway.get_multiple_prices: ticker deduplication
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


# ---------------------------------------------------------------------------
# QuoteCache unit tests
# ---------------------------------------------------------------------------


class TestQuoteCacheHitMiss:
    """Basic cache-aside behavior."""

    @pytest.mark.asyncio
    async def test_cache_miss_calls_fetch(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock(return_value=True)
        mock_cache.delete = AsyncMock(return_value=True)

        qc = QuoteCache(mock_cache)

        fetch_fn = AsyncMock(return_value={"ticker": "SSE:600519", "price": 1800.0})
        result = await qc.get_or_fetch("SSE:600519", fetch_fn)

        assert result == {"ticker": "SSE:600519", "price": 1800.0}
        fetch_fn.assert_awaited_once()
        mock_cache.set.assert_awaited_once()
        assert qc.metrics.misses == 1
        assert qc.metrics.hits == 0

    @pytest.mark.asyncio
    async def test_cache_hit_skips_fetch(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        cached_data = {"ticker": "NASDAQ:AAPL", "price": 195.0}
        mock_cache.get = AsyncMock(return_value=cached_data)
        mock_cache.set = AsyncMock(return_value=True)

        qc = QuoteCache(mock_cache)

        fetch_fn = AsyncMock(return_value={"price": 999})
        result = await qc.get_or_fetch("NASDAQ:AAPL", fetch_fn)

        assert result == cached_data
        fetch_fn.assert_not_awaited()
        assert qc.metrics.hits == 1
        assert qc.metrics.misses == 0

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock(return_value=True)

        qc = QuoteCache(mock_cache)

        fetch_fn = AsyncMock(return_value=None)
        result = await qc.get_or_fetch("UNKNOWN:X", fetch_fn)

        assert result is None
        # None results should NOT be cached (avoids poisoning)
        mock_cache.set.assert_not_awaited()


class TestQuoteCacheSingleFlight:
    """Concurrent requests for the same ticker should coalesce."""

    @pytest.mark.asyncio
    async def test_single_flight_coalesces_concurrent_requests(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        # Simulate real cache: initially empty, then populated after set
        _store = {}

        async def mock_get(key):
            return _store.get(key)

        async def mock_set(key, value, ttl=None):
            _store[key] = value

        mock_cache.get = mock_get
        mock_cache.set = mock_set
        mock_cache.delete = AsyncMock(return_value=True)

        qc = QuoteCache(mock_cache)

        fetch_count = 0

        async def slow_fetch():
            nonlocal fetch_count
            fetch_count += 1
            await asyncio.sleep(0.1)  # simulate slow API
            return {"ticker": "SSE:600519", "price": 1800.0}

        # Launch 5 concurrent requests for the same ticker
        results = await asyncio.gather(
            *[qc.get_or_fetch("SSE:600519", slow_fetch) for _ in range(5)]
        )

        # Only 1 fetch should have been made (single-flight)
        assert fetch_count == 1, f"Expected 1 fetch, got {fetch_count}"
        assert qc.metrics.coalesced >= 1, "At least 1 request should have been coalesced"
        # All results should be the same
        assert all(r == {"ticker": "SSE:600519", "price": 1800.0} for r in results)

    @pytest.mark.asyncio
    async def test_different_tickers_fetch_independently(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock(return_value=True)

        qc = QuoteCache(mock_cache)

        fetch_calls = []

        async def fetch_factory(ticker):
            async def _fetch():
                fetch_calls.append(ticker)
                return {"ticker": ticker, "price": 100}
            return _fetch

        await asyncio.gather(
            qc.get_or_fetch("SSE:600519", await fetch_factory("SSE:600519")),
            qc.get_or_fetch("NASDAQ:AAPL", await fetch_factory("NASDAQ:AAPL")),
        )

        # Both tickers should have been fetched
        assert len(fetch_calls) == 2
        assert "SSE:600519" in fetch_calls
        assert "NASDAQ:AAPL" in fetch_calls


class TestQuoteCacheMetrics:
    """Metrics observability."""

    @pytest.mark.asyncio
    async def test_metrics_snapshot(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value={"price": 100})
        qc = QuoteCache(mock_cache)

        await qc.get_or_fetch("SSE:600519", AsyncMock())

        snap = qc.metrics.snapshot()
        assert "hits" in snap
        assert "misses" in snap
        assert "coalesced" in snap
        assert "errors" in snap
        assert snap["hits"] == 1

    @pytest.mark.asyncio
    async def test_error_metric_on_fetch_failure(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        mock_cache.get = AsyncMock(return_value=None)
        mock_cache.set = AsyncMock(return_value=True)

        qc = QuoteCache(mock_cache)

        async def failing_fetch():
            raise RuntimeError("API timeout")

        with pytest.raises(RuntimeError, match="API timeout"):
            await qc.get_or_fetch("NASDAQ:AAPL", failing_fetch)

        assert qc.metrics.errors == 1
        assert qc.metrics.misses == 1


class TestQuoteCacheTTL:
    """Market-aware TTL calculation."""

    def test_ttl_a_share_uses_market_aware(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        qc = QuoteCache(mock_cache)

        # SSE ticker should use market_aware_ttl
        ttl = qc._ttl_for_ticker("SSE:600519")
        assert isinstance(ttl, int)
        assert ttl > 0

    def test_ttl_us_stock_returns_base(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        qc = QuoteCache(mock_cache)

        ttl = qc._ttl_for_ticker("NASDAQ:AAPL")
        assert ttl == 15  # configured in _MARKET_TTL

    def test_ttl_crypto_returns_short(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        qc = QuoteCache(mock_cache)

        ttl = qc._ttl_for_ticker("CRYPTO:BTC")
        assert ttl == 10

    def test_ttl_unknown_exchange_defaults(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        qc = QuoteCache(mock_cache)

        ttl = qc._ttl_for_ticker("UNKNOWN:TICK")
        assert ttl == 60  # default fallback


class TestQuoteCacheSnapshot:
    """EOD snapshot support."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_snapshot(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        mock_cache.set = AsyncMock(return_value=True)
        mock_cache.get = AsyncMock(return_value={"price": 1850.0})

        qc = QuoteCache(mock_cache)

        await qc.store_snapshot("SSE:600519", {"price": 1850.0})
        mock_cache.set.assert_awaited_once()

        snap = await qc.get_snapshot("SSE:600519")  # Same ticker as store
        mock_cache.get.assert_awaited()
        assert snap == {"price": 1850.0}


class TestQuoteCacheInvalidate:
    """Cache invalidation."""

    @pytest.mark.asyncio
    async def test_invalidate_calls_delete(self):
        from src.server.domain.quote_cache import QuoteCache

        mock_cache = MagicMock()
        mock_cache.delete = AsyncMock(return_value=True)

        qc = QuoteCache(mock_cache)
        result = await qc.invalidate("SSE:600519")

        assert result is True
        mock_cache.delete.assert_awaited_once_with("quote:SSE:600519")


# ---------------------------------------------------------------------------
# MarketGateway integration tests
# ---------------------------------------------------------------------------


class TestMarketGatewayQuoteCache:
    """Verify MarketGateway accepts quote_cache parameter."""

    def test_gateway_accepts_quote_cache(self):
        from src.server.domain.market_gateway import MarketGateway

        mock_resolver = MagicMock()
        mock_quote_cache = MagicMock()

        gw = MarketGateway(
            symbol_resolver=mock_resolver,
            quote_cache=mock_quote_cache,
        )
        assert gw._quote_cache is mock_quote_cache

    def test_gateway_default_no_quote_cache(self):
        from src.server.domain.market_gateway import MarketGateway

        mock_resolver = MagicMock()

        gw = MarketGateway(symbol_resolver=mock_resolver)
        assert gw._quote_cache is None


class TestGetMultiplePricesDedup:
    """Verify get_multiple_prices deduplicates resolved tickers."""

    @pytest.mark.asyncio
    async def test_duplicate_tickers_fetched_once(self):
        """When multiple raw_symbols resolve to same ticker, only fetch once."""
        from src.server.domain.market_gateway import MarketGateway

        mock_resolver = MagicMock()

        # Mock ResolutionResult
        from src.server.domain.symbols.types import ResolutionStatus

        resolved_a = MagicMock()
        resolved_a.status = ResolutionStatus.RESOLVED
        resolved_a.normalized = "SSE:600519"

        resolved_b = MagicMock()
        resolved_b.status = ResolutionStatus.RESOLVED
        resolved_b.normalized = "SSE:600519"  # Same as a

        mock_resolver.resolve = AsyncMock(side_effect=[resolved_a, resolved_b])

        gw = MarketGateway(symbol_resolver=mock_resolver)

        # Mock _dispatch_ticker to count calls
        dispatch_calls = []

        async def mock_dispatch(method, ticker, **kwargs):
            dispatch_calls.append((method, ticker))
            from unittest.mock import MagicMock
            mock_price = MagicMock()
            mock_price.to_dict.return_value = {"ticker": ticker, "price": 1800}
            return mock_price

        gw._dispatch_ticker = mock_dispatch

        results = await gw.get_multiple_prices(["600519", "贵州茅台"])

        # Should only have 1 unique dispatch call despite 2 raw symbols
        unique_tickers = set(t for _, t in dispatch_calls)
        assert len(unique_tickers) <= 1, f"Expected ≤1 unique fetch, got {unique_tickers}"
