# src/server/domain/adapter_manager.py
"""AdapterManager for coordinating multiple data source adapters.

This manager routes ticker symbols to appropriate adapters based on
capabilities, with support for caching, failover, and LLM-based fallback search.

Aligned with ValueCell's architecture.

Monitoring Integration:
- All adapter calls are automatically logged to Redis (non-blocking, < 1ms)
- Data type is auto-detected from method name
- Latency, status, has_data are tracked
"""

import threading
import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.server.domain.adapters.base import BaseDataAdapter
from src.server.domain.types import (
    Asset,
    AssetPrice,
    AssetType,
    DataSource,
    Exchange,
)
from src.server.utils.logger import logger  # Use structlog instead of standard logging
from src.server.monitoring.redis_backend import (
    RedisMonitoring,
    RequestLog,
    RequestStatus,
    Alert,
    AlertSeverity,
    get_redis_monitoring,
)


# 方法名 → 数据类型映射（用于自动识别监控类型）
METHOD_TO_DATA_TYPE = {
    # 价格相关
    "get_real_time_price": "price",
    "get_historical_prices": "kline",
    "get_multiple_prices": "price",
    "get_kline_data": "kline",

    # 财务相关
    "get_financials": "financials",
    "get_financial_statements": "financials",
    "get_dividend_info": "dividend",
    "get_forecast_info": "forecast",
    "get_earnings_history": "earnings",
    "get_cash_flow_quality": "cashflow",
    "get_profit_forecast": "forecast",
    "get_mainbz_info": "business",
    "get_shareholder_info": "shareholder",

    # 资产信息
    "get_asset_info": "asset_info",
    "get_valuation_metrics": "valuation",
    "get_us_valuation_metrics": "valuation",

    # 资金流向
    "get_money_flow": "money_flow",
    "get_north_bound_flow": "north_bound",
    "get_market_money_flow": "market_flow",
    "get_chip_distribution": "chip",

    # 宏观数据
    "get_money_supply": "macro",
    "get_inflation_data": "macro",
    "get_pmi_data": "macro",
    "get_gdp_data": "macro",
    "get_social_financing": "macro",
    "get_interest_rates": "macro",
    "get_market_liquidity": "macro",
    "get_us_economic_growth": "macro",
    "get_us_inflation_employment": "macro",
    "get_us_interest_rates": "macro",

    # 板块相关
    "get_sector_trend": "sector",
    "resolve_sector": "sector",
    "get_sector_money_flow_history": "sector",
    "get_sector_valuation_metrics": "sector",

    # 公告/文件
    "get_filings": "filings",
    "get_filings_list": "filings",

    # 技术指标
    "get_technical_indicators": "technical",

    # 美股特有
    "get_earnings_history": "earnings",
    "get_us_institutional_holdings": "holdings",
    "get_us_volume_analysis": "volume",
    "get_us_sector_etf_analysis": "sector",
}


class AdapterManager:
    """Manager for coordinating multiple asset data adapters.

    Provides unified interface for:
    - Asset search
    - Real-time prices
    - Historical prices
    - Asset information
    - Batch operations

    Extension pattern (adding a new operation):
    1. Add the method to BaseDataAdapter (raise NotImplementedError)
    2. Implement in the relevant Adapter(s)
    3. Add a 2-line delegation method here using _dispatch_ticker or _dispatch_market
    4. Add a 1-line delegation in MarketGateway
    5. Add a 1-line delegation in use_cases/
    6. Create the MCP tool file and register in registry.py
    """

    def __init__(self, provider_timeout_seconds: float = 12.0):
        """Initialize adapter manager."""
        self.adapters: Dict[DataSource, BaseDataAdapter] = {}
        self._adapter_order: List[BaseDataAdapter] = []
        self.exchange_routing: Dict[str, List[BaseDataAdapter]] = {}
        self._ticker_cache_max_size = 10000  # 限制缓存大小
        self._ticker_cache: Dict[str, BaseDataAdapter] = {}
        self._cache_lock = threading.Lock()
        self.lock = threading.RLock()
        self._provider_timeout_seconds = max(float(provider_timeout_seconds), 1.0)

        # 监控实例（延迟初始化）
        self._monitoring: Optional[RedisMonitoring] = None

        # 告警限流缓存：{alert_key: last_alert_time}
        self._alert_throttle: Dict[str, float] = {}
        self._alert_throttle_ttl = 60  # 同类型告警 60 秒内只发一次

        logger.info("Asset adapter manager initialized")

    def _get_monitoring(self) -> Optional[RedisMonitoring]:
        """延迟获取监控实例（避免启动时 Redis 未就绪）"""
        if self._monitoring is None:
            try:
                self._monitoring = get_redis_monitoring()
            except Exception as e:
                logger.warning(f"Redis monitoring not available: {e}")
        return self._monitoring

    # =========================================================================
    # Internal routing infrastructure (do NOT duplicate below)
    # =========================================================================

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

    def register_adapter(self, adapter: BaseDataAdapter) -> None:
        """Register a data adapter and rebuild routing table."""
        with self.lock:
            if adapter.source in self.adapters:
                logger.info(
                    f"Adapter already registered: {adapter.source.value}, skipping duplicate"
                )
                return
            self.adapters[adapter.source] = adapter
            self._adapter_order.append(adapter)
            self._rebuild_routing_table()
            logger.info(f"Registered adapter: {adapter.source.value}")

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
                    # LRU 缓存：超过限制时清理一半
                    if len(self._ticker_cache) >= self._ticker_cache_max_size:
                        # 删除前一半（最旧的条目）
                        keys_to_remove = list(self._ticker_cache.keys())[:len(self._ticker_cache) // 2]
                        for k in keys_to_remove:
                            del self._ticker_cache[k]
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

    async def _dispatch_ticker(self, method: str, ticker: str, **kwargs) -> Any:
        """Generic dispatcher for ticker-scoped operations with auto-failover and monitoring.

        This is THE single place where failover logic lives.
        All per-ticker business methods delegate here.

        Args:
            method:  Name of the BaseDataAdapter method to call.
            ticker:  Internal ticker (e.g. "NASDAQ:AAPL").
            **kwargs: Extra keyword arguments forwarded to the adapter method.

        Raises:
            ValueError: If no adapter found or all adapters failed.
        """
        # ========== 监控变量初始化 ==========
        start_time = time.time()
        data_type = METHOD_TO_DATA_TYPE.get(method, "unknown")
        used_adapter: Optional[BaseDataAdapter] = None
        status = RequestStatus.FAILED.value
        error_message: Optional[str] = None
        has_data = False
        fields_count = 0

        primary = self.get_adapter_for_ticker(ticker)
        if not primary:
            error_message = f"No adapter found for ticker: {ticker}"
            # 记录失败日志
            self._log_to_monitoring(
                data_type=data_type,
                source="unknown",
                instrument_id=ticker,
                status=RequestStatus.FAILED.value,
                latency_ms=(time.time() - start_time) * 1000,
                error_message=error_message,
                has_data=False,
                fields_count=0,
                metadata={"method": method},
            )
            raise ValueError(error_message)

        last_error: Exception = ValueError(f"No result for {ticker}.{method}")

        try:
            for adapter in [primary] + self._get_fallbacks(ticker, primary):
                try:
                    result = await asyncio.wait_for(
                        getattr(adapter, method)(ticker, **kwargs),
                        timeout=self._provider_timeout_seconds,
                    )
                    # For methods that return collections, treat empty as "no data"
                    if result is not None:
                        used_adapter = adapter
                        status = RequestStatus.SUCCESS.value
                        has_data, fields_count = self._extract_result_info(result)

                        logger.debug(
                            f"{method}({ticker}) succeeded via {adapter.source.value}"
                        )
                        # Update ticker cache if we used a fallback
                        if adapter is not primary:
                            with self._cache_lock:
                                # LRU 缓存：超过限制时清理一半
                                if len(self._ticker_cache) >= self._ticker_cache_max_size:
                                    keys_to_remove = list(self._ticker_cache.keys())[:len(self._ticker_cache) // 2]
                                    for k in keys_to_remove:
                                        del self._ticker_cache[k]
                                self._ticker_cache[ticker] = adapter
                        return result
                    logger.warning(
                        f"{adapter.source.value}.{method}({ticker}) returned None, trying next"
                    )
                except NotImplementedError:
                    logger.debug(
                        f"{adapter.source.value} does not support {method}, skipping"
                    )
                except asyncio.TimeoutError:
                    last_error = TimeoutError(
                        f"timeout after {self._provider_timeout_seconds}s"
                    )
                    error_message = f"Timeout after {self._provider_timeout_seconds}s"
                    logger.warning(
                        f"{adapter.source.value}.{method}({ticker}) timeout in "
                        f"{self._provider_timeout_seconds}s"
                    )
                except Exception as e:
                    last_error = e
                    error_message = f"{type(e).__name__}: {str(e)}"
                    logger.warning(f"{adapter.source.value}.{method}({ticker}) failed: {e}")

            raise ValueError(f"All adapters failed for {ticker}.{method}: {last_error}")

        finally:
            # ========== 非阻塞记录监控日志 ==========
            latency_ms = (time.time() - start_time) * 1000
            source = used_adapter.source.value if used_adapter else primary.source.value

            self._log_to_monitoring(
                data_type=data_type,
                source=source,
                instrument_id=ticker,
                status=status,
                latency_ms=latency_ms,
                error_message=error_message,
                has_data=has_data,
                fields_count=fields_count,
                metadata={"method": method},
            )

            # 检查是否需要告警
            self._check_and_alert(source, data_type, status, latency_ms)

    async def _dispatch_market(self, method: str, **kwargs) -> Any:
        """Generic dispatcher for market-wide (non-ticker) operations with monitoring.

        Tries adapters in registration order, skips NotImplementedError.

        Args:
            method:  Name of the BaseDataAdapter method to call.
            **kwargs: Extra keyword arguments forwarded to the adapter method.

        Raises:
            ValueError: If no adapter supports the method.
        """
        # ========== 监控变量初始化 ==========
        start_time = time.time()
        data_type = METHOD_TO_DATA_TYPE.get(method, "unknown")
        instrument_id = self._extract_market_instrument_id(method, kwargs)
        used_adapter: Optional[BaseDataAdapter] = None
        status = RequestStatus.FAILED.value
        error_message: Optional[str] = None
        has_data = False
        fields_count = 0

        last_error: Exception = ValueError(f"No adapter supports {method}")

        try:
            for adapter in self._adapter_order:
                try:
                    result = await asyncio.wait_for(
                        getattr(adapter, method)(**kwargs),
                        timeout=self._provider_timeout_seconds,
                    )
                    if result is not None:
                        used_adapter = adapter
                        status = RequestStatus.SUCCESS.value
                        has_data, fields_count = self._extract_result_info(result)
                        return result
                except NotImplementedError:
                    continue
                except asyncio.TimeoutError:
                    last_error = TimeoutError(
                        f"timeout after {self._provider_timeout_seconds}s"
                    )
                    error_message = str(last_error)
                    logger.warning(
                        f"{adapter.source.value}.{method}() timeout in "
                        f"{self._provider_timeout_seconds}s"
                    )
                except Exception as e:
                    last_error = e
                    error_message = f"{type(e).__name__}: {str(e)}"
                    logger.warning(f"{adapter.source.value}.{method}() failed: {e}")

            raise ValueError(f"No adapter supports {method}: {last_error}")

        finally:
            # ========== 非阻塞记录监控日志 ==========
            latency_ms = (time.time() - start_time) * 1000
            source = used_adapter.source.value if used_adapter else "unknown"

            self._log_to_monitoring(
                data_type=data_type,
                source=source,
                instrument_id=instrument_id,
                status=status,
                latency_ms=latency_ms,
                error_message=error_message,
                has_data=has_data,
                fields_count=fields_count,
                metadata={"method": method},
            )

            # 检查是否需要告警
            if used_adapter:
                self._check_and_alert(source, data_type, status, latency_ms)

    # =========================================================================
    # Core price / asset operations  (use dedicated implementations for perf)
    # =========================================================================

    async def get_asset_info(self, ticker: str) -> Optional[Asset]:
        try:
            return await self._dispatch_ticker("get_asset_info", ticker)
        except ValueError:
            return None

    async def get_real_time_price(
        self, ticker: str, source: Optional[str] = None
    ) -> Optional[AssetPrice]:
        """Get real-time price with optional source specification.

        Args:
            ticker: Asset ticker (e.g., "SSE:600519")
            source: Optional data source name (e.g., "akshare", "tushare")

        Returns:
            AssetPrice if successful, None otherwise
        """
        try:
            if source:
                # Use specified source
                adapter = self.adapters.get(source)
                logger.info(f"🔍 Adapter lookup for '{source}': {adapter is not None}")
                if not adapter:
                    logger.warning(
                        f"Source '{source}' not found, using auto-selection"
                    )
                    return await self._dispatch_ticker("get_real_time_price", ticker)

                logger.info(
                    f"🔍 Using specified source '{source}' for ticker '{ticker}'"
                )

                if not adapter.validate_ticker(ticker):
                    logger.warning(
                        f"Source '{source}' does not support ticker: {ticker}"
                    )
                    return None

                logger.info(f"✅ Ticker '{ticker}' validated for source '{source}'")

                try:
                    result = await asyncio.wait_for(
                        adapter.get_real_time_price(ticker),
                        timeout=self._provider_timeout_seconds,
                    )
                    logger.info(
                        f"📊 Source '{source}' returned: {result is not None} for '{ticker}'"
                    )
                    return result
                except Exception as e:
                    logger.error(
                        f"❌ Source '{source}' failed for '{ticker}': {e}",
                        exc_info=True,
                    )
                    return None
            else:
                # Auto-select best source
                return await self._dispatch_ticker("get_real_time_price", ticker)
        except ValueError:
            return None
        except asyncio.TimeoutError:
            logger.warning(
                f"Timeout fetching price for {ticker} from {source or 'auto'}"
            )
            return None

    async def get_historical_prices(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> List[AssetPrice]:
        try:
            result = await self._dispatch_ticker(
                "get_historical_prices",
                ticker,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
            )
            return result or []
        except ValueError:
            return []

    async def get_multiple_prices(
        self, tickers: List[str], source: Optional[str] = None
    ) -> Dict[str, Optional[AssetPrice]]:
        """Get multiple prices with optional source specification.

        Args:
            tickers: List of asset tickers
            source: Optional data source name (applies to all tickers)

        Returns:
            Dict mapping ticker to AssetPrice (or None if failed)
        """
        import asyncio

        tasks = {t: self.get_real_time_price(t, source=source) for t in tickers}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return {
            ticker: (None if isinstance(r, Exception) else r)
            for ticker, r in zip(tasks.keys(), results)
        }

    # =========================================================================
    # Ticker-scoped business operations — each is a 2-liner via _dispatch_ticker
    # =========================================================================

    async def get_financials(self, ticker: str) -> Dict[str, Any]:
        return await self._dispatch_ticker("get_financials", ticker)

    async def get_financial_statements(
        self,
        ticker: str,
        report_type: str = "all",
        periods: int | None = None,
    ) -> Dict[str, Any]:
        """Fetch complete financial statements with YoY/QoQ calculations."""
        return await self._dispatch_ticker(
            "get_financial_statements", ticker, report_type=report_type, periods=periods
        )

    async def get_dividend_info(self, ticker: str) -> Dict[str, Any]:
        return await self._dispatch_ticker("get_dividend_info", ticker)

    async def get_forecast_info(
        self, ticker: str, limit: int = 50
    ) -> Dict[str, Any]:
        return await self._dispatch_ticker("get_forecast_info", ticker, limit=limit)

    async def get_mainbz_info(self, ticker: str) -> Dict[str, Any]:
        return await self._dispatch_ticker("get_mainbz_info", ticker)

    async def get_shareholder_info(self, ticker: str) -> Dict[str, Any]:
        return await self._dispatch_ticker("get_shareholder_info", ticker)

    async def get_valuation_metrics(
        self, ticker: str, days: int = 250
    ) -> Dict[str, Any]:
        return await self._dispatch_ticker("get_valuation_metrics", ticker, days=days)

    async def get_money_flow(self, ticker: str, days: int = 20) -> Dict[str, Any]:
        return await self._dispatch_ticker("get_money_flow", ticker, days=days)

    async def get_chip_distribution(
        self, ticker: str, days: int = 30
    ) -> Dict[str, Any]:
        return await self._dispatch_ticker("get_chip_distribution", ticker, days=days)

    async def get_filings(
        self,
        ticker: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 10,
        filing_types: Optional[List[str]] = None,
    ) -> List[Dict]:
        return await self._dispatch_ticker(
            "get_filings",
            ticker,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            filing_types=filing_types,
        )

    async def get_profit_forecast(self, ticker: str) -> Dict[str, Any]:
        """获取盈利预测 (带自动降级)."""
        adapter = self.get_adapter_for_ticker(ticker)
        if not adapter:
            raise ValueError(f"No adapter found for ticker {ticker}")

        try:
            return await adapter.get_profit_forecast(ticker)
        except Exception as e:
            if isinstance(e, NotImplementedError):
                logger.warning(f"Adapter {adapter.source.value} does not support profit forecast")
            else:
                logger.warning(f"Adapter {adapter.source.value} failed: {e}")

            if ":" in ticker:
                exchange, _ = ticker.split(":", 1)
                adapters = self.get_adapters_for_exchange(exchange)

                for alt in adapters:
                    if alt is adapter:
                        continue
                    try:
                        logger.info(
                            f"Trying failover adapter {alt.source.value} for profit forecast of {ticker}"
                        )
                        return await alt.get_profit_forecast(ticker)
                    except Exception as failover_error:
                        logger.warning(
                            f"Failover adapter {alt.source.value} also failed: {failover_error}"
                        )
                        continue

            raise ValueError(
                f"All adapters failed to fetch profit forecast for {ticker}: {e}"
            )

    async def get_technical_indicators(
        self,
        ticker: str,
        indicators: List[str],
        period: str = "daily",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        return await self._dispatch_ticker(
            "get_technical_indicators",
            ticker,
            indicators=indicators,
            period=period,
            start_date=start_date,
            end_date=end_date,
        )

    # --- NEW: US-market specific ticker operations ---

    async def get_earnings_history(
        self, ticker: str, quarters: int = 8
    ) -> Dict[str, Any]:
        """Fetch EPS history with estimate vs actual and surprise %."""
        return await self._dispatch_ticker(
            "get_earnings_history", ticker, quarters=quarters
        )

    async def get_cash_flow_quality(self, ticker: str) -> Dict[str, Any]:
        """Fetch operating/free cash flow and FCF/net-income ratio."""
        return await self._dispatch_ticker("get_cash_flow_quality", ticker)

    async def get_us_valuation_metrics(self, ticker: str) -> Dict[str, Any]:
        """Fetch US stock PE/PS/PB/EV_EBITDA with historical percentile."""
        return await self._dispatch_ticker("get_us_valuation_metrics", ticker)

    async def get_us_institutional_holdings(self, ticker: str) -> Dict[str, Any]:
        """Fetch top institutional holders and recent change direction."""
        return await self._dispatch_ticker("get_us_institutional_holdings", ticker)

    async def get_us_price_history(
        self, ticker: str, days: int = 60, interval: str = "1d"
    ) -> Dict[str, Any]:
        """Fetch OHLCV klines for US stock."""
        return await self._dispatch_ticker(
            "get_us_price_history", ticker, days=days, interval=interval
        )

    async def get_us_volume_analysis(
        self, ticker: str, days: int = 30
    ) -> Dict[str, Any]:
        """Fetch volume metrics: avg volume, RVol, OBV trend."""
        return await self._dispatch_ticker("get_us_volume_analysis", ticker, days=days)

    async def get_us_sector_etf_analysis(
        self, sector_name: str, days: int = 30
    ) -> Dict[str, Any]:
        """Fetch US sector ETF klines by sector name."""
        return await self._dispatch_market(
            "get_us_sector_etf_analysis", sector_name=sector_name, days=days
        )

    async def get_us_economic_growth(self, quarters: int = 20) -> Dict[str, Any]:
        """Fetch US real GDP levels and growth rates."""
        return await self._dispatch_market(
            "get_us_economic_growth",
            quarters=quarters,
        )

    async def get_us_inflation_employment(self, months: int = 24) -> Dict[str, Any]:
        """Fetch US inflation (CPI YoY) and unemployment rate."""
        return await self._dispatch_market(
            "get_us_inflation_employment",
            months=months,
        )

    async def get_us_interest_rates(self, days: int = 180) -> Dict[str, Any]:
        """Fetch US 2Y/10Y/Fed Funds rates and curve spread."""
        return await self._dispatch_market(
            "get_us_interest_rates",
            days=days,
        )

    # =========================================================================
    # Market-wide operations — each is a 2-liner via _dispatch_market
    # =========================================================================

    async def get_north_bound_flow(self, days: int = 30) -> Dict[str, Any]:
        # North-bound data is China-specific; prefer Tushare
        if DataSource.TUSHARE in self.adapters:
            try:
                return await self.adapters[DataSource.TUSHARE].get_north_bound_flow(
                    days
                )
            except Exception as e:
                logger.warning(f"Tushare failed for north_bound_flow: {e}")
        return await self._dispatch_market("get_north_bound_flow", days=days)

    async def get_money_supply(self, months: int = 60) -> Dict[str, Any]:
        return await self._dispatch_market("get_money_supply", months=months)

    async def get_inflation_data(self, months: int = 60) -> Dict[str, Any]:
        return await self._dispatch_market("get_inflation_data", months=months)

    async def get_pmi_data(self, months: int = 60) -> Dict[str, Any]:
        return await self._dispatch_market("get_pmi_data", months=months)

    async def get_gdp_data(self, quarters: int = 20) -> Dict[str, Any]:
        return await self._dispatch_market("get_gdp_data", quarters=quarters)

    async def get_social_financing(self, months: int = 60) -> Dict[str, Any]:
        return await self._dispatch_market("get_social_financing", months=months)

    async def get_interest_rates(
        self, shibor_days: int = 252, lpr_months: int = 60
    ) -> Dict[str, Any]:
        return await self._dispatch_market(
            "get_interest_rates", shibor_days=shibor_days, lpr_months=lpr_months
        )

    async def get_market_liquidity(self, days: int = 60) -> Dict[str, Any]:
        return await self._dispatch_market("get_market_liquidity", days=days)

    async def get_market_money_flow(
        self,
        trade_date: Optional[str] = None,
        top_n: int = 20,
        include_outflow: bool = True,
    ) -> Dict[str, Any]:
        return await self._dispatch_market(
            "get_market_money_flow",
            trade_date=trade_date,
            top_n=top_n,
            include_outflow=include_outflow,
        )

    async def get_sector_trend(
        self,
        sector_name: str = "",
        days: int = 10,
        sector_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._dispatch_market(
            "get_sector_trend",
            sector_name=sector_name,
            days=days,
            sector_id=sector_id,
        )

    async def resolve_sector(
        self, query_text: str, intent: str = "trend"
    ) -> Dict[str, Any]:
        """Resolve sector with cross-adapter fallback.

        Prefer first adapter that returns:
        - resolved
        - ambiguous
        If an adapter returns not_found, continue trying the next adapter.
        """
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
            except NotImplementedError:
                continue
            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"timeout after {self._provider_timeout_seconds}s"
                )
                logger.warning(
                    f"{adapter.source.value}.resolve_sector() timeout in "
                    f"{self._provider_timeout_seconds}s"
                )
            except Exception as e:
                last_error = e
                logger.warning(f"{adapter.source.value}.resolve_sector() failed: {e}")

        if last_not_found is not None:
            return last_not_found
        raise ValueError(f"No adapter supports resolve_sector: {last_error}")

    async def get_sector_money_flow_history(
        self,
        sector_name: str = "",
        days: int = 20,
        sector_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._dispatch_market(
            "get_sector_money_flow_history",
            sector_name=sector_name,
            days=days,
            sector_id=sector_id,
        )

    async def get_sector_valuation_metrics(
        self,
        sector_name: str = "",
        days: int = 250,
        sample_size: int = 60,
        sector_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return await self._dispatch_market(
            "get_sector_valuation_metrics",
            sector_name=sector_name,
            days=days,
            sample_size=sample_size,
            sector_id=sector_id,
        )

    async def get_ggt_daily(self, days: int = 60) -> Dict[str, Any]:
        return await self._dispatch_market("get_ggt_daily", days=days)

    # =========================================================================
    # Monitoring helper methods
    # =========================================================================

    def _log_to_monitoring(
        self,
        data_type: str,
        source: str,
        instrument_id: str,
        status: str,
        latency_ms: float,
        error_message: Optional[str] = None,
        has_data: bool = False,
        fields_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """非阻塞记录监控日志到 Redis"""
        monitoring = self._get_monitoring()
        if monitoring is None:
            return

        try:
            log = RequestLog(
                timestamp=datetime.now().isoformat(),
                data_type=data_type,
                instrument_id=instrument_id,
                source=source,
                status=status,
                latency_ms=latency_ms,
                error_message=error_message,
                fields_count=fields_count,
                has_data=has_data,
                metadata=metadata or {},
            )
            monitoring.log_request(log)
        except Exception as e:
            logger.warning(f"Failed to log monitoring: {e}")

    def _check_and_alert(
        self,
        source: str,
        data_type: str,
        status: str,
        latency_ms: float,
    ) -> None:
        """检查是否需要告警（带限流）"""
        monitoring = self._get_monitoring()
        if monitoring is None:
            return

        def should_alert(alert_type: str) -> bool:
            """检查是否应该发送告警（限流检查）"""
            key = f"{source}:{data_type}:{alert_type}"
            now = time.time()
            last_alert = self._alert_throttle.get(key, 0)
            if now - last_alert < self._alert_throttle_ttl:
                return False
            self._alert_throttle[key] = now
            return True

        try:
            # 延迟告警
            if latency_ms > 10000 and should_alert("latency_critical"):  # > 10s
                monitoring.create_alert(Alert(
                    source=source,
                    severity=AlertSeverity.CRITICAL.value,
                    message=f"数据源 {source} 延迟过高: {latency_ms:.0f}ms ({data_type})",
                ))
            elif latency_ms > 5000 and should_alert("latency_warning"):  # > 5s
                monitoring.create_alert(Alert(
                    source=source,
                    severity=AlertSeverity.WARNING.value,
                    message=f"数据源 {source} 延迟较高: {latency_ms:.0f}ms ({data_type})",
                ))

            # 失败告警
            if status == RequestStatus.TIMEOUT.value and should_alert("timeout"):
                monitoring.create_alert(Alert(
                    source=source,
                    severity=AlertSeverity.WARNING.value,
                    message=f"数据源 {source} 请求超时 ({data_type})",
                ))
            elif status == RequestStatus.FAILED.value and should_alert("failed"):
                monitoring.create_alert(Alert(
                    source=source,
                    severity=AlertSeverity.WARNING.value,
                    message=f"数据源 {source} 请求失败 ({data_type})",
                ))
        except Exception as e:
            logger.warning(f"Failed to create alert: {e}")

    def _extract_result_info(self, result: Any) -> Tuple[bool, int]:
        """从结果中提取是否有数据和字段数"""
        if result is None:
            return False, 0

        if isinstance(result, dict):
            has_data = any(v is not None and v != "" for v in result.values())
            fields_count = len(result)
            return has_data, fields_count

        if isinstance(result, list):
            return len(result) > 0, len(result)

        if isinstance(result, AssetPrice):
            return True, len(result.to_dict())

        if isinstance(result, Asset):
            return True, 1

        return True, 1

    def _extract_market_instrument_id(self, method: str, kwargs: Dict[str, Any]) -> str:
        """从 market 方法参数中提取 instrument_id"""
        # 尝试常见的参数名
        for key in ["sector_name", "sector_id", "index_code", "market", "query_text"]:
            if key in kwargs and kwargs[key]:
                return str(kwargs[key])
        return method


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_adapter_manager_instance: Optional["AdapterManager"] = None
_adapter_manager_lock = threading.Lock()


def get_adapter_manager() -> AdapterManager:
    global _adapter_manager_instance
    if _adapter_manager_instance is None:
        with _adapter_manager_lock:
            if _adapter_manager_instance is None:
                _adapter_manager_instance = AdapterManager()
    return _adapter_manager_instance
