# tests/test_market_gateway.py
"""Comprehensive tests for MarketGateway: routing, failover, symbol resolution, errors.

Covers:
1. Adapter registration and routing table construction
2. get_real_time_price routing for A-share / US / Crypto
3. _dispatch_ticker: primary selection + fallback
4. _dispatch_market: market-wide method routing
5. __getattr__ synthesized methods (_TICKER_METHODS / _MARKET_METHODS)
6. Symbol resolution integration (resolve_ticker / resolve_instrument)
7. Error handling: unknown asset types, all adapters failing, invalid tickers
8. AdapterErrorResult short-circuit (upstream data errors)
9. _sanitize_na (NaN / pd.NA cleanup)
10. Fact pack routing (akshare / yahoo adapters)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncio
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server.domain.market_gateway import (
    AdapterErrorResult,
    MarketGateway,
    _MARKET_METHODS,
    _TICKER_METHODS,
)
from src.server.domain.symbols.errors import SymbolResolutionError
from src.server.domain.symbols.types import (
    InstrumentRef,
    ResolutionStatus,
    SymbolResolution,
)
from src.server.domain.types import (
    AdapterCapability,
    AssetPrice,
    AssetType,
    DataSource,
    Exchange,
)


# ---------------------------------------------------------------------------
# Helpers: build mock adapters and resolver
# ---------------------------------------------------------------------------


def _make_adapter(
    source: DataSource,
    exchanges: list[Exchange],
    asset_types: list[AssetType] | None = None,
):
    """Build a lightweight mock adapter with real capabilities.

    Returns a MagicMock that has .source set and get_capabilities /
    validate_ticker wired up correctly so the routing table logic works.
    """
    adapter = MagicMock()
    adapter.source = source

    caps = [AdapterCapability(asset_type=AssetType.STOCK, exchanges=set(exchanges))]
    if asset_types:
        caps = [
            AdapterCapability(asset_type=at, exchanges=set(exchanges))
            for at in asset_types
        ]
    adapter.get_capabilities.return_value = caps
    adapter.get_supported_asset_types.return_value = list(
        {c.asset_type for c in caps}
    )

    # validate_ticker mirrors the real BaseDataAdapter logic
    def _validate(ticker: str) -> bool:
        if ":" not in ticker:
            return False
        exch = ticker.split(":", 1)[0]
        return any(Exchange(exch) in c.exchanges for c in caps)

    adapter.validate_ticker.side_effect = _validate
    return adapter


def _make_resolver(resolved_ticker: str | None = "SSE:600519"):
    """Build a mock symbol resolver that always resolves to *resolved_ticker*."""
    resolver = MagicMock()
    resolution = SymbolResolution(
        raw="input",
        normalized=resolved_ticker,
        status=ResolutionStatus.RESOLVED,
        exchange=resolved_ticker.split(":")[0] if resolved_ticker else None,
        asset_type="stock",
    )
    resolution.instrument = InstrumentRef(
        canonical_id=f"stock|{resolved_ticker}",
        normalized=resolved_ticker,
        asset_type="stock",
        exchange=resolved_ticker.split(":")[0] if resolved_ticker else "",
        raw_input="input",
    )
    resolver.resolve = AsyncMock(return_value=resolution)
    return resolver


def _make_price(ticker: str, price: float = 100.0) -> AssetPrice:
    return AssetPrice(
        ticker=ticker,
        price=Decimal(str(price)),
        currency="USD",
        timestamp=datetime(2026, 1, 1),
    )


def _build_gateway(
    adapters: list[tuple[DataSource, list[Exchange]]],
    resolved_ticker: str = "SSE:600519",
    quote_cache=None,
    provider_timeout: float = 12.0,
) -> MarketGateway:
    """Create a MarketGateway with pre-registered adapters and a mock resolver."""
    resolver = _make_resolver(resolved_ticker)
    gw = MarketGateway(
        symbol_resolver=resolver,
        provider_timeout_seconds=provider_timeout,
        quote_cache=quote_cache,
    )
    for source, exchanges in adapters:
        adapter = _make_adapter(source, exchanges)
        gw.register_adapter(adapter)
    return gw


# ===========================================================================
# 1. Adapter Registration & Routing Table
# ===========================================================================


class TestAdapterRegistration:
    """Verify adapter registration and routing table construction."""

    def test_register_single_adapter(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE, Exchange.SZSE])])
        assert DataSource.AKSHARE in gw.adapters
        assert len(gw.adapters) == 1

    def test_register_multiple_adapters(self):
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE, Exchange.SZSE]),
            (DataSource.YAHOO, [Exchange.NASDAQ, Exchange.NYSE]),
        ])
        assert len(gw.adapters) == 2
        assert DataSource.AKSHARE in gw.adapters
        assert DataSource.YAHOO in gw.adapters

    def test_duplicate_registration_ignored(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        # Manually register same source again
        dup = _make_adapter(DataSource.AKSHARE, [Exchange.SSE])
        gw.register_adapter(dup)
        assert len(gw.adapters) == 1

    def test_routing_table_populated(self):
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE, Exchange.SZSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        # SSE should have both adapters
        sse_adapters = gw.get_adapters_for_exchange("SSE")
        assert len(sse_adapters) == 2
        # SZSE should only have akshare
        szse_adapters = gw.get_adapters_for_exchange("SZSE")
        assert len(szse_adapters) == 1

    def test_get_available_adapters(self):
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.YAHOO, [Exchange.NASDAQ]),
        ])
        available = gw.get_available_adapters()
        assert DataSource.AKSHARE in available
        assert DataSource.YAHOO in available

    def test_get_adapter_by_provider_string(self):
        gw = _build_gateway([(DataSource.YAHOO, [Exchange.NASDAQ])])
        adapter = gw.get_adapter_by_provider("yahoo")
        assert adapter is not None
        assert adapter.source == DataSource.YAHOO

    def test_get_adapter_by_provider_empty(self):
        gw = _build_gateway([(DataSource.YAHOO, [Exchange.NASDAQ])])
        assert gw.get_adapter_by_provider("") is None

    def test_get_adapter_by_provider_unknown(self):
        gw = _build_gateway([(DataSource.YAHOO, [Exchange.NASDAQ])])
        assert gw.get_adapter_by_provider("nonexistent") is None

    def test_get_adapters_for_asset_type(self):
        gw = _build_gateway([(DataSource.YAHOO, [Exchange.NASDAQ])])
        adapters = gw.get_adapters_for_asset_type(AssetType.STOCK)
        assert len(adapters) >= 1

    def test_get_adapters_for_asset_type_no_match(self):
        gw = _build_gateway([(DataSource.YAHOO, [Exchange.NASDAQ])])
        adapters = gw.get_adapters_for_asset_type(AssetType.CRYPTO)
        assert len(adapters) == 0

    def test_get_adapter_for_ticker_cached(self):
        """Second call for same ticker should hit cache."""
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        adapter1 = gw.get_adapter_for_ticker("SSE:600519")
        adapter2 = gw.get_adapter_for_ticker("SSE:600519")
        assert adapter1 is adapter2


# ===========================================================================
# 2. Price Routing: A-share, US, Crypto
# ===========================================================================


class TestGetRealTimePriceRouting:
    """Verify get_real_time_price routes to the correct adapter based on ticker."""

    @pytest.mark.asyncio
    async def test_a_share_routed_to_akshare(self):
        """SSE tickers should be routed to the A-share adapter."""
        gw = _build_gateway(
            adapters=[
                (DataSource.AKSHARE, [Exchange.SSE, Exchange.SZSE]),
                (DataSource.YAHOO, [Exchange.NASDAQ]),
            ],
            resolved_ticker="SSE:600519",
        )
        price = _make_price("SSE:600519", 1800.0)
        # Only akshare adapter should be called
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_real_time_price = AsyncMock(return_value=price)

        result = await gw.get_real_time_price("600519")
        assert result is not None
        assert result.ticker == "SSE:600519"
        akshare.get_real_time_price.assert_awaited_once_with("SSE:600519")

    @pytest.mark.asyncio
    async def test_us_stock_routed_to_yahoo(self):
        """NASDAQ tickers should be routed to the US adapter."""
        gw = _build_gateway(
            adapters=[
                (DataSource.AKSHARE, [Exchange.SSE]),
                (DataSource.YAHOO, [Exchange.NASDAQ, Exchange.NYSE]),
            ],
            resolved_ticker="NASDAQ:AAPL",
        )
        price = _make_price("NASDAQ:AAPL", 195.0)
        yahoo = gw.adapters[DataSource.YAHOO]
        yahoo.get_real_time_price = AsyncMock(return_value=price)

        result = await gw.get_real_time_price("AAPL")
        assert result is not None
        assert result.ticker == "NASDAQ:AAPL"
        yahoo.get_real_time_price.assert_awaited_once_with("NASDAQ:AAPL")

    @pytest.mark.asyncio
    async def test_crypto_routed_to_ccxt(self):
        """CRYPTO tickers should be routed to the crypto adapter."""
        gw = _build_gateway(
            adapters=[
                (DataSource.CCXT, [Exchange.CRYPTO]),
            ],
            resolved_ticker="CRYPTO:BTC",
        )
        # Override resolver to return crypto resolution
        from src.server.domain.symbols.types import SymbolResolution, ResolutionStatus
        crypto_resolution = SymbolResolution(
            raw="BTC",
            normalized="CRYPTO:BTC",
            status=ResolutionStatus.RESOLVED,
            exchange="CRYPTO",
            asset_type="crypto",
        )
        crypto_resolution.instrument = InstrumentRef(
            canonical_id="crypto|CRYPTO|BTC",
            normalized="CRYPTO:BTC",
            asset_type="crypto",
            exchange="CRYPTO",
            raw_input="BTC",
        )
        gw._resolver.resolve = AsyncMock(return_value=crypto_resolution)

        price = _make_price("CRYPTO:BTC", 42000.0)
        ccxt = gw.adapters[DataSource.CCXT]
        ccxt.get_real_time_price = AsyncMock(return_value=price)

        result = await gw.get_real_time_price("BTC")
        assert result is not None
        assert result.ticker == "CRYPTO:BTC"

    @pytest.mark.asyncio
    async def test_price_raises_when_adapter_returns_none(self):
        """If the adapter returns None for all, gateway should raise ValueError."""
        gw = _build_gateway(
            adapters=[(DataSource.AKSHARE, [Exchange.SSE])],
            resolved_ticker="SSE:600519",
        )
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_real_time_price = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="All adapters failed"):
            await gw.get_real_time_price("600519")

    @pytest.mark.asyncio
    async def test_price_uses_quote_cache_when_available(self):
        """When quote_cache is provided, it should be used for caching."""
        mock_cache = MagicMock()
        cached_data = {
            "ticker": "SSE:600519",
            "price": 1800.0,
            "currency": "CNY",
            "timestamp": "2026-01-01T00:00:00",
            "source": "akshare",
        }
        mock_cache.get_or_fetch = AsyncMock(return_value=cached_data)

        gw = _build_gateway(
            adapters=[(DataSource.AKSHARE, [Exchange.SSE])],
            resolved_ticker="SSE:600519",
            quote_cache=mock_cache,
        )

        result = await gw.get_real_time_price("600519")
        assert result is not None
        assert result.ticker == "SSE:600519"
        mock_cache.get_or_fetch.assert_awaited_once()


# ===========================================================================
# 3. Dispatch & Fallback Logic
# ===========================================================================


class TestDispatchTicker:
    """Verify _dispatch_ticker selects primary adapter and falls back."""

    @pytest.mark.asyncio
    async def test_primary_adapter_succeeds(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_financials = AsyncMock(
            return_value={"ticker": "SSE:600519", "data": "ok"}
        )

        result = await gw._dispatch_ticker("get_financials", "SSE:600519")
        assert result["data"] == "ok"
        akshare.get_financials.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_when_primary_fails(self):
        """When primary adapter raises, fallback adapter should be tried."""
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        akshare = gw.adapters[DataSource.AKSHARE]
        tushare = gw.adapters[DataSource.TUSHARE]

        # Primary fails
        akshare.get_financials = AsyncMock(side_effect=RuntimeError("API error"))
        # Fallback succeeds
        tushare.get_financials = AsyncMock(
            return_value={"ticker": "SSE:600519", "data": "from_tushare"}
        )

        result = await gw._dispatch_ticker("get_financials", "SSE:600519")
        assert result["data"] == "from_tushare"
        tushare.get_financials.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fallback_skips_not_implemented(self):
        """NotImplementedError should be skipped, not treated as hard failure."""
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        akshare = gw.adapters[DataSource.AKSHARE]
        tushare = gw.adapters[DataSource.TUSHARE]

        akshare.get_financials = AsyncMock(side_effect=NotImplementedError("nope"))
        tushare.get_financials = AsyncMock(
            return_value={"ticker": "SSE:600519", "data": "tushare"}
        )

        result = await gw._dispatch_ticker("get_financials", "SSE:600519")
        assert result["data"] == "tushare"

    @pytest.mark.asyncio
    async def test_adapter_error_result_short_circuits(self):
        """AdapterErrorResult should re-raise immediately without trying fallbacks."""
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        akshare = gw.adapters[DataSource.AKSHARE]
        tushare = gw.adapters[DataSource.TUSHARE]

        akshare.get_financials = AsyncMock(
            side_effect=AdapterErrorResult("Upstream data error: rate limited")
        )
        tushare.get_financials = AsyncMock(return_value={"should": "not be called"})

        with pytest.raises(AdapterErrorResult, match="Upstream data error"):
            await gw._dispatch_ticker("get_financials", "SSE:600519")
        # Fallback should NOT be called
        tushare.get_financials.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_all_adapters_failing_raises_value_error(self):
        """If all adapters fail, raise ValueError with last error."""
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        akshare = gw.adapters[DataSource.AKSHARE]
        tushare = gw.adapters[DataSource.TUSHARE]

        akshare.get_financials = AsyncMock(side_effect=RuntimeError("fail1"))
        tushare.get_financials = AsyncMock(side_effect=RuntimeError("fail2"))

        with pytest.raises(ValueError, match="All adapters failed"):
            await gw._dispatch_ticker("get_financials", "SSE:600519")

    @pytest.mark.asyncio
    async def test_no_adapter_found_raises_value_error(self):
        """Ticker with no matching adapter raises ValueError."""
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        with pytest.raises(ValueError, match="No adapter found"):
            await gw._dispatch_ticker("get_financials", "NASDAQ:AAPL")

    @pytest.mark.asyncio
    async def test_adapter_returning_none_tries_fallback(self):
        """Adapter returning None (not error) should trigger fallback."""
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        akshare = gw.adapters[DataSource.AKSHARE]
        tushare = gw.adapters[DataSource.TUSHARE]

        akshare.get_financials = AsyncMock(return_value=None)
        tushare.get_financials = AsyncMock(
            return_value={"ticker": "SSE:600519", "data": "fallback"}
        )

        result = await gw._dispatch_ticker("get_financials", "SSE:600519")
        assert result["data"] == "fallback"

    @pytest.mark.asyncio
    async def test_validate_adapter_result_raises_on_error_dict(self):
        """_validate_adapter_result should raise AdapterErrorResult for error dicts."""
        error_result = {"error": "upstream timeout", "data": []}
        with pytest.raises(AdapterErrorResult):
            MarketGateway._validate_adapter_result(error_result)

    @pytest.mark.asyncio
    async def test_validate_adapter_result_passes_good_data(self):
        """Normal data dicts should pass through validation."""
        good_data = {"data": [{"price": 100}], "ticker": "SSE:600519"}
        result = MarketGateway._validate_adapter_result(good_data)
        assert result == good_data

    @pytest.mark.asyncio
    async def test_validate_adapter_result_passes_non_dict(self):
        """Non-dict results (lists, objects) should pass through."""
        assert MarketGateway._validate_adapter_result([1, 2, 3]) == [1, 2, 3]


class TestDispatchMarket:
    """Verify _dispatch_market routes to adapters in registration order."""

    @pytest.mark.asyncio
    async def test_first_adapter_succeeds(self):
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_money_supply = AsyncMock(
            return_value={"months": 60, "data": "ok"}
        )

        result = await gw._dispatch_market("get_money_supply", months=60)
        assert result["data"] == "ok"

    @pytest.mark.asyncio
    async def test_skips_not_implemented_tries_next(self):
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        akshare = gw.adapters[DataSource.AKSHARE]
        tushare = gw.adapters[DataSource.TUSHARE]

        akshare.get_money_supply = AsyncMock(
            side_effect=NotImplementedError("nope")
        )
        tushare.get_money_supply = AsyncMock(
            return_value={"months": 60, "data": "from_tushare"}
        )

        result = await gw._dispatch_market("get_money_supply", months=60)
        assert result["data"] == "from_tushare"

    @pytest.mark.asyncio
    async def test_no_adapter_supports_raises_value_error(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_money_supply = AsyncMock(
            side_effect=NotImplementedError("nope")
        )

        with pytest.raises(ValueError, match="No adapter supports"):
            await gw._dispatch_market("get_money_supply", months=60)

    @pytest.mark.asyncio
    async def test_adapter_error_result_short_circuits(self):
        """AdapterErrorResult in market dispatch also re-raises immediately."""
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        akshare = gw.adapters[DataSource.AKSHARE]
        tushare = gw.adapters[DataSource.TUSHARE]

        akshare.get_money_supply = AsyncMock(
            side_effect=AdapterErrorResult("data source down")
        )
        tushare.get_money_supply = AsyncMock(return_value={"should": "not be called"})

        with pytest.raises(AdapterErrorResult, match="data source down"):
            await gw._dispatch_market("get_money_supply", months=60)
        tushare.get_money_supply.assert_not_awaited()


# ===========================================================================
# 4. __getattr__ Synthesized Methods
# ===========================================================================


class TestSynthesizedMethods:
    """Verify __getattr__ dynamically creates ticker and market methods."""

    def test_ticker_method_is_callable(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        method = gw.get_financials
        assert callable(method)

    def test_market_method_is_callable(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        method = gw.get_money_supply
        assert callable(method)

    def test_unknown_method_raises_attribute_error(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        with pytest.raises(AttributeError):
            _ = gw.this_method_does_not_exist

    def test_private_attribute_raises_attribute_error(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        with pytest.raises(AttributeError):
            _ = gw._some_private_thing

    def test_method_cached_on_second_access(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        method1 = gw.get_financials
        method2 = gw.get_financials
        assert method1 is method2

    @pytest.mark.asyncio
    async def test_ticker_method_resolves_and_dispatches(self):
        """Synthesized ticker method should resolve raw symbol then dispatch."""
        gw = _build_gateway(
            adapters=[(DataSource.AKSHARE, [Exchange.SSE])],
            resolved_ticker="SSE:600519",
        )
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_financials = AsyncMock(
            return_value={"ticker": "SSE:600519", "revenue": 100}
        )

        result = await gw.get_financials("600519")
        assert result["revenue"] == 100
        # Verify symbol resolution was called
        gw._resolver.resolve.assert_awaited_once_with("600519")

    @pytest.mark.asyncio
    async def test_market_method_dispatches_without_resolve(self):
        """Synthesized market method should dispatch directly without resolution."""
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_money_supply = AsyncMock(
            return_value={"months": 60, "data": "ok"}
        )

        result = await gw.get_money_supply(months=60)
        assert result["data"] == "ok"
        # Resolver should NOT have been called for market methods
        gw._resolver.resolve.assert_not_awaited()


# ===========================================================================
# 5. Symbol Resolution Integration
# ===========================================================================


class TestSymbolResolution:
    """Verify resolve_ticker and resolve_instrument behavior."""

    @pytest.mark.asyncio
    async def test_resolve_ticker_success(self):
        resolver = _make_resolver("SSE:600519")
        gw = MarketGateway(symbol_resolver=resolver)
        result = await gw.resolve_ticker("600519")
        assert result == "SSE:600519"

    @pytest.mark.asyncio
    async def test_resolve_ticker_ambiguous_raises(self):
        from src.server.domain.symbols.types import SymbolCandidate

        resolver = MagicMock()
        resolution = SymbolResolution(
            raw="AAPL",
            status=ResolutionStatus.AMBIGUOUS,
            candidates=[
                SymbolCandidate(ticker="NASDAQ:AAPL", exchange="NASDAQ"),
                SymbolCandidate(ticker="NYSE:AAPL", exchange="NYSE"),
            ],
        )
        resolver.resolve = AsyncMock(return_value=resolution)
        gw = MarketGateway(symbol_resolver=resolver)

        with pytest.raises(SymbolResolutionError) as exc_info:
            await gw.resolve_ticker("AAPL")
        assert exc_info.value.code == "SYMBOL_AMBIGUOUS"
        assert len(exc_info.value.candidates) == 2

    @pytest.mark.asyncio
    async def test_resolve_ticker_not_found_raises(self):
        resolver = MagicMock()
        resolution = SymbolResolution(
            raw="XYZABC",
            status=ResolutionStatus.NOT_FOUND,
        )
        resolver.resolve = AsyncMock(return_value=resolution)
        gw = MarketGateway(symbol_resolver=resolver)

        with pytest.raises(SymbolResolutionError) as exc_info:
            await gw.resolve_ticker("XYZABC")
        assert exc_info.value.code == "SYMBOL_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_resolve_ticker_invalid_raises(self):
        resolver = MagicMock()
        resolution = SymbolResolution(
            raw="!!!",
            status=ResolutionStatus.INVALID,
            reason="bad characters",
        )
        resolver.resolve = AsyncMock(return_value=resolution)
        gw = MarketGateway(symbol_resolver=resolver)

        with pytest.raises(SymbolResolutionError) as exc_info:
            await gw.resolve_ticker("!!!")
        assert exc_info.value.code == "SYMBOL_INVALID"

    @pytest.mark.asyncio
    async def test_resolve_instrument_success(self):
        resolver = _make_resolver("NASDAQ:AAPL")
        gw = MarketGateway(symbol_resolver=resolver)
        result = await gw.resolve_instrument("AAPL")
        assert isinstance(result, InstrumentRef)
        assert result.normalized == "NASDAQ:AAPL"

    @pytest.mark.asyncio
    async def test_resolve_instrument_not_found_raises(self):
        resolver = MagicMock()
        resolution = SymbolResolution(
            raw="UNKNOWN",
            status=ResolutionStatus.NOT_FOUND,
        )
        resolver.resolve = AsyncMock(return_value=resolution)
        gw = MarketGateway(symbol_resolver=resolver)

        with pytest.raises(SymbolResolutionError, match="not found"):
            await gw.resolve_instrument("UNKNOWN")

    @pytest.mark.asyncio
    async def test_dispatch_with_resolve_resolves_then_dispatches(self):
        """_dispatch_with_resolve should first resolve, then dispatch."""
        gw = _build_gateway(
            adapters=[(DataSource.AKSHARE, [Exchange.SSE])],
            resolved_ticker="SSE:600519",
        )
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_financials = AsyncMock(return_value={"data": "ok"})

        result = await gw._dispatch_with_resolve("get_financials", "600519")
        assert result["data"] == "ok"
        gw._resolver.resolve.assert_awaited_once_with("600519")


# ===========================================================================
# 6. Error Handling
# ===========================================================================


class TestErrorHandling:
    """Verify error handling for edge cases."""

    @pytest.mark.asyncio
    async def test_no_adapter_for_exchange(self):
        """Ticker with unregistered exchange returns no adapter."""
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        adapter = gw.get_adapter_for_ticker("NASDAQ:AAPL")
        assert adapter is None

    @pytest.mark.asyncio
    async def test_invalid_ticker_format_no_colon(self):
        """Ticker without ':' should not match any adapter."""
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        adapter = gw.get_adapter_for_ticker("600519")
        assert adapter is None

    @pytest.mark.asyncio
    async def test_empty_ticker_returns_none(self):
        """Empty string ticker should return None."""
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        adapter = gw.get_adapter_for_ticker("")
        assert adapter is None

    @pytest.mark.asyncio
    async def test_get_asset_info_raises_on_resolve_failure(self):
        """get_asset_info should raise SymbolResolutionError when resolution fails."""
        resolver = MagicMock()
        resolution = SymbolResolution(
            raw="BAD",
            status=ResolutionStatus.NOT_FOUND,
        )
        resolver.resolve = AsyncMock(return_value=resolution)
        gw = MarketGateway(symbol_resolver=resolver)
        # No adapters registered

        with pytest.raises(SymbolResolutionError, match="not found"):
            await gw.get_asset_info("BAD")

    @pytest.mark.asyncio
    async def test_get_historical_prices_returns_empty_on_failure(self):
        """get_historical_prices should return [] when dispatch fails."""
        gw = _build_gateway(
            adapters=[(DataSource.AKSHARE, [Exchange.SSE])],
            resolved_ticker="SSE:600519",
        )
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_historical_prices = AsyncMock(side_effect=ValueError("no data"))

        result = await gw.get_historical_prices(
            "600519",
            start_date=datetime(2026, 1, 1),
            end_date=datetime(2026, 1, 31),
        )
        assert result == []


# ===========================================================================
# 7. _sanitize_na
# ===========================================================================


class TestSanitizeNA:
    """Verify NaN / pd.NA values are cleaned up."""

    def test_float_nan_becomes_none(self):
        import math

        result = MarketGateway._sanitize_na(float("nan"))
        assert result is None

    def test_float_inf_passes_through(self):
        result = MarketGateway._sanitize_na(float("inf"))
        assert result == float("inf")

    def test_nested_dict_nan_cleaned(self):
        result = MarketGateway._sanitize_na(
            {"key": float("nan"), "normal": 42.0}
        )
        assert result["key"] is None
        assert result["normal"] == 42.0

    def test_list_nan_cleaned(self):
        result = MarketGateway._sanitize_na([float("nan"), 1.0, "hello"])
        assert result[0] is None
        assert result[1] == 1.0
        assert result[2] == "hello"

    def test_normal_values_unchanged(self):
        data = {"price": 100.5, "name": "AAPL", "active": True}
        assert MarketGateway._sanitize_na(data) == data


# ===========================================================================
# 8. Fact Pack Methods
# ===========================================================================


class TestFactPackMethods:
    """Verify fact pack methods route to specific adapters."""

    @pytest.mark.asyncio
    async def test_get_stock_fact_pack_routes_to_akshare(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_stock_fact_pack = AsyncMock(
            return_value={"symbol": "600519", "facts": "data"}
        )

        result = await gw.get_stock_fact_pack("600519")
        assert result["facts"] == "data"
        akshare.get_stock_fact_pack.assert_awaited_once_with("600519")

    @pytest.mark.asyncio
    async def test_get_us_stock_fact_pack_routes_to_yahoo(self):
        gw = _build_gateway([(DataSource.YAHOO, [Exchange.NASDAQ])])
        yahoo = gw.adapters[DataSource.YAHOO]
        yahoo.get_us_stock_fact_pack = AsyncMock(
            return_value={"ticker": "AAPL", "facts": "us_data"}
        )

        result = await gw.get_us_stock_fact_pack("AAPL")
        assert result["facts"] == "us_data"
        yahoo.get_us_stock_fact_pack.assert_awaited_once_with("AAPL")

    @pytest.mark.asyncio
    async def test_get_stock_fact_pack_raises_without_akshare(self):
        gw = _build_gateway([(DataSource.YAHOO, [Exchange.NASDAQ])])
        with pytest.raises(ValueError, match="AkshareAdapter is not registered"):
            await gw.get_stock_fact_pack("600519")

    @pytest.mark.asyncio
    async def test_get_us_stock_fact_pack_raises_without_yahoo(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        with pytest.raises(ValueError, match="YahooAdapter is not registered"):
            await gw.get_us_stock_fact_pack("AAPL")

    @pytest.mark.asyncio
    async def test_get_fund_fact_pack_routes_to_akshare(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_fund_fact_pack = AsyncMock(
            return_value={"fund_code": "000001", "facts": "fund_data"}
        )

        result = await gw.get_fund_fact_pack("000001")
        assert result["fund_code"] == "000001"

    @pytest.mark.asyncio
    async def test_get_sector_fact_pack_routes_to_akshare(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_sector_fact_pack = AsyncMock(
            return_value={"sector": "banking", "facts": "sector_data"}
        )

        result = await gw.get_sector_fact_pack("banking")
        assert result["sector"] == "banking"


# ===========================================================================
# 9. Special Routing Methods
# ===========================================================================


class TestSpecialRoutingMethods:
    """Verify methods with custom routing logic (north_bound_flow, resolve_sector, etc.)."""

    @pytest.mark.asyncio
    async def test_get_north_bound_flow_prefers_tushare(self):
        """When Tushare adapter is registered, north_bound_flow prefers it."""
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        tushare = gw.adapters[DataSource.TUSHARE]
        tushare.get_north_bound_flow = AsyncMock(
            return_value={"days": 30, "data": "from_tushare"}
        )

        result = await gw.get_north_bound_flow(days=30)
        assert result["data"] == "from_tushare"
        tushare.get_north_bound_flow.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_north_bound_flow_falls_back_when_tushare_fails(self):
        """When Tushare fails, should fall back to _dispatch_market."""
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        tushare = gw.adapters[DataSource.TUSHARE]
        akshare = gw.adapters[DataSource.AKSHARE]

        tushare.get_north_bound_flow = AsyncMock(
            side_effect=RuntimeError("Tushare API down")
        )
        akshare.get_north_bound_flow = AsyncMock(
            return_value={"days": 30, "data": "from_akshare"}
        )

        result = await gw.get_north_bound_flow(days=30)
        assert result["data"] == "from_akshare"

    @pytest.mark.asyncio
    async def test_resolve_sector_returns_resolved(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.resolve_sector = AsyncMock(
            return_value={"status": "resolved", "sector_id": "bank_01"}
        )

        result = await gw.resolve_sector("banking", intent="trend")
        assert result["status"] == "resolved"
        assert result["sector_id"] == "bank_01"

    @pytest.mark.asyncio
    async def test_resolve_sector_returns_not_found_if_all_not_found(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.resolve_sector = AsyncMock(
            return_value={"status": "not_found", "sector_id": None}
        )

        result = await gw.resolve_sector("xyz_sector")
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_resolve_sector_raises_when_all_fail(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.resolve_sector = AsyncMock(
            side_effect=RuntimeError("API down")
        )

        with pytest.raises(ValueError, match="No adapter supports resolve_sector"):
            await gw.resolve_sector("broken")

    @pytest.mark.asyncio
    async def test_get_profit_forecast_fallback(self):
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.TUSHARE, [Exchange.SSE]),
        ])
        akshare = gw.adapters[DataSource.AKSHARE]
        tushare = gw.adapters[DataSource.TUSHARE]

        # Make resolver return a known ticker
        resolver = _make_resolver("SSE:600519")
        gw._resolver = resolver

        akshare.get_profit_forecast = AsyncMock(
            side_effect=NotImplementedError("nope")
        )
        tushare.get_profit_forecast = AsyncMock(
            return_value={"ticker": "SSE:600519", "forecast": "bullish"}
        )

        result = await gw.get_profit_forecast("600519")
        assert result["forecast"] == "bullish"


# ===========================================================================
# 10. get_multiple_prices
# ===========================================================================


class TestGetMultiplePrices:
    """Verify batch price resolution and fetching."""

    @pytest.mark.asyncio
    async def test_multiple_prices_parallel(self):
        gw = _build_gateway([
            (DataSource.AKSHARE, [Exchange.SSE]),
            (DataSource.YAHOO, [Exchange.NASDAQ]),
        ])
        akshare = gw.adapters[DataSource.AKSHARE]
        yahoo = gw.adapters[DataSource.YAHOO]

        # Setup resolver to return different results for different inputs
        from src.server.domain.symbols.types import SymbolResolution, ResolutionStatus

        r1 = SymbolResolution(
            raw="600519",
            normalized="SSE:600519",
            status=ResolutionStatus.RESOLVED,
            exchange="SSE",
            asset_type="stock",
        )
        r2 = SymbolResolution(
            raw="AAPL",
            normalized="NASDAQ:AAPL",
            status=ResolutionStatus.RESOLVED,
            exchange="NASDAQ",
            asset_type="stock",
        )
        gw._resolver.resolve = AsyncMock(side_effect=[r1, r2])

        price_a = _make_price("SSE:600519", 1800.0)
        price_b = _make_price("NASDAQ:AAPL", 195.0)
        akshare.get_real_time_price = AsyncMock(return_value=price_a)
        yahoo.get_real_time_price = AsyncMock(return_value=price_b)

        results = await gw.get_multiple_prices(["600519", "AAPL"])
        assert len(results) == 2
        assert "600519" in results
        assert "AAPL" in results

    @pytest.mark.asyncio
    async def test_multiple_prices_handles_resolution_failure(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])

        from src.server.domain.symbols.types import SymbolResolution, ResolutionStatus

        r_ok = SymbolResolution(
            raw="600519",
            normalized="SSE:600519",
            status=ResolutionStatus.RESOLVED,
            exchange="SSE",
            asset_type="stock",
        )
        r_fail = SymbolResolution(
            raw="BAD",
            status=ResolutionStatus.NOT_FOUND,
        )
        gw._resolver.resolve = AsyncMock(side_effect=[r_ok, r_fail])

        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_real_time_price = AsyncMock(
            return_value=_make_price("SSE:600519", 1800.0)
        )

        results = await gw.get_multiple_prices(["600519", "BAD"])
        assert "600519" in results
        assert "BAD" in results
        # The failed resolution should have error info
        bad_result = results["BAD"]
        assert isinstance(bad_result, dict)
        assert "error" in bad_result

    @pytest.mark.asyncio
    async def test_multiple_prices_deduplicates_tickers(self):
        """Two raw symbols resolving to same ticker should only fetch once."""
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])

        from src.server.domain.symbols.types import SymbolResolution, ResolutionStatus

        r1 = SymbolResolution(
            raw="600519",
            normalized="SSE:600519",
            status=ResolutionStatus.RESOLVED,
            exchange="SSE",
            asset_type="stock",
        )
        r2 = SymbolResolution(
            raw="maotai",
            normalized="SSE:600519",  # Same resolved ticker
            status=ResolutionStatus.RESOLVED,
            exchange="SSE",
            asset_type="stock",
        )
        gw._resolver.resolve = AsyncMock(side_effect=[r1, r2])

        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_real_time_price = AsyncMock(
            return_value=_make_price("SSE:600519", 1800.0)
        )

        results = await gw.get_multiple_prices(["600519", "maotai"])
        # Should only call adapter once (deduplicated)
        assert akshare.get_real_time_price.call_count == 1


# ===========================================================================
# 11. get_technical_indicators (dual-signature)
# ===========================================================================


class TestGetTechnicalIndicators:
    """Verify dual-signature routing (raw_symbol vs pre-resolved ticker)."""

    @pytest.mark.asyncio
    async def test_with_raw_symbol(self):
        gw = _build_gateway(
            adapters=[(DataSource.AKSHARE, [Exchange.SSE])],
            resolved_ticker="SSE:600519",
        )
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_technical_indicators = AsyncMock(
            return_value={"ticker": "SSE:600519", "MA5": 100}
        )

        result = await gw.get_technical_indicators(raw_symbol="600519")
        assert result["MA5"] == 100

    @pytest.mark.asyncio
    async def test_with_pre_resolved_ticker(self):
        gw = _build_gateway(
            adapters=[(DataSource.AKSHARE, [Exchange.SSE])],
            resolved_ticker="SSE:600519",
        )
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_technical_indicators = AsyncMock(
            return_value={"ticker": "SSE:600519", "MA5": 100}
        )

        result = await gw.get_technical_indicators(ticker="SSE:600519")
        assert result["MA5"] == 100
        # Should NOT call resolver since ticker is already normalized
        gw._resolver.resolve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_without_symbol_or_ticker(self):
        gw = _build_gateway([(DataSource.AKSHARE, [Exchange.SSE])])
        with pytest.raises(ValueError, match="raw_symbol or ticker is required"):
            await gw.get_technical_indicators()


# ===========================================================================
# 12. Method Registries Sanity
# ===========================================================================


class TestMethodRegistries:
    """Sanity checks on _TICKER_METHODS and _MARKET_METHODS."""

    def test_ticker_methods_not_empty(self):
        assert len(_TICKER_METHODS) > 0

    def test_market_methods_not_empty(self):
        assert len(_MARKET_METHODS) > 0

    def test_no_overlap_between_registries(self):
        overlap = _TICKER_METHODS & _MARKET_METHODS
        assert len(overlap) == 0, f"Methods in both registries: {overlap}"

    def test_known_ticker_methods_present(self):
        for method in [
            "get_financials",
            "get_financial_statements",
            "get_dividend_info",
            "get_money_flow",
        ]:
            assert method in _TICKER_METHODS, f"{method} missing from _TICKER_METHODS"

    def test_known_market_methods_present(self):
        for method in [
            "get_north_bound_flow",
            "get_money_supply",
            "get_gdp_data",
            "screen_stocks",
        ]:
            assert method in _MARKET_METHODS, f"{method} missing from _MARKET_METHODS"


# ===========================================================================
# 13. Timeout Behavior
# ===========================================================================


class TestTimeoutBehavior:
    """Verify timeout configuration and behavior."""

    def test_minimum_timeout_enforced(self):
        """Provider timeout should have a minimum of 1.0 second."""
        gw = MarketGateway(
            symbol_resolver=MagicMock(),
            provider_timeout_seconds=0.0,
        )
        assert gw._provider_timeout_seconds >= 1.0

    def test_negative_timeout_clamped(self):
        gw = MarketGateway(
            symbol_resolver=MagicMock(),
            provider_timeout_seconds=-5.0,
        )
        assert gw._provider_timeout_seconds >= 1.0

    def test_custom_timeout_preserved(self):
        gw = MarketGateway(
            symbol_resolver=MagicMock(),
            provider_timeout_seconds=30.0,
        )
        assert gw._provider_timeout_seconds == 30.0


# ===========================================================================
# 14. get_technical_signals
# ===========================================================================


class TestGetTechnicalSignals:
    """Verify get_technical_signals resolves and dispatches."""

    @pytest.mark.asyncio
    async def test_resolves_and_dispatches(self):
        gw = _build_gateway(
            adapters=[(DataSource.AKSHARE, [Exchange.SSE])],
            resolved_ticker="SSE:600519",
        )
        akshare = gw.adapters[DataSource.AKSHARE]
        akshare.get_technical_signals = AsyncMock(
            return_value={"ticker": "SSE:600519", "RSI": 65}
        )

        result = await gw.get_technical_signals("600519")
        assert result["RSI"] == 65
        gw._resolver.resolve.assert_awaited_once_with("600519")
