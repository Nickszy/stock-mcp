# src/server/domain/market_gateway.py
"""MarketGateway: unified gateway for symbol resolution + adapter routing.

Merged from MarketGateway + AdapterManager to eliminate redundant delegation.

Architecture (v3):
- Single entry point for all market data operations
- Symbol resolution → Adapter routing → Failover in one place
- Declarative method registries + __getattr__ for zero-boilerplate extensibility

Adding a new operation:
1. Add method to BaseDataAdapter (raise NotImplementedError)
2. Implement in the relevant Adapter(s)
3. Add method name to _TICKER_METHODS or _MARKET_METHODS — that's it
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from src.server.domain.adapters.base import BaseDataAdapter


class AdapterErrorResult(Exception):
    """Raised when an adapter returns a result dict containing an upstream error.

    Unlike NotImplementedError (adapter doesn't support the method),
    this means the adapter tried and the data source itself failed.
    The dispatch loop should NOT try fallback adapters — re-raise immediately.
    """
from src.server.domain.symbols.errors import SymbolResolutionError
from src.server.domain.symbols.types import InstrumentRef, ResolutionStatus
from src.server.domain.types import (
    Asset,
    AssetPrice,
    AssetType,
    DataSource,
    Exchange,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Declarative routing registries
# ---------------------------------------------------------------------------
# ticker-scoped: resolve raw_symbol → ticker, then dispatch to adapter
_TICKER_METHODS: Set[str] = {
    # core
    "get_financials",
    "get_financial_statements",
    "get_mainbz_info",
    "get_shareholder_info",
    "get_dividend_info",
    "get_forecast_info",
    "get_valuation_metrics",
    "get_money_flow",
    "get_chip_distribution",
    "get_filings",
    # US fundamental
    "get_earnings_history",
    "get_cash_flow_quality",
    "get_us_valuation_metrics",
    "get_us_institutional_holdings",
    "get_us_company_profile",
    "get_us_analyst_recommendations",
    "get_us_revenue_segments",
    "get_us_insider_trading",
    "get_us_share_statistics",
    "get_us_financial_health",
    # US technical
    "get_us_price_history",
    "get_us_volume_analysis",
    # Stock participant data (COL-144)
    "get_stock_northbound_holdings",
    "get_stock_top10_shareholders",
    # Quantitative (needs single symbol)
    "get_stock_factors",
    # Relative strength (needs single symbol + benchmark)
    "get_relative_strength",
}

# market-wide: no symbol resolution, forward kwargs as-is
_MARKET_METHODS: Set[str] = {
    "get_north_bound_flow",
    "get_money_supply",
    "get_inflation_data",
    "get_pmi_data",
    "get_gdp_data",
    "get_social_financing",
    "get_interest_rates",
    "get_market_liquidity",
    "get_market_money_flow",
    "resolve_sector",
    "get_sector_trend",
    "get_sector_money_flow_history",
    "get_sector_valuation_metrics",
    "get_ggt_daily",
    "get_us_sector_etf_analysis",
    "get_us_economic_growth",
    "get_us_inflation_employment",
    "get_us_interest_rates",
    "get_market_breadth",
    "calculate_technical_indicators",
    # New: extended data
    "get_margin_trading",
    "get_restricted_release",
    "get_repurchase_info",
    "get_index_constituents",
    "get_index_constituent_weights",
    "get_fund_nav",
    "get_bond_yield",
    "get_futures_main",
    "get_option_summary",
    # New: quantitative analysis
    "get_sector_pe_pb_historical",
    "get_etf_flow",
    "get_style_rotation",
    "get_futures_basis",
    "calculate_risk_metrics",
    # New: additional data domains
    "get_dragon_tiger_list",
    "get_block_trade",
    "get_convertible_bond",
    "get_fund_holdings",
    "get_commodity_inventory",
    # Stock participant data (COL-144)
    "get_stock_northbound_ranking",
    "get_stock_shareholder_changes",
    "get_stock_institutional_research",
    # Corporate action data (COL-147)
    "get_shareholder_holding_detail",
    "get_ipo_calendar",
    "get_ipo_info",
    # Technical signals
    "get_technical_signals",
    # Quantitative screener
    "screen_stocks",
    "get_industry_ranking",
    "get_concept_ranking",
    # US market overview
    "get_us_market_overview",
    # Fund data (COL-145)
    "search_funds",
    "get_fund_detail",
    "get_fund_ranking",
    "get_fund_manager",
    "get_fund_valuation",
    "get_fund_performance",
    "get_fund_scale",
    # Index data (COL-146)
    "get_index_list",
    "get_index_pe_pb",
    "get_index_performance",
    # ETF data
    "get_etf_list",
    "get_etf_detail",
    "get_etf_performance",
    # Factor / correlation / ranking (COL-142)
    "get_stock_correlation",
    "get_factor_ranking",
    # Fact packs (handle symbol resolution internally)
    "get_stock_fact_pack",
    "get_fund_fact_pack",
    "get_market_fact_pack",
    "get_us_stock_fact_pack",
    "get_etf_fact_pack",
    "get_index_fact_pack",
    "get_sector_fact_pack",
}


class MarketGateway:
    """Unified gateway: symbol resolution + adapter management + routing.

    Combines responsibilities that were previously split between
    MarketGateway and AdapterManager, eliminating redundant delegation.

    Features:
    - Adapter registration and routing table management
    - Symbol resolution (raw → normalized ticker)
    - Automatic failover to backup adapters
    - Declarative method registration via _TICKER_METHODS / _MARKET_METHODS
    """

    def __init__(
        self,
        symbol_resolver,
        market_router=None,
        provider_timeout_seconds: float = 12.0,
    ):
        """Initialize the unified gateway.

        Args:
            symbol_resolver: SymbolResolver for raw_symbol → ticker conversion
            market_router: Optional MarketRouter for advanced routing (e.g., health-based)
            provider_timeout_seconds: Timeout for individual adapter calls
        """
        # Symbol resolution
        self._resolver = symbol_resolver
        self._router = market_router

        # Adapter management (migrated from AdapterManager)
        self.adapters: Dict[DataSource, BaseDataAdapter] = {}
        self._adapter_order: List[BaseDataAdapter] = []
        self.exchange_routing: Dict[str, List[BaseDataAdapter]] = {}
        self._ticker_cache: Dict[str, BaseDataAdapter] = {}
        self._cache_lock = threading.Lock()
        self.lock = threading.RLock()
        self._provider_timeout_seconds = max(float(provider_timeout_seconds), 1.0)

        # Method cache for __getattr__ synthesized methods
        self._method_cache: Dict[str, Any] = {}

        logger.info("MarketGateway initialized (unified)")

    # =========================================================================
    # Adapter Management (migrated from AdapterManager)
    # =========================================================================

    def register_adapter(self, adapter: BaseDataAdapter) -> None:
        """Register a data adapter and rebuild routing table."""
        with self.lock:
            if adapter.source in self.adapters:
                logger.info(
                    f"Adapter already registered: {adapter.source.value}, skipping"
                )
                return
            self.adapters[adapter.source] = adapter
            self._adapter_order.append(adapter)
            self._rebuild_routing_table()
            logger.info(f"Registered adapter: {adapter.source.value}")

    def _rebuild_routing_table(self) -> None:
        """Rebuild routing table based on registered adapters' capabilities."""
        with self.lock:
            self.exchange_routing.clear()
            for adapter in self._adapter_order:
                capabilities = adapter.get_capabilities()
                supported_exchanges = set()
                for cap in capabilities:
                    for exchange in cap.exchanges:
                        exchange_key = (
                            exchange.value
                            if isinstance(exchange, Exchange)
                            else exchange
                        )
                        supported_exchanges.add(exchange_key)
                for exchange_key in supported_exchanges:
                    if exchange_key not in self.exchange_routing:
                        self.exchange_routing[exchange_key] = []
                    self.exchange_routing[exchange_key].append(adapter)
            with self._cache_lock:
                self._ticker_cache.clear()
            logger.debug(
                f"Routing table rebuilt with {len(self.exchange_routing)} exchanges"
            )

    def get_available_adapters(self) -> List[DataSource]:
        return list(self.adapters.keys())

    def get_adapter_by_provider(self, provider: str) -> Optional[BaseDataAdapter]:
        if not provider:
            return None
        try:
            ds = DataSource(provider)
        except Exception:
            ds = None
        with self.lock:
            if ds and ds in self.adapters:
                return self.adapters.get(ds)
            for key, adapter in self.adapters.items():
                if key.value == provider:
                    return adapter
        return None

    def get_adapters_for_exchange(self, exchange: str) -> List[BaseDataAdapter]:
        with self.lock:
            return self.exchange_routing.get(exchange, [])

    def get_adapters_for_asset_type(
        self, asset_type: AssetType
    ) -> List[BaseDataAdapter]:
        with self.lock:
            supporting = set()
            for adapter in self.adapters.values():
                if asset_type in adapter.get_supported_asset_types():
                    supporting.add(adapter)
            return list(supporting)

    def get_adapter_for_ticker(self, ticker: str) -> Optional[BaseDataAdapter]:
        """Get the best adapter for a specific ticker (with caching)."""
        with self._cache_lock:
            if ticker in self._ticker_cache:
                return self._ticker_cache[ticker]
        if ":" not in ticker:
            logger.warning(f"Invalid ticker format (missing ':'): {ticker}")
            return None
        exchange, _ = ticker.split(":", 1)
        adapters = self.get_adapters_for_exchange(exchange)
        if not adapters:
            logger.debug(f"No adapters registered for exchange: {exchange}")
            return None
        for adapter in adapters:
            if adapter.validate_ticker(ticker):
                with self._cache_lock:
                    self._ticker_cache[ticker] = adapter
                return adapter
        logger.warning(f"No suitable adapter found for ticker: {ticker}")
        return None

    def _get_fallbacks(
        self, ticker: str, primary: BaseDataAdapter
    ) -> List[BaseDataAdapter]:
        """Return fallback adapters for a ticker, excluding the primary."""
        if ":" not in ticker:
            return []
        exchange, _ = ticker.split(":", 1)
        return [
            a
            for a in self.get_adapters_for_exchange(exchange)
            if a is not primary and a.validate_ticker(ticker)
        ]

    # =========================================================================
    # Symbol Resolution (from original MarketGateway)
    # =========================================================================

    async def resolve_ticker(self, raw_symbol: str) -> str:
        """Resolve raw symbol to normalized ticker (e.g., 'AAPL' → 'NASDAQ:AAPL')."""
        resolution = await self._resolver.resolve(raw_symbol)
        if resolution.status == ResolutionStatus.RESOLVED and resolution.normalized:
            return resolution.normalized
        if resolution.status == ResolutionStatus.AMBIGUOUS:
            raise SymbolResolutionError(
                code="SYMBOL_AMBIGUOUS",
                message="symbol is ambiguous; specify exchange",
                raw=raw_symbol,
                candidates=[c.ticker for c in resolution.candidates],
            )
        if resolution.status == ResolutionStatus.NOT_FOUND:
            raise SymbolResolutionError(
                code="SYMBOL_NOT_FOUND",
                message="symbol not found",
                raw=raw_symbol,
            )
        raise SymbolResolutionError(
            code="SYMBOL_INVALID",
            message=resolution.reason or "invalid symbol",
            raw=raw_symbol,
        )

    async def resolve_instrument(self, raw_symbol: str) -> InstrumentRef:
        """Resolve raw symbol to full instrument reference."""
        resolution = await self._resolver.resolve(raw_symbol)
        if resolution.status == ResolutionStatus.RESOLVED and resolution.instrument:
            return resolution.instrument
        if resolution.status == ResolutionStatus.RESOLVED and resolution.normalized:
            exchange, symbol = resolution.normalized.split(":", 1)
            return resolution.instrument or InstrumentRef(
                canonical_id=f"stock|{exchange}|{symbol}",
                normalized=resolution.normalized,
                asset_type=resolution.asset_type or "stock",
                exchange=exchange,
                raw_input=raw_symbol,
            )
        if resolution.status == ResolutionStatus.AMBIGUOUS:
            raise SymbolResolutionError(
                code="SYMBOL_AMBIGUOUS",
                message="symbol is ambiguous; specify exchange",
                raw=raw_symbol,
                candidates=[c.ticker for c in resolution.candidates],
            )
        if resolution.status == ResolutionStatus.NOT_FOUND:
            raise SymbolResolutionError(
                code="SYMBOL_NOT_FOUND",
                message="symbol not found",
                raw=raw_symbol,
            )
        raise SymbolResolutionError(
            code="SYMBOL_INVALID",
            message=resolution.reason or "invalid symbol",
            raw=raw_symbol,
        )

    # =========================================================================
    # Core Dispatch Methods (unified routing + failover)
    # =========================================================================

    async def _dispatch_ticker(self, method: str, ticker: str, **kwargs) -> Any:
        """Generic dispatcher for ticker-scoped operations with auto-failover.

        Args:
            method: Name of the BaseDataAdapter method to call
            ticker: Normalized ticker (e.g., "NASDAQ:AAPL")
            **kwargs: Extra arguments forwarded to adapter method

        Raises:
            ValueError: If no adapter found or all adapters failed
        """
        primary = self.get_adapter_for_ticker(ticker)
        if not primary:
            raise ValueError(f"No adapter found for ticker: {ticker}")

        last_error: Exception = ValueError(f"No result for {ticker}.{method}")
        for adapter in [primary] + self._get_fallbacks(ticker, primary):
            try:
                result = await asyncio.wait_for(
                    getattr(adapter, method)(ticker, **kwargs),
                    timeout=self._provider_timeout_seconds,
                )
                if result is not None:
                    logger.debug(
                        f"{method}({ticker}) succeeded via {adapter.source.value}"
                    )
                    if adapter is not primary:
                        with self._cache_lock:
                            self._ticker_cache[ticker] = adapter
                    return self._sanitize_na(self._validate_adapter_result(result))
                logger.warning(
                    f"{adapter.source.value}.{method}({ticker}) returned None, trying next"
                )
            except (NotImplementedError, AttributeError):
                logger.debug(
                    f"{adapter.source.value} does not support {method}, skipping"
                )
            except AdapterErrorResult:
                raise  # upstream data error — don't try fallbacks
            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"timeout after {self._provider_timeout_seconds}s"
                )
                logger.warning(
                    f"{adapter.source.value}.{method}({ticker}) timeout"
                )
            except Exception as e:
                last_error = e
                logger.warning(f"{adapter.source.value}.{method}({ticker}) failed: {e}")

        raise ValueError(f"All adapters failed for {ticker}.{method}: {last_error}")

    async def _dispatch_market(self, method: str, **kwargs) -> Any:
        """Generic dispatcher for market-wide (non-ticker) operations.

        Tries adapters in registration order, skips NotImplementedError.

        Raises:
            ValueError: If no adapter supports the method
        """
        last_error: Exception = ValueError(f"No adapter supports {method}")
        for adapter in self._adapter_order:
            try:
                result = await asyncio.wait_for(
                    getattr(adapter, method)(**kwargs),
                    timeout=self._provider_timeout_seconds,
                )
                if result is not None:
                    return self._sanitize_na(self._validate_adapter_result(result))
            except (NotImplementedError, AttributeError):
                continue
            except AdapterErrorResult:
                raise  # upstream data error — don't try fallbacks
            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"timeout after {self._provider_timeout_seconds}s"
                )
                logger.warning(f"{adapter.source.value}.{method}() timeout")
            except Exception as e:
                last_error = e
                logger.warning(f"{adapter.source.value}.{method}() failed: {e}")

        raise ValueError(f"No adapter supports {method}: {last_error}")

    async def _dispatch_with_resolve(
        self, method: str, raw_symbol: str, **kwargs
    ) -> Any:
        """Resolve raw_symbol → ticker, then dispatch to adapter.

        This is the unified entry point for most ticker-scoped operations.
        """
        ticker = await self.resolve_ticker(raw_symbol)
        return await self._dispatch_ticker(method, ticker, **kwargs)

    # =========================================================================
    # Explicit Methods — kept for special routing logic
    # =========================================================================

    async def get_asset_info(self, raw_symbol: str) -> Optional[Asset]:
        """Get asset information with symbol resolution."""
        try:
            return await self._dispatch_with_resolve("get_asset_info", raw_symbol)
        except ValueError:
            return None

    async def get_real_time_price(self, raw_symbol: str) -> Optional[AssetPrice]:
        """Get real-time price with router support."""
        instrument = await self.resolve_instrument(raw_symbol)
        if self._router and hasattr(instrument, "normalized"):
            return await self._router.get_real_time_price(instrument)
        return await self._dispatch_ticker("get_real_time_price", instrument.normalized)

    async def get_historical_prices(
        self,
        raw_symbol: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> List[AssetPrice]:
        """Get historical prices with router support."""
        instrument = await self.resolve_instrument(raw_symbol)
        if self._router and hasattr(instrument, "normalized"):
            return await self._router.get_historical_prices(
                instrument, start_date, end_date, interval
            )
        try:
            result = await self._dispatch_ticker(
                "get_historical_prices",
                instrument.normalized,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )
            return result or []
        except ValueError:
            return []

    async def get_multiple_prices(
        self, raw_symbols: List[str]
    ) -> Dict[str, Optional[AssetPrice]]:
        """Batch price lookup with parallel resolution."""
        if self._router:
            results: Dict[str, Any] = {}
            for raw in raw_symbols:
                try:
                    instrument = await self.resolve_instrument(raw)
                    price = await self._router.get_real_time_price(instrument)
                    results[raw] = (
                        price.to_dict()
                        if price and hasattr(price, "to_dict")
                        else price
                    )
                except SymbolResolutionError as e:
                    results[raw] = {"error": e.to_dict()}
            return results

        # Parallel resolution + batch fetch
        resolutions = await asyncio.gather(
            *[self._resolver.resolve(sym) for sym in raw_symbols],
            return_exceptions=True,
        )
        resolved_map: Dict[str, Optional[str]] = {}
        errors: Dict[str, dict] = {}

        for raw, res in zip(raw_symbols, resolutions):
            if isinstance(res, Exception):
                errors[raw] = {
                    "error": {"code": "RESOLVE_FAILED", "message": str(res), "raw": raw}
                }
                continue
            if res.status == ResolutionStatus.RESOLVED and res.normalized:
                resolved_map[raw] = res.normalized
            elif res.status == ResolutionStatus.AMBIGUOUS:
                errors[raw] = {
                    "error": {
                        "code": "SYMBOL_AMBIGUOUS",
                        "message": "symbol is ambiguous; specify exchange",
                        "raw": raw,
                        "candidates": [c.ticker for c in res.candidates],
                    }
                }
            elif res.status == ResolutionStatus.NOT_FOUND:
                errors[raw] = {
                    "error": {
                        "code": "SYMBOL_NOT_FOUND",
                        "message": "symbol not found",
                        "raw": raw,
                    }
                }
            else:
                errors[raw] = {
                    "error": {
                        "code": "SYMBOL_INVALID",
                        "message": res.reason or "invalid symbol",
                        "raw": raw,
                    }
                }

        results: Dict[str, Any] = {}
        resolved_tickers = [t for t in resolved_map.values() if t]
        if resolved_tickers:
            tasks = {t: self._dispatch_ticker("get_real_time_price", t) for t in resolved_tickers}
            price_results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            price_map = {t: r for t, r in zip(tasks.keys(), price_results)}

            for raw, resolved in resolved_map.items():
                price = price_map.get(resolved)
                if isinstance(price, Exception):
                    results[raw] = None
                elif price is not None and hasattr(price, "to_dict"):
                    data = price.to_dict()
                    data["resolved_ticker"] = resolved
                    results[raw] = data
                else:
                    results[raw] = None

        for raw, err in errors.items():
            results[raw] = err
        for raw in raw_symbols:
            results.setdefault(raw, None)
        return results

    async def get_profit_forecast(self, raw_symbol: str) -> Dict[str, Any]:
        """Get profit forecast with special fallback logic."""
        ticker = await self.resolve_ticker(raw_symbol)
        adapter = self.get_adapter_for_ticker(ticker)
        if not adapter:
            raise ValueError(f"No adapter found for ticker {ticker}")

        try:
            return await adapter.get_profit_forecast(ticker)
        except Exception as e:
            if isinstance(e, NotImplementedError):
                logger.warning(f"{adapter.source.value} does not support profit forecast")
            else:
                logger.warning(f"{adapter.source.value} failed: {e}")

            # Try fallback adapters
            if ":" in ticker:
                exchange, _ = ticker.split(":", 1)
                for alt in self.get_adapters_for_exchange(exchange):
                    if alt is adapter:
                        continue
                    try:
                        logger.info(f"Trying fallback {alt.source.value} for {ticker}")
                        return await alt.get_profit_forecast(ticker)
                    except Exception as fe:
                        logger.warning(f"Fallback {alt.source.value} also failed: {fe}")

            raise ValueError(f"All adapters failed for profit forecast {ticker}: {e}")

    async def get_technical_indicators(
        self,
        raw_symbol: str | None = None,
        indicators: List[str] | None = None,
        period: str = "daily",
        start_date=None,
        end_date=None,
        *,
        ticker: str | None = None,
    ) -> Dict[str, Any]:
        """Dual-signature: accepts raw_symbol or pre-resolved ticker."""
        if ticker:
            resolved = ticker if ":" in ticker else await self.resolve_ticker(ticker)
        else:
            if not raw_symbol:
                raise ValueError("raw_symbol or ticker is required")
            resolved = await self.resolve_ticker(raw_symbol)
        return await self._dispatch_ticker(
            "get_technical_indicators",
            resolved,
            indicators=indicators or [],
            period=period,
            start_date=start_date,
            end_date=end_date,
        )

    async def get_technical_signals(self, raw_symbol: str) -> Dict[str, Any]:
        """Get deterministic technical signals (RSI/MACD/BOLL) for a symbol."""
        resolved = await self.resolve_ticker(raw_symbol)
        return await self._dispatch_ticker("get_technical_signals", resolved)

    async def get_north_bound_flow(self, days: int = 30) -> Dict[str, Any]:
        """North-bound flow with Tushare preference."""
        if DataSource.TUSHARE in self.adapters:
            try:
                return await self.adapters[DataSource.TUSHARE].get_north_bound_flow(days)
            except Exception as e:
                logger.warning(f"Tushare failed for north_bound_flow: {e}")
        return await self._dispatch_market("get_north_bound_flow", days=days)

    async def resolve_sector(self, query_text: str, intent: str = "trend") -> Dict[str, Any]:
        """Resolve sector with cross-adapter fallback."""
        last_not_found: Optional[Dict[str, Any]] = None
        last_error: Optional[Exception] = None

        for adapter in self._adapter_order:
            try:
                result = await asyncio.wait_for(
                    adapter.resolve_sector(query_text=query_text, intent=intent),
                    timeout=self._provider_timeout_seconds,
                )
                if not isinstance(result, dict):
                    continue
                status = str(result.get("status", "")).lower()
                if status in {"resolved", "ambiguous"}:
                    return result
                if status == "not_found":
                    last_not_found = result
                    continue
                return result
            except (NotImplementedError, AttributeError):
                continue
            except asyncio.TimeoutError:
                last_error = TimeoutError(f"timeout after {self._provider_timeout_seconds}s")
                logger.warning(f"{adapter.source.value}.resolve_sector() timeout")
            except Exception as e:
                last_error = e
                logger.warning(f"{adapter.source.value}.resolve_sector() failed: {e}")

        if last_not_found is not None:
            return last_not_found
        raise ValueError(f"No adapter supports resolve_sector: {last_error}")

    # =========================================================================
    # Fact Pack methods — always route to AkshareAdapter
    # =========================================================================

    def _akshare_adapter(self) -> BaseDataAdapter:
        """Get the AkshareAdapter, raising if unavailable."""
        adapter = self.adapters.get(DataSource.AKSHARE)
        if adapter is None:
            raise ValueError("AkshareAdapter is not registered")
        return adapter

    @staticmethod
    def _sanitize_na(obj: Any) -> Any:
        """Recursively convert pandas NA / NaN / Nat to None for JSON."""
        import pandas as pd
        import numpy as np
        if isinstance(obj, dict):
            return {k: MarketGateway._sanitize_na(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [MarketGateway._sanitize_na(v) for v in obj]
        if isinstance(obj, float) and (np.isnan(obj) or pd.isna(obj)):
            return None
        try:
            if pd.isna(obj):
                return None
        except (TypeError, ValueError):
            pass
        return obj

    @staticmethod
    def _validate_adapter_result(result: Any) -> Any:
        """Raise if adapter silently returned an error dict instead of raising.

        Many adapter methods catch exceptions and return {"error": str(e), "data": []}
        which then gets wrapped as HTTP 200 success by the route layer.
        This method detects that pattern and re-raises as a proper exception.
        """
        if isinstance(result, dict) and "error" in result:
            data = result.get("data")
            if data is None or data == [] or data == {}:
                err_msg = result["error"]
                raise AdapterErrorResult(f"Upstream data error: {err_msg}")
        return result

    async def get_stock_fact_pack(self, symbol: str) -> Dict[str, Any]:
        """Get aggregated stock fact pack (AkshareAdapter only)."""
        result = await self._akshare_adapter().get_stock_fact_pack(symbol)
        return self._sanitize_na(result)

    async def get_fund_fact_pack(self, fund_code: str) -> Dict[str, Any]:
        """Get aggregated fund fact pack (AkshareAdapter only)."""
        result = await self._akshare_adapter().get_fund_fact_pack(fund_code)
        return self._sanitize_na(result)

    async def get_etf_fact_pack(self, symbol: str) -> Dict[str, Any]:
        """Get aggregated ETF fact pack (AkshareAdapter only)."""
        result = await self._akshare_adapter().get_etf_fact_pack(symbol)
        return self._sanitize_na(result)

    async def get_index_fact_pack(self, symbol: str) -> Dict[str, Any]:
        """Get aggregated index fact pack (AkshareAdapter only)."""
        result = await self._akshare_adapter().get_index_fact_pack(symbol)
        return self._sanitize_na(result)

    async def get_market_fact_pack(self, symbol: str) -> Dict[str, Any]:
        """Get aggregated market fact pack (AkshareAdapter only)."""
        result = await self._akshare_adapter().get_market_fact_pack(symbol)
        return self._sanitize_na(result)

    # ------------------------------------------------------------------
    # US Stock Fact Pack (COL-164)
    # ------------------------------------------------------------------
    def _yahoo_adapter(self) -> "BaseDataAdapter":
        """Get the YahooAdapter, raising if unavailable."""
        from src.server.domain.types import DataSource
        adapter = self.adapters.get(DataSource.YAHOO)
        if adapter is None:
            raise ValueError("YahooAdapter is not registered")
        return adapter

    async def get_us_stock_fact_pack(self, ticker: str) -> Dict[str, Any]:
        """Get aggregated US stock fact pack (YahooAdapter only)."""
        result = await self._yahoo_adapter().get_us_stock_fact_pack(ticker)
        return self._sanitize_na(result)

    async def get_sector_fact_pack(self, sector_name: str) -> Dict[str, Any]:
        """Get aggregated sector fact pack (AkshareAdapter only)."""
        return await self._ak_adapter().get_sector_fact_pack(sector_name)

    # =========================================================================
    # __getattr__: synthesize ticker-scoped and market-wide methods
    # =========================================================================

    def __getattr__(self, item: str):
        """Dynamically synthesize methods based on _TICKER_METHODS / _MARKET_METHODS."""
        if item.startswith("_"):
            raise AttributeError(item)

        cache = object.__getattribute__(self, "_method_cache")
        if item in cache:
            return cache[item]

        if item in _TICKER_METHODS:
            async def _ticker_method(raw_symbol: str, *args, **kwargs):
                return await self._dispatch_with_resolve(item, raw_symbol, **kwargs)
            _ticker_method.__name__ = item
            _ticker_method.__qualname__ = f"MarketGateway.{item}"
            cache[item] = _ticker_method
            return _ticker_method

        if item in _MARKET_METHODS:
            async def _market_method(*args, **kwargs):
                return await self._dispatch_market(item, **kwargs)
            _market_method.__name__ = item
            _market_method.__qualname__ = f"MarketGateway.{item}"
            cache[item] = _market_method
            return _market_method

        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{item}'")


# ---------------------------------------------------------------------------
# Singleton (for backward compatibility during migration)
# ---------------------------------------------------------------------------

_gateway_instance: Optional["MarketGateway"] = None
_gateway_lock = threading.Lock()


def get_market_gateway() -> MarketGateway:
    """Get singleton instance (deprecated: use DI container instead)."""
    global _gateway_instance
    if _gateway_instance is None:
        with _gateway_lock:
            if _gateway_instance is None:
                raise RuntimeError(
                    "MarketGateway not initialized. Use DI container instead."
                )
    return _gateway_instance
