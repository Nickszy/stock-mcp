# src/server/domain/adapters/yahoo_adapter.py
"""YahooFinance adapter using yfinance.

All methods are async via asyncio.run_in_executor to avoid blocking.
"""

import asyncio
import logging
import math
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

import pandas as pd
import yfinance as yf

from src.server.domain.adapters.base import BaseDataAdapter
from src.server.domain.types import (
    AdapterCapability,
    Asset,
    AssetPrice,
    AssetType,
    DataSource,
    Exchange,
    MarketInfo,
    MarketStatus,
)
from src.server.utils.logger import logger


def _to_decimal_price(value: Optional[float]) -> Optional[Decimal]:
    """Convert price fields to Decimal with 2 decimal places.

    Used for: price, open, high, low, close, change
    """
    if value is None:
        return None
    rounded = round(value, 2)
    return Decimal(str(rounded))


def _to_decimal_percent(value: Optional[float]) -> Optional[Decimal]:
    """Convert percentage fields to Decimal with 2 decimal places.

    Used for: change_percent
    """
    if value is None:
        return None
    rounded = round(value, 2)
    return Decimal(str(rounded))


def _to_decimal_volume(value: Optional[float]) -> Optional[Decimal]:
    """Convert volume to Decimal as integer.

    Volume should always be a whole number.
    """
    if value is None:
        return None
    return Decimal(str(int(round(value))))


def _to_decimal_market_cap(value: Optional[float]) -> Optional[Decimal]:
    """Convert market cap to Decimal as integer.

    Market cap should always be a whole number.
    """
    if value is None:
        return None
    return Decimal(str(int(round(value))))


class YahooAdapter(BaseDataAdapter):
    name = "yahoo"

    def __init__(self, cache, proxy_url: str = None):
        super().__init__(DataSource.YAHOO)
        self.cache = cache
        self.logger = logger
        self.proxy_url = proxy_url

        # Configure proxy
        # yfinance 1.0+ uses curl_cffi which requires proxy as dict format
        if self.proxy_url:
            try:
                proxy_dict = {
                    "http": self.proxy_url,
                    "https": self.proxy_url,
                }
                yf.config.network.proxy = proxy_dict
                self.logger.info(
                    f"✅ Yahoo adapter configured with proxy (yf.config.network.proxy): {self.proxy_url}"
                )
            except Exception as e:
                self.logger.warning(
                    f"⚠️  Failed to set proxy via yf.config: {e}, continue without global env proxy mutation"
                )
        else:
            self.logger.info("ℹ️  Yahoo adapter running without proxy")

    def get_capabilities(self) -> List[AdapterCapability]:
        """Declare Yahoo Finance's capabilities."""
        return [
            AdapterCapability(
                asset_type=AssetType.STOCK,
                exchanges={
                    Exchange.NASDAQ,
                    Exchange.NYSE,
                    Exchange.AMEX,
                    Exchange.HKEX,
                },
            ),
            AdapterCapability(
                asset_type=AssetType.ETF, exchanges={Exchange.NASDAQ, Exchange.NYSE}
            ),
            AdapterCapability(
                asset_type=AssetType.INDEX, exchanges={Exchange.NASDAQ, Exchange.NYSE}
            ),
            AdapterCapability(asset_type=AssetType.CRYPTO, exchanges={Exchange.CRYPTO}),
            AdapterCapability(asset_type=AssetType.FX, exchanges={Exchange.FOREX}),
            AdapterCapability(
                asset_type=AssetType.COMMODITY_SPOT, exchanges={Exchange.OTC}
            ),
            AdapterCapability(
                asset_type=AssetType.COMMODITY_FUTURE,
                exchanges={Exchange.COMEX, Exchange.NYMEX, Exchange.CME, Exchange.ICE},
            ),
        ]

    def get_supported_asset_types(self) -> List[AssetType]:
        """Get list of supported asset types."""
        return [
            AssetType.STOCK,
            AssetType.ETF,
            AssetType.INDEX,
            AssetType.FX,
            AssetType.COMMODITY_SPOT,
            AssetType.COMMODITY_FUTURE,
            AssetType.CRYPTO,
        ]

    def convert_to_source_ticker(self, ticker: str) -> str:
        """Convert internal ticker to Yahoo Finance format.

        Internal format: EXCHANGE:SYMBOL
        Yahoo format: SYMBOL.EXCHANGE_SUFFIX
        """
        if ":" not in ticker:
            return ticker

        exchange, symbol = ticker.split(":", 1)

        # Handle Crypto
        if exchange == "CRYPTO":
            # Convert BTC/USDT -> BTC-USD
            if "/" in symbol:
                base, quote = symbol.split("/")
                # Yahoo uses USD for most crypto pairs
                if quote in ["USDT", "USDC", "USD"]:
                    return f"{base}-USD"
                return f"{base}-{quote}"
            return f"{symbol}-USD"

        # Handle FX (Yahoo: EURUSD=X)
        if exchange == "FOREX":
            return f"{symbol}=X"

        # Handle commodity spot (Yahoo: XAUUSD=X, XAGUSD=X)
        if exchange == "OTC":
            return f"{symbol}=X"

        # Handle commodity futures (Yahoo: GC=F, SI=F, CL=F)
        if exchange in ["COMEX", "NYMEX", "CME", "ICE"]:
            if symbol.endswith("=F"):
                return symbol
            return f"{symbol}=F"

        # Handle US stocks (no suffix)
        if exchange in ["NASDAQ", "NYSE", "AMEX", "US"]:
            return symbol

        # Handle HK stocks
        if exchange == "HKEX":
            return f"{symbol}.HK"

        # Handle A-shares
        if exchange == "SSE":  # Shanghai
            return f"{symbol}.SS"

        elif exchange == "SZSE":
            return f"{symbol}.SZ"

        elif exchange == "CRYPTO":
            return f"{symbol}-USD"

        elif exchange in ["NASDAQ", "NYSE", "AMEX"]:
            return symbol

        else:
            return symbol

    def convert_to_internal_ticker(
        self, source_ticker: str, default_exchange: Optional[str] = None
    ) -> str:
        """Convert Yahoo Finance format to EXCHANGE:SYMBOL."""
        # FX and commodity spot symbols: EURUSD=X, XAUUSD=X
        if source_ticker.endswith("=X"):
            core = source_ticker.replace("=X", "").upper()
            if core in {"XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"}:
                return f"OTC:{core}"
            if len(core) == 6 and core.isalpha():
                return f"FOREX:{core}"
            return f"OTC:{core}"

        # Commodity futures: GC=F, SI=F
        if source_ticker.endswith("=F"):
            core = source_ticker.replace("=F", "").upper()
            comex = {"GC", "SI", "HG"}
            nymex = {"CL", "NG"}
            if core in comex:
                return f"COMEX:{core}"
            if core in nymex:
                return f"NYMEX:{core}"
            return f"CME:{core}"

        # Special handling for indices from yfinance - remove ^ prefix
        if source_ticker.startswith("^"):
            symbol = source_ticker[1:]  # Remove ^ prefix
            if default_exchange:
                return f"{default_exchange}:{symbol}"
            return f"UNKNOWN:{symbol}"

        # Special handling for crypto from yfinance - remove currency suffix
        if "-USD" in source_ticker:
            crypto_symbol = source_ticker.split("-")[0].upper()
            return f"CRYPTO:{crypto_symbol}"

        # Special handling for Hong Kong stocks from yfinance
        if ".HK" in source_ticker:
            symbol = source_ticker.replace(".HK", "")
            if symbol.isdigit():
                symbol = symbol.zfill(5)
            return f"HKEX:{symbol}"

        # Special handling for Shanghai stocks from yfinance
        if ".SS" in source_ticker:
            symbol = source_ticker.replace(".SS", "")
            return f"SSE:{symbol}"

        # Special handling for Shenzhen stocks from yfinance
        if ".SZ" in source_ticker:
            symbol = source_ticker.replace(".SZ", "")
            return f"SZSE:{symbol}"

        if default_exchange:
            return f"{default_exchange}:{source_ticker}"

        # Default to NASDAQ if no exchange info
        return f"NASDAQ:{source_ticker}"

    async def _run(self, func, *args, **kwargs):
        loop = asyncio.get_event_loop()
        max_retries = 3
        base_delay = 1

        for attempt in range(max_retries):
            try:
                return await loop.run_in_executor(None, lambda: func(*args, **kwargs))
            except Exception as e:
                error_msg = str(e).lower()
                if (
                    "too many requests" in error_msg
                    or "429" in error_msg
                    or "rate limited" in error_msg
                ):
                    if attempt == max_retries - 1:
                        raise e

                    delay = base_delay * (2**attempt) + (
                        0.1 * (asyncio.get_event_loop().time() % 1)
                    )
                    self.logger.warning(
                        f"Rate limited (attempt {attempt + 1}/{max_retries}), retrying in {delay:.2f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise e

    def _to_yf_ticker(self, ticker: str) -> str:
        return self.convert_to_source_ticker(ticker)

    async def get_asset_info(self, ticker: str) -> Optional[Asset]:
        """Fetch detailed asset information."""
        ticker_norm = self._to_yf_ticker(ticker)
        cache_key = f"yahoo:info:{ticker_norm}"
        cached = await self.cache.get(cache_key)
        if cached:
            return Asset.model_validate(cached)

        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)
            info = await self._run(lambda: ticker_obj.info)

            # yfinance 1.0 may return string or None instead of dict
            if not info or not isinstance(info, dict):
                self.logger.warning(f"Invalid info type for {ticker}: {type(info)}")
                return None

            if "symbol" not in info:
                self.logger.warning(f"No symbol in info for {ticker}")
                return None

            # Map Yahoo info to Asset model
            exchange_map = {
                "NMS": "NASDAQ",
                "NYQ": "NYSE",
                "ASE": "AMEX",
                "HKG": "HKEX",
            }
            yf_exchange = info.get("exchange", "")
            exchange = exchange_map.get(yf_exchange, yf_exchange)

            asset_type = AssetType.STOCK
            if ":" in ticker:
                exchange = ticker.split(":", 1)[0]
                if exchange == "FOREX":
                    asset_type = AssetType.FX
                elif exchange == "OTC":
                    asset_type = AssetType.COMMODITY_SPOT
                elif exchange in {"COMEX", "NYMEX", "CME", "ICE"}:
                    asset_type = AssetType.COMMODITY_FUTURE

            asset = Asset(
                ticker=ticker,
                asset_type=asset_type,
                name=info.get("longName") or info.get("shortName") or ticker,
                market_info=MarketInfo(
                    exchange=exchange,
                    country=info.get("country", "US"),
                    currency=info.get("currency", "USD"),
                    timezone=info.get("timeZoneShortName", "UTC"),
                    market_status=MarketStatus.UNKNOWN,
                ),
                source_mappings={DataSource.YAHOO: ticker_norm},
                properties={
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "website": info.get("website"),
                    "description": info.get("longBusinessSummary"),
                },
            )

            await self.cache.set(cache_key, asset.model_dump(), ttl=3600)
            return asset
        except Exception as e:
            self.logger.warning(f"Failed to fetch asset info for {ticker}: {e}")
            return None

    async def get_real_time_price(self, ticker: str) -> Optional[AssetPrice]:
        """Fetch current price."""
        ticker_norm = self._to_yf_ticker(ticker)
        cache_key = f"yahoo:price:{ticker_norm}"
        cached = await self.cache.get(cache_key)
        if cached:
            # Reconstruct AssetPrice from cached dict
            return AssetPrice.from_dict(cached)

        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)

            # Try fast_info first (more stable in yfinance 1.0)
            price = None
            currency = "USD"
            volume = 0
            open_price = None
            high_price = None
            low_price = None
            close_price = None
            market_cap = None

            try:
                fast_info = await self._run(lambda: ticker_obj.fast_info)
                if fast_info:
                    price = getattr(fast_info, "last_price", None)
                    currency = getattr(fast_info, "currency", "USD") or "USD"
                    volume = getattr(fast_info, "last_volume", 0) or 0
                    open_price = getattr(fast_info, "open", None)
                    high_price = getattr(fast_info, "day_high", None)
                    low_price = getattr(fast_info, "day_low", None)
                    close_price = getattr(fast_info, "previous_close", None)
                    market_cap = getattr(fast_info, "market_cap", None)
            except Exception as fast_info_error:
                self.logger.debug(
                    f"fast_info failed for {ticker}, trying info: {fast_info_error}"
                )

            # Fallback to info if fast_info didn't get price
            if price is None:
                info = await self._run(lambda: ticker_obj.info)

                # yfinance 1.0 may return string or None instead of dict
                if info and isinstance(info, dict):
                    price = (
                        info.get("currentPrice")
                        or info.get("regularMarketPrice")
                        or info.get("ask")
                    )
                    if price is not None:
                        currency = info.get("currency", "USD") or "USD"
                        volume = info.get("volume", 0) or 0
                        open_price = info.get("open")
                        high_price = info.get("dayHigh")
                        low_price = info.get("dayLow")
                        close_price = info.get("previousClose")
                        market_cap = info.get("marketCap")

            if price is None:
                self.logger.warning(f"No price available for {ticker}")
                return None

            asset_price = AssetPrice(
                ticker=ticker,
                price=_to_decimal_price(price),
                currency=currency,
                timestamp=datetime.utcnow(),
                volume=_to_decimal_volume(volume),
                open_price=_to_decimal_price(open_price),
                high_price=_to_decimal_price(high_price),
                low_price=_to_decimal_price(low_price),
                close_price=_to_decimal_price(close_price),
                change=None,  # Calculate if needed
                change_percent=None,
                market_cap=_to_decimal_market_cap(market_cap),
                source=DataSource.YAHOO,
            )

            # Calculate change if possible
            if asset_price.close_price and asset_price.price:
                asset_price.change = asset_price.price - asset_price.close_price
                # Calculate percentage and round to 2 decimal places
                change_pct_decimal = (asset_price.change / asset_price.close_price) * 100
                asset_price.change_percent = _to_decimal_percent(float(change_pct_decimal))

            # Cache as dict
            await self.cache.set(cache_key, asset_price.to_dict(), ttl=60)
            return asset_price

        except Exception as e:
            self.logger.warning(f"Failed to fetch price for {ticker}: {e}")
            return None

    async def get_historical_prices(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        interval: str = "1d",
    ) -> List[AssetPrice]:
        """Fetch historical prices."""
        ticker_norm = self._to_yf_ticker(ticker)
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        cache_key = f"yahoo:history:{ticker_norm}:{start_str}:{end_str}:{interval}"
        cached = await self.cache.get(cache_key)
        if cached:
            return [AssetPrice.from_dict(item) for item in cached]

        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)
            hist = await self._run(
                ticker_obj.history, start=start_str, end=end_str, interval=interval
            )

            # yfinance 1.0 may return None
            if hist is None:
                self.logger.warning(f"history() returned None for {ticker}")
                return []

            if hist.empty:
                return []

            # Get currency from fast_info or info
            currency = "USD"
            try:
                fast_info = await self._run(lambda: ticker_obj.fast_info)
                if fast_info:
                    currency = getattr(fast_info, 'currency', 'USD') or 'USD'
            except Exception:
                pass

            prices = []
            for idx, row in hist.iterrows():
                # idx is Timestamp
                timestamp = idx.to_pydatetime()

                price = AssetPrice(
                    ticker=ticker,
                    price=_to_decimal_price(row["Close"]),
                    currency=currency,
                    timestamp=timestamp,
                    volume=_to_decimal_volume(row["Volume"]),
                    open_price=_to_decimal_price(row["Open"]),
                    high_price=_to_decimal_price(row["High"]),
                    low_price=_to_decimal_price(row["Low"]),
                    close_price=_to_decimal_price(row["Close"]),
                    source=DataSource.YAHOO,
                )
                prices.append(price)

            # Cache list of dicts
            await self.cache.set(cache_key, [p.to_dict() for p in prices], ttl=3600)
            return prices

        except Exception as e:
            self.logger.error(f"Failed to fetch history for {ticker}: {e}")
            return []

    async def get_financials(self, ticker: str) -> Dict[str, Any]:
        """Fetch financial statements."""
        # Keep existing implementation but ensure it works with new base class
        # ... (Same implementation as before, just copied over)
        cache_key = f"yahoo:financials:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)

        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)

            def fetch_financial_data():
                balance_sheet = ticker_obj.balance_sheet
                income_statement = ticker_obj.financials
                cash_flow = ticker_obj.cashflow
                info = ticker_obj.info
                return balance_sheet, income_statement, cash_flow, info

            balance_sheet, income_statement, cash_flow, info = await self._run(
                fetch_financial_data
            )

            company_info = {
                "公司名称": info.get("longName", info.get("shortName", "")),
                "股票代码": ticker_norm,
                "行业": info.get("industry", ""),
                "板块": info.get("sector", ""),
                "国家": info.get("country", ""),
                "网站": info.get("website", ""),
                "总市值": info.get("marketCap", 0),
                "员工人数": info.get("fullTimeEmployees", 0),
                "公司简介": info.get("longBusinessSummary", "")[:200],
            }

            # Convert DataFrames to JSON-serializable format
            def df_to_serializable(df):
                if df.empty:
                    return {}
                # Reset index to convert Timestamp index to column
                df_reset = df.reset_index()
                # Convert to dict with orient='records'
                return df_reset.to_dict(orient="records")

            # Clean function to handle Timestamp and other non-serializable objects
            def clean_for_json(obj):
                """Recursively clean object for JSON serialization."""
                import math
                from datetime import datetime

                if isinstance(obj, dict):
                    return {str(k): clean_for_json(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [clean_for_json(item) for item in obj]
                elif isinstance(obj, (pd.Timestamp, datetime)):
                    return obj.isoformat() if hasattr(obj, "isoformat") else str(obj)
                elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                    return None
                elif isinstance(obj, (int, float, str, bool, type(None))):
                    return obj
                else:
                    return str(obj)

            result = {
                "balance_sheet": clean_for_json(df_to_serializable(balance_sheet)),
                "income_statement": clean_for_json(
                    df_to_serializable(income_statement)
                ),
                "cash_flow": clean_for_json(df_to_serializable(cash_flow)),
                "financial_indicators": None,
                "company_info": company_info,
                "_raw_info": clean_for_json(info),
            }

            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to fetch financials for {ticker}: {e}")
            raise ValueError(f"Failed to fetch financials for {ticker}: {e}")

    async def get_financial_statements(
        self,
        ticker: str,
        report_type: str = "all",
        periods: int | None = None,
    ) -> Dict[str, Any]:
        """Fetch complete financial statements with YoY/QoQ calculations.

        Unified interface matching TushareAdapter for overseas stocks.

        Args:
            ticker: Asset ticker in internal format (e.g., NASDAQ:AAPL)
            report_type: "quarterly" | "annual" | "all" (default: "all")
            periods: Number of periods to return. None = all available history.

        Returns:
            Dictionary containing:
            - income_statement: {quarterly: [...], annual: [...]}
            - balance_sheet: {quarterly: [...], annual: [...]}
            - cash_flow: {quarterly: [...], annual: [...]}
            - Each record includes YoY (同比) and QoQ (环比) for key metrics
        """
        cache_key = f"yahoo:financial_statements:{ticker}:{report_type}:{periods}:v1"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)

        # Core fields for YoY/QoQ calculation
        income_yoy_fields = [
            "Total Revenue", "Operating Income", "Net Income",
            "Basic EPS", "Diluted EPS"
        ]
        balance_yoy_fields = [
            "Total Assets", "Total Liabilities Net Minority Interest",
            "Stockholders Equity"
        ]
        cashflow_yoy_fields = [
            "Operating Cash Flow", "Investing Cash Flow",
            "Financing Cash Flow", "Free Cash Flow"
        ]

        try:
            def fetch_all_financials():
                # Create ticker and fetch all data in one executor call
                ticker_obj = yf.Ticker(ticker_norm)

                # Annual data
                income_annual = ticker_obj.income_stmt
                balance_annual = ticker_obj.balance_sheet
                cashflow_annual = ticker_obj.cash_flow

                # Quarterly data
                income_quarterly = ticker_obj.quarterly_income_stmt
                balance_quarterly = ticker_obj.quarterly_balance_sheet
                cashflow_quarterly = ticker_obj.quarterly_cash_flow

                return (
                    income_annual, balance_annual, cashflow_annual,
                    income_quarterly, balance_quarterly, cashflow_quarterly
                )

            results = await self._run(fetch_all_financials)
            (
                income_annual, balance_annual, cashflow_annual,
                income_quarterly, balance_quarterly, cashflow_quarterly
            ) = results

            def process_statement(df, yoy_fields, is_quarterly=False):
                """Process DataFrame: add YoY/QoQ calculations."""
                if df is None or df.empty:
                    return []

                # Transpose: dates as rows, metrics as columns
                # yfinance format: rows=metrics, columns=dates
                df_t = df.T.reset_index()
                # Rename first column to end_date
                df_t = df_t.rename(columns={'index': 'end_date'})

                # Sort by date ascending for YoY calculation
                df_t = df_t.sort_values("end_date", ascending=True)

                # Calculate YoY and QoQ
                df_t = self._add_yoy_qoq_yahoo(df_t, yoy_fields, is_quarterly)

                # Sort descending (newest first)
                df_t = df_t.sort_values("end_date", ascending=False)

                if periods is not None:
                    df_t = df_t.head(periods)

                return clean_for_json(df_t.to_dict("records"))

            def clean_for_json(obj):
                """Recursively clean object for JSON serialization."""
                import math
                from datetime import datetime

                if isinstance(obj, dict):
                    return {str(k): clean_for_json(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [clean_for_json(item) for item in obj]
                elif isinstance(obj, (pd.Timestamp, datetime)):
                    return obj.strftime("%Y-%m-%d") if hasattr(obj, "strftime") else str(obj)
                elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                    return None
                elif isinstance(obj, (int, float, str, bool, type(None))):
                    return obj
                else:
                    return str(obj)

            result = {
                "ticker": ticker_norm,
                "source": "yahoo",
                "income_statement": {
                    "quarterly": process_statement(income_quarterly, income_yoy_fields, is_quarterly=True) if report_type in ("all", "quarterly") else [],
                    "annual": process_statement(income_annual, income_yoy_fields, is_quarterly=False) if report_type in ("all", "annual") else [],
                },
                "balance_sheet": {
                    "quarterly": process_statement(balance_quarterly, balance_yoy_fields, is_quarterly=True) if report_type in ("all", "quarterly") else [],
                    "annual": process_statement(balance_annual, balance_yoy_fields, is_quarterly=False) if report_type in ("all", "annual") else [],
                },
                "cash_flow": {
                    "quarterly": process_statement(cashflow_quarterly, cashflow_yoy_fields, is_quarterly=True) if report_type in ("all", "quarterly") else [],
                    "annual": process_statement(cashflow_annual, cashflow_yoy_fields, is_quarterly=False) if report_type in ("all", "annual") else [],
                },
            }

            await self.cache.set(cache_key, result, ttl=3600)
            return result

        except Exception as e:
            self.logger.error(f"Failed to fetch financial statements for {ticker}: {e}")
            raise ValueError(f"Failed to fetch financial statements for {ticker}: {e}")

    def _add_yoy_qoq_yahoo(self, df: pd.DataFrame, yoy_fields: list, is_quarterly: bool) -> pd.DataFrame:
        """Add YoY and QoQ calculations for Yahoo Finance data."""
        df = df.copy()

        # Extract year and quarter for alignment
        if "end_date" in df.columns:
            df["_year"] = pd.to_datetime(df["end_date"]).dt.year
            df["_quarter"] = pd.to_datetime(df["end_date"]).dt.quarter

        for field in yoy_fields:
            if field not in df.columns:
                continue

            yoy_col = f"{field}_yoy"
            qoq_col = f"{field}_qoq"

            # Calculate YoY
            df[yoy_col] = None
            if "_year" in df.columns:
                for i in range(len(df)):
                    curr_year = df.iloc[i]["_year"]
                    curr_quarter = df.iloc[i]["_quarter"]
                    curr_val = df.iloc[i][field]

                    if curr_val is None or pd.isna(curr_val):
                        continue

                    # Find same quarter last year
                    last_year_mask = (df["_year"] == curr_year - 1) & (df["_quarter"] == curr_quarter)
                    last_year_rows = df[last_year_mask]

                    if len(last_year_rows) > 0:
                        last_year_val = last_year_rows.iloc[0][field]
                        if last_year_val is not None and not pd.isna(last_year_val) and last_year_val != 0:
                            df.iloc[i, df.columns.get_loc(yoy_col)] = round(
                                (curr_val - last_year_val) / abs(last_year_val) * 100, 2
                            )

            # Calculate QoQ (only for quarterly data)
            if is_quarterly:
                df[qoq_col] = None
                for i in range(1, len(df)):
                    curr_val = df.iloc[i][field]
                    prev_val = df.iloc[i - 1][field]

                    if curr_val is None or pd.isna(curr_val) or prev_val is None or pd.isna(prev_val):
                        continue

                    if prev_val != 0:
                        df.iloc[i, df.columns.get_loc(qoq_col)] = round(
                            (curr_val - prev_val) / abs(prev_val) * 100, 2
                        )

        # Clean up temp columns
        df = df.drop(columns=["_year", "_quarter"], errors="ignore")
        return df

    # =========================================================================
    # US-market specific implementations
    # =========================================================================

    async def get_earnings_history(
        self, ticker: str, quarters: int = 8
    ) -> Dict[str, Any]:
        """Fetch EPS history: estimate vs actual and surprise %."""
        t0 = time.perf_counter()
        cache_key = f"yahoo:earnings:{ticker}:{quarters}"
        cached = await self.cache.get(cache_key)
        if cached:
            self.logger.info(
                "yahoo.get_earnings_history cache hit",
                ticker=ticker,
                quarters=quarters,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        try:
            t_ticker = time.perf_counter()
            ticker_obj = await self._run(yf.Ticker, ticker_norm)
            t_fetch = time.perf_counter()

            def _fetch():
                return ticker_obj.earnings_history

            raw = await self._run(_fetch)
            t_parse = time.perf_counter()
            if raw is None or (hasattr(raw, "empty") and raw.empty):
                self.logger.warning(
                    "yahoo.get_earnings_history empty response",
                    ticker=ticker,
                    ticker_norm=ticker_norm,
                    build_ticker_ms=int((t_fetch - t_ticker) * 1000),
                    fetch_ms=int((t_parse - t_fetch) * 1000),
                    elapsed_ms=int((time.perf_counter() - t0) * 1000),
                )
                return {"ticker": ticker, "quarters": []}

            rows = []
            df = raw.reset_index() if hasattr(raw, "reset_index") else raw
            for _, row in df.iterrows():
                actual = row.get("epsActual") or row.get("Reported EPS")
                estimate = row.get("epsEstimate") or row.get("EPS Estimate")
                surprise = row.get("surprisePercent") or row.get("Surprise(%)")
                date_val = (
                    row.get("Earnings Date") or row.get("Quarter") or row.get("index")
                )
                rows.append(
                    {
                        "date": str(date_val)[:10] if date_val is not None else None,
                        "actual_eps": float(actual) if actual is not None else None,
                        "estimated_eps": (
                            float(estimate) if estimate is not None else None
                        ),
                        "surprise_pct": (
                            float(surprise) if surprise is not None else None
                        ),
                    }
                )
            rows = rows[-quarters:]
            result = {"ticker": ticker, "quarters": rows}
            await self.cache.set(cache_key, result, ttl=3600)
            self.logger.info(
                "yahoo.get_earnings_history success",
                ticker=ticker,
                ticker_norm=ticker_norm,
                quarters=quarters,
                rows=len(rows),
                build_ticker_ms=int((t_fetch - t_ticker) * 1000),
                fetch_ms=int((t_parse - t_fetch) * 1000),
                parse_cache_ms=int((time.perf_counter() - t_parse) * 1000),
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )
            return result
        except Exception as e:
            self.logger.error(
                f"get_earnings_history failed for {ticker}: {e}",
                ticker=ticker,
                ticker_norm=ticker_norm,
                quarters=quarters,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
            )
            raise ValueError(f"get_earnings_history failed for {ticker}: {e}")

    async def get_cash_flow_quality(self, ticker: str) -> Dict[str, Any]:
        """Fetch operating/free cash flow and FCF/net-income ratio."""
        cache_key = f"yahoo:cashflow:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)

            def _fetch():
                return ticker_obj.cashflow, ticker_obj.financials

            cf_df, inc_df = await self._run(_fetch)

            import math

            def _safe(val):
                if val is None:
                    return None
                try:
                    v = float(val)
                    return None if math.isnan(v) or math.isinf(v) else v
                except Exception:
                    return None

            annual = []
            if cf_df is not None and not cf_df.empty:
                for col in cf_df.columns:
                    year = str(col)[:4]
                    op_cf = _safe(
                        cf_df.loc["Operating Cash Flow", col]
                        if "Operating Cash Flow" in cf_df.index
                        else None
                    )
                    capex = _safe(
                        cf_df.loc["Capital Expenditure", col]
                        if "Capital Expenditure" in cf_df.index
                        else None
                    )
                    free_cf = (op_cf or 0) + (capex or 0) if op_cf is not None else None
                    net_inc = None
                    if (
                        inc_df is not None
                        and not inc_df.empty
                        and col in inc_df.columns
                    ):
                        net_inc = _safe(
                            inc_df.loc["Net Income", col]
                            if "Net Income" in inc_df.index
                            else None
                        )
                    fcf_ratio = (
                        (free_cf / net_inc)
                        if (free_cf is not None and net_inc and net_inc != 0)
                        else None
                    )
                    annual.append(
                        {
                            "year": year,
                            "operating_cf": op_cf,
                            "capex": capex,
                            "free_cf": free_cf,
                            "net_income": net_inc,
                            "fcf_ratio": (
                                round(fcf_ratio, 4) if fcf_ratio is not None else None
                            ),
                        }
                    )

            result = {"ticker": ticker, "annual": annual}
            await self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            self.logger.error(f"get_cash_flow_quality failed for {ticker}: {e}")
            raise ValueError(f"get_cash_flow_quality failed for {ticker}: {e}")

    async def get_us_valuation_metrics(self, ticker: str) -> Dict[str, Any]:
        """Fetch US stock valuation: PE/PS/PB/EV_EBITDA."""
        cache_key = f"yahoo:us_val:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)
            info = await self._run(lambda: ticker_obj.info)
            if not info or not isinstance(info, dict):
                raise ValueError(f"No info for {ticker}")

            import math

            def _safe(key):
                v = info.get(key)
                if v is None:
                    return None
                try:
                    f = float(v)
                    return None if math.isnan(f) or math.isinf(f) else f
                except Exception:
                    return None

            result = {
                "ticker": ticker,
                "pe_ttm": _safe("trailingPE"),
                "pe_forward": _safe("forwardPE"),
                "ps_ttm": _safe("priceToSalesTrailing12Months"),
                "pb": _safe("priceToBook"),
                "ev_ebitda": _safe("enterpriseToEbitda"),
                "peg_ratio": _safe("pegRatio"),
                "market_cap": _safe("marketCap"),
                "enterprise_value": _safe("enterpriseValue"),
                "beta": _safe("beta"),
                "dividend_yield": _safe("dividendYield"),
                "name": info.get("longName") or info.get("shortName", ""),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.error(f"get_us_valuation_metrics failed for {ticker}: {e}")
            raise ValueError(f"get_us_valuation_metrics failed for {ticker}: {e}")

    async def get_us_institutional_holdings(self, ticker: str) -> Dict[str, Any]:
        """Fetch top institutional holders and recent change."""
        cache_key = f"yahoo:institutions:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)

            def _fetch():
                return ticker_obj.institutional_holders, ticker_obj.major_holders

            inst_df, major_df = await self._run(_fetch)

            holders = []
            if inst_df is not None and not inst_df.empty:
                for _, row in inst_df.head(15).iterrows():
                    pct = row.get("pctHeld") or row.get("% Out")
                    shares = row.get("Shares") or row.get("shares")
                    change = row.get("Change") or row.get("change")
                    date_filed = row.get("Date Reported") or row.get("dateReported")
                    holders.append(
                        {
                            "name": str(row.get("Holder") or row.get("holder") or ""),
                            "pct_held": (
                                round(float(pct) * 100, 2) if pct is not None else None
                            ),
                            "shares": int(shares) if shares is not None else None,
                            "change_pct": (
                                round(float(change) * 100, 2)
                                if change is not None
                                else None
                            ),
                            "filing_date": (
                                str(date_filed)[:10] if date_filed is not None else None
                            ),
                        }
                    )

            major = {}
            if major_df is not None and not major_df.empty:
                for _, row in major_df.iterrows():
                    val = row.iloc[0] if len(row) > 0 else None
                    label = row.iloc[1] if len(row) > 1 else None
                    if label and val is not None:
                        major[str(label)] = str(val)

            result = {"ticker": ticker, "holders": holders, "major_holders": major}
            await self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            self.logger.error(f"get_us_institutional_holdings failed for {ticker}: {e}")
            raise ValueError(f"get_us_institutional_holdings failed for {ticker}: {e}")

    async def get_us_price_history(
        self, ticker: str, days: int = 60, interval: str = "1d"
    ) -> Dict[str, Any]:
        """Fetch OHLCV klines for a US stock."""
        from datetime import timedelta

        cache_key = f"yahoo:us_price_hist:{ticker}:{days}:{interval}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        end = datetime.utcnow()
        start = end - timedelta(days=days)
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)
            hist = await self._run(
                ticker_obj.history,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval=interval,
            )
            if hist is None or (hasattr(hist, "empty") and hist.empty):
                return {"ticker": ticker, "interval": interval, "bars": []}

            bars = []
            for idx, row in hist.iterrows():
                bars.append(
                    {
                        "date": str(idx)[:10],
                        "open": round(float(row["Open"]), 4),
                        "high": round(float(row["High"]), 4),
                        "low": round(float(row["Low"]), 4),
                        "close": round(float(row["Close"]), 4),
                        "volume": int(row["Volume"]),
                    }
                )
            result = {"ticker": ticker, "interval": interval, "bars": bars}
            await self.cache.set(cache_key, result, ttl=600)
            return result
        except Exception as e:
            self.logger.error(f"get_us_price_history failed for {ticker}: {e}")
            raise ValueError(f"get_us_price_history failed for {ticker}: {e}")

    async def get_us_volume_analysis(
        self, ticker: str, days: int = 30
    ) -> Dict[str, Any]:
        """Fetch volume metrics: avg volume, relative volume, OBV trend."""
        from datetime import timedelta

        cache_key = f"yahoo:us_vol:{ticker}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        end = datetime.utcnow()
        start = end - timedelta(days=max(days + 20, 60))  # extra days for avg
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)
            hist = await self._run(
                ticker_obj.history,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1d",
            )
            if hist is None or (hasattr(hist, "empty") and hist.empty):
                return {"ticker": ticker, "bars": []}

            vols = hist["Volume"].values
            avg_vol_20 = (
                float(vols[-20:].mean()) if len(vols) >= 20 else float(vols.mean())
            )
            current_vol = float(vols[-1]) if len(vols) > 0 else 0.0
            rvol = current_vol / avg_vol_20 if avg_vol_20 > 0 else None

            # OBV
            obv = 0.0
            obv_series = []
            closes = hist["Close"].values
            for i in range(1, len(vols)):
                if closes[i] > closes[i - 1]:
                    obv += vols[i]
                elif closes[i] < closes[i - 1]:
                    obv -= vols[i]
                obv_series.append(obv)
            obv_trend = (
                "up"
                if (len(obv_series) >= 5 and obv_series[-1] > obv_series[-5])
                else "down" if len(obv_series) >= 5 else "flat"
            )

            bars = []
            hist_tail = hist.tail(days)
            avg_20_rolling = (
                float(hist["Volume"].rolling(20).mean().iloc[-1])
                if len(hist) >= 20
                else avg_vol_20
            )
            for idx, row in hist_tail.iterrows():
                v = float(row["Volume"])
                bars.append(
                    {
                        "date": str(idx)[:10],
                        "volume": int(v),
                        "rvol": (
                            round(v / avg_20_rolling, 2) if avg_20_rolling > 0 else None
                        ),
                    }
                )

            result = {
                "ticker": ticker,
                "avg_volume_20d": round(avg_vol_20, 0),
                "current_volume": round(current_vol, 0),
                "rvol": round(rvol, 2) if rvol is not None else None,
                "obv_trend": obv_trend,
                "bars": bars,
            }
            await self.cache.set(cache_key, result, ttl=600)
            return result
        except Exception as e:
            self.logger.error(f"get_us_volume_analysis failed for {ticker}: {e}")
            raise ValueError(f"get_us_volume_analysis failed for {ticker}: {e}")

    async def get_us_sector_etf_analysis(
        self, sector_name: str, days: int = 30
    ) -> Dict[str, Any]:
        """Fetch US sector ETF klines by sector name."""
        from datetime import timedelta

        # Sector → ETF ticker mapping
        SECTOR_ETF_MAP: Dict[str, str] = {
            "technology": "XLK",
            "tech": "XLK",
            "科技": "XLK",
            "financials": "XLF",
            "finance": "XLF",
            "金融": "XLF",
            "healthcare": "XLV",
            "health": "XLV",
            "医疗": "XLV",
            "医疗保健": "XLV",
            "energy": "XLE",
            "能源": "XLE",
            "consumer discretionary": "XLY",
            "consumer staples": "XLP",
            "consumer": "XLY",
            "消费": "XLY",
            "日常消费": "XLP",
            "utilities": "XLU",
            "公用事业": "XLU",
            "industrials": "XLI",
            "industrial": "XLI",
            "工业": "XLI",
            "materials": "XLB",
            "材料": "XLB",
            "real estate": "XLRE",
            "realestate": "XLRE",
            "房地产": "XLRE",
            "communication": "XLC",
            "communications": "XLC",
            "通信": "XLC",
            "semiconductor": "SOXX",
            "semiconductors": "SOXX",
            "半导体": "SOXX",
            "biotech": "XBI",
            "biotechnology": "XBI",
            "生物技术": "XBI",
            "software": "IGV",
            "软件": "IGV",
            "cloud": "SKYY",
            "云计算": "SKYY",
            "ev": "DRIV",
            "electric vehicle": "DRIV",
            "新能源车": "DRIV",
            "cybersecurity": "HACK",
            "网络安全": "HACK",
            "ai": "AIQ",
            "人工智能": "AIQ",
        }

        key = sector_name.strip().lower()
        etf_ticker = SECTOR_ETF_MAP.get(key)
        if not etf_ticker:
            # Fuzzy: try partial match
            for k, v in SECTOR_ETF_MAP.items():
                if k in key or key in k:
                    etf_ticker = v
                    break
        if not etf_ticker:
            etf_ticker = "SPY"  # fallback to S&P500

        cache_key = f"yahoo:sector_etf:{etf_ticker}:{days}"
        cached = await self.cache.get(cache_key)
        if cached:
            cached["sector_name"] = sector_name
            return cached

        end = datetime.utcnow()
        start = end - timedelta(days=days + 5)
        try:
            ticker_obj = await self._run(yf.Ticker, etf_ticker)
            hist = await self._run(
                ticker_obj.history,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                interval="1d",
            )
            if hist is None or (hasattr(hist, "empty") and hist.empty):
                return {
                    "sector_name": sector_name,
                    "etf_ticker": etf_ticker,
                    "bars": [],
                    "trend_summary": "no data",
                }

            bars = []
            closes = []
            for idx, row in hist.tail(days).iterrows():
                c = float(row["Close"])
                closes.append(c)
                bars.append(
                    {"date": str(idx)[:10], "close": round(c, 4), "change_pct": None}
                )

            # Fill change_pct
            for i in range(1, len(bars)):
                prev = closes[i - 1]
                if prev > 0:
                    bars[i]["change_pct"] = round((closes[i] - prev) / prev * 100, 2)

            total_chg = (
                ((closes[-1] - closes[0]) / closes[0] * 100) if closes[0] > 0 else 0
            )
            trend_summary = f"{etf_ticker} {days}d return: {total_chg:+.2f}%"

            result = {
                "sector_name": sector_name,
                "etf_ticker": etf_ticker,
                "bars": bars,
                "trend_summary": trend_summary,
                "total_change_pct": round(total_chg, 2),
            }
            await self.cache.set(cache_key, result, ttl=600)
            return result
        except Exception as e:
            self.logger.error(
                f"get_us_sector_etf_analysis failed for {sector_name}: {e}"
            )
            raise ValueError(
                f"get_us_sector_etf_analysis failed for {sector_name}: {e}"
            )

    # ------------------------------------------------------------------
    # US Company Profile
    # ------------------------------------------------------------------
    async def get_us_company_profile(self, ticker: str) -> Dict[str, Any]:
        """Fetch comprehensive company profile from Yahoo Finance."""
        cache_key = f"yahoo:us_profile:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)

            def _fetch():
                return ticker_obj.info

            info = await self._run(_fetch)
            if not info or not isinstance(info, dict):
                raise ValueError(f"No info for {ticker}")

            import math

            def _safe(key):
                v = info.get(key)
                if v is None:
                    return None
                try:
                    f = float(v)
                    return None if math.isnan(f) or math.isinf(f) else f
                except Exception:
                    return v

            result = {
                "ticker": ticker,
                "name": info.get("longName") or info.get("shortName", ""),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "country": info.get("country", ""),
                "city": info.get("city", ""),
                "state": info.get("state", ""),
                "address": info.get("address1", ""),
                "website": info.get("website", ""),
                "phone": info.get("phone", ""),
                "employees": _safe("fullTimeEmployees"),
                "description": info.get("longBusinessSummary", ""),
                "market_cap": _safe("marketCap"),
                "enterprise_value": _safe("enterpriseValue"),
                "exchange": info.get("exchange", ""),
                "quote_type": info.get("quoteType", ""),
                "currency": info.get("currency", ""),
                "founded_year": info.get("firstTradeDateEpochUtc"),
                "ceo": "",
                # Key financial snapshot
                "pe_ttm": _safe("trailingPE"),
                "pe_forward": _safe("forwardPE"),
                "pb": _safe("priceToBook"),
                "dividend_yield": _safe("dividendYield"),
                "beta": _safe("beta"),
                "52week_high": _safe("fiftyTwoWeekHigh"),
                "52week_low": _safe("fiftyTwoWeekLow"),
                "50day_ma": _safe("fiftyDayAverage"),
                "200day_ma": _safe("twoHundredDayAverage"),
                "avg_volume": _safe("averageVolume"),
                "shares_outstanding": _safe("sharesOutstanding"),
                "float_shares": _safe("floatShares"),
            }

            # Extract CEO from company officers
            officers = info.get("companyOfficers") or []
            for officer in officers:
                title = str(officer.get("title", "")).lower()
                if "ceo" in title or "chief executive" in title:
                    result["ceo"] = officer.get("name", "")
                    break

            await self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            self.logger.error(f"get_us_company_profile failed for {ticker}: {e}")
            raise ValueError(f"get_us_company_profile failed for {ticker}: {e}")

    # ------------------------------------------------------------------
    # US Analyst Recommendations
    # ------------------------------------------------------------------
    async def get_us_analyst_recommendations(self, ticker: str) -> Dict[str, Any]:
        """Fetch analyst recommendations and upgrade/downgrade history."""
        cache_key = f"yahoo:us_analyst:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)

            def _fetch():
                rec = ticker_obj.recommendations
                summary = ticker_obj.recommendations_summary
                upgrades = ticker_obj.upgrades_downgrades
                info = ticker_obj.info
                return rec, summary, upgrades, info

            rec_df, summary_df, upgrades_df, info = await self._run(_fetch)

            # Target price from info — sanitize NaN/inf
            def _safe_price(val):
                if val is None:
                    return None
                try:
                    f = float(val)
                    return None if (math.isnan(f) or math.isinf(f)) else f
                except Exception:
                    return None

            target_price = _safe_price(info.get("targetHighPrice"))
            target_low = _safe_price(info.get("targetLowPrice"))
            target_mean = _safe_price(info.get("targetMeanPrice"))
            target_median = _safe_price(info.get("targetMedianPrice"))
            current_price = _safe_price(info.get("currentPrice"))
            num_analysts_raw = info.get("numberOfAnalystOpinions")
            num_analysts = int(num_analysts_raw) if num_analysts_raw is not None and not (isinstance(num_analysts_raw, float) and (math.isnan(num_analysts_raw) or math.isinf(num_analysts_raw))) else None

            # Parse recommendations
            recommendations = []
            if rec_df is not None and not rec_df.empty:
                for _, row in rec_df.tail(10).iterrows():
                    period = row.get("period") or row.get("To Period") or ""
                    recommendations.append(
                        {
                            "period": str(period)[:10] if period else "",
                            "strong_buy": int(row.get("strongBuy", 0)),
                            "buy": int(row.get("buy", 0)),
                            "hold": int(row.get("hold", 0)),
                            "sell": int(row.get("sell", 0)),
                            "strong_sell": int(row.get("strongSell", 0)),
                        }
                    )

            # Parse summary
            summary_data = {}
            if summary_df is not None and not summary_df.empty:
                for _, row in summary_df.iterrows():
                    summary_data = {
                        "strong_buy": int(row.get("strongBuy", 0)),
                        "buy": int(row.get("buy", 0)),
                        "hold": int(row.get("hold", 0)),
                        "sell": int(row.get("sell", 0)),
                        "strong_sell": int(row.get("strongSell", 0)),
                    }

            # Parse upgrades/downgrades (last 30 entries)
            upgrade_history = []
            if upgrades_df is not None and not upgrades_df.empty:
                for _, row in upgrades_df.tail(30).iterrows():
                    grade_date = row.get("GradeDate") or row.get("Date")
                    firm = row.get("Firm") or row.get("firm") or ""
                    from_grade = row.get("From Grade") or row.get("fromGrade") or ""
                    to_grade = row.get("To Grade") or row.get("toGrade") or ""
                    action = row.get("Action") or ""

                    # Map action to Chinese labels for AI readability
                    action_map = {
                        "up": "上调",
                        "down": "下调",
                        "main": "维持",
                        "reit": "维持",
                        "init": "首次覆盖",
                    }
                    action_label = action_map.get(str(action).lower(), str(action))

                    upgrade_history.append(
                        {
                            "date": str(grade_date)[:10] if grade_date else "",
                            "firm": str(firm),
                            "from_grade": str(from_grade),
                            "to_grade": str(to_grade),
                            "action": action_label,
                        }
                    )

            result = {
                "ticker": ticker,
                "target_price": {
                    "high": target_price,
                    "low": target_low,
                    "mean": target_mean,
                    "median": target_median,
                },
                "current_price": current_price,
                "num_analysts": num_analysts,
                "recommendations": recommendations,
                "summary": summary_data,
                "upgrade_history": upgrade_history,
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.error(
                f"get_us_analyst_recommendations failed for {ticker}: {e}"
            )
            raise ValueError(
                f"get_us_analyst_recommendations failed for {ticker}: {e}"
            )

    # ------------------------------------------------------------------
    # US Revenue Segments
    # ------------------------------------------------------------------
    async def get_us_revenue_segments(self, ticker: str) -> Dict[str, Any]:
        """Fetch revenue breakdown by geography and business segment."""
        cache_key = f"yahoo:us_segments:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)

            def _fetch():
                info = ticker_obj.info
                return info

            info = await self._run(_fetch)

            # Geographic segments
            geo_segments = []
            geo_fields = {
                "revenueFromGeography_us": ("United States", "us"),
                "revenueFromGeography_europe": ("Europe", "europe"),
                "revenueFromGeography_china": ("China", "china"),
                "revenueFromGeography_japan": ("Japan", "japan"),
                "revenueFromGeography_asiaPacific": ("Asia Pacific", "asia_pacific"),
                "revenueFromGeography_americas": ("Americas", "americas"),
                "revenueFromGeography_emergingMarkets": ("Emerging Markets", "emerging_markets"),
                "revenueFromGeography_row": ("Rest of World", "row"),
            }
            total_geo = 0
            for field, (label, key) in geo_fields.items():
                val = info.get(field)
                if val is not None:
                    try:
                        val = float(val)
                        if math.isnan(val) or math.isinf(val):
                            continue
                        geo_segments.append(
                            {"region": label, "key": key, "revenue": val}
                        )
                        total_geo += val
                    except (TypeError, ValueError):
                        pass

            # Calculate percentages
            for seg in geo_segments:
                seg["pct"] = round(seg["revenue"] / total_geo * 100, 1) if total_geo > 0 else 0

            # Business/product segments
            biz_segments = []
            biz_fields = {
                "revenueFromBusiness_product": ("Product Revenue", "product"),
                "revenueFromBusiness_service": ("Service Revenue", "service"),
                "revenueFromBusiness_hardware": ("Hardware Revenue", "hardware"),
                "revenueFromBusiness_software": ("Software Revenue", "software"),
                "revenueFromBusiness_advertising": ("Advertising Revenue", "advertising"),
                "revenueFromBusiness_subscriptions": ("Subscription Revenue", "subscriptions"),
                "revenueFromBusiness_licensing": ("Licensing Revenue", "licensing"),
            }
            total_biz = 0
            for field, (label, key) in biz_fields.items():
                val = info.get(field)
                if val is not None:
                    try:
                        val = float(val)
                        if math.isnan(val) or math.isinf(val):
                            continue
                        biz_segments.append(
                            {"segment": label, "key": key, "revenue": val}
                        )
                        total_biz += val
                    except (TypeError, ValueError):
                        pass

            for seg in biz_segments:
                seg["pct"] = round(seg["revenue"] / total_biz * 100, 1) if total_biz > 0 else 0

            # Total revenue for context
            total_revenue = info.get("totalRevenue")

            result = {
                "ticker": ticker,
                "name": info.get("longName") or info.get("shortName", ""),
                "total_revenue": total_revenue,
                "currency": info.get("currency", "USD"),
                "geographic_segments": geo_segments,
                "business_segments": biz_segments,
            }
            await self.cache.set(cache_key, result, ttl=3600)
            return result
        except Exception as e:
            self.logger.error(f"get_us_revenue_segments failed for {ticker}: {e}")
            raise ValueError(f"get_us_revenue_segments failed for {ticker}: {e}")

    # ------------------------------------------------------------------
    # US Insider Trading
    # ------------------------------------------------------------------
    async def get_us_insider_trading(self, ticker: str) -> Dict[str, Any]:
        """Fetch recent insider purchase and sale transactions."""
        cache_key = f"yahoo:us_insider:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)

            def _fetch():
                purchases = ticker_obj.insider_purchases
                transactions = ticker_obj.insider_transactions
                return purchases, transactions

            purchases_df, transactions_df = await self._run(_fetch)

            # Parse insider purchases
            purchases = []
            if purchases_df is not None and not purchases_df.empty:
                for _, row in purchases_df.head(20).iterrows():
                    purchases.append(
                        {
                            "insider_name": str(row.get("Insider", "")),
                            "title": str(row.get("Title", "")),
                            "transaction_date": str(row.get("Date", ""))[:10],
                            "shares": int(row.get("Shares", 0)) if row.get("Shares") and not math.isnan(float(row.get("Shares", 0))) else None,
                            "value": float(row.get("Value", 0)) if row.get("Value") and not math.isnan(float(row.get("Value", 0))) else None,
                            "transaction_type": "Purchase",
                        }
                    )

            # Parse insider transactions (includes both buys and sells)
            transactions = []
            if transactions_df is not None and not transactions_df.empty:
                for _, row in transactions_df.head(30).iterrows():
                    shares_raw = row.get("Shares")
                    value_raw = row.get("Value")
                    tx_type = str(row.get("Transaction", "")).lower()

                    # Classify transaction direction
                    if "buy" in tx_type or "purchase" in tx_type:
                        direction = "买入"
                    elif "sell" in tx_type or "sale" in tx_type:
                        direction = "卖出"
                    else:
                        direction = str(row.get("Transaction", ""))

                    transactions.append(
                        {
                            "insider_name": str(row.get("Insider", "")),
                            "title": str(row.get("Title", "")),
                            "transaction_date": str(row.get("Date", ""))[:10],
                            "shares": int(shares_raw) if shares_raw and not math.isnan(float(shares_raw)) else None,
                            "value": float(value_raw) if value_raw and not math.isnan(float(value_raw)) else None,
                            "transaction_type": direction,
                        }
                    )

            # Summary statistics
            buy_count = sum(1 for t in transactions if "买" in t.get("transaction_type", ""))
            sell_count = sum(1 for t in transactions if "卖" in t.get("transaction_type", ""))
            buy_value = sum(t.get("value", 0) or 0 for t in transactions if "买" in t.get("transaction_type", ""))
            sell_value = sum(t.get("value", 0) or 0 for t in transactions if "卖" in t.get("transaction_type", ""))

            result = {
                "ticker": ticker,
                "purchases": purchases,
                "transactions": transactions,
                "summary": {
                    "total_transactions": len(transactions),
                    "buy_count": buy_count,
                    "sell_count": sell_count,
                    "buy_value": buy_value,
                    "sell_value": sell_value,
                    "net_sentiment": "insider_buying" if buy_value > sell_value else "insider_selling" if sell_value > buy_value else "neutral",
                },
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.error(f"get_us_insider_trading failed for {ticker}: {e}")
            raise ValueError(f"get_us_insider_trading failed for {ticker}: {e}")

    # ------------------------------------------------------------------
    # US Share Statistics
    # ------------------------------------------------------------------
    async def get_us_share_statistics(self, ticker: str) -> Dict[str, Any]:
        """Fetch share statistics including short interest and float."""
        cache_key = f"yahoo:us_share_stats:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)

            def _fetch():
                info = ticker_obj.info
                shares = ticker_obj.shares
                return info, shares

            info, shares_df = await self._run(_fetch)

            import math

            def _safe(key):
                v = info.get(key)
                if v is None:
                    return None
                try:
                    f = float(v)
                    return None if math.isnan(f) or math.isinf(f) else f
                except Exception:
                    return None

            # From info dict
            shares_outstanding = _safe("sharesOutstanding")
            float_shares = _safe("floatShares")
            shares_short = _safe("sharesShort")
            shares_short_prior = _safe("sharesShortPriorMonth")
            short_ratio = _safe("shortRatio")
            short_pct_float = _safe("shortPercentOfFloat")

            # Calculate derived metrics
            if shares_short and float_shares and float_shares > 0:
                short_pct_calculated = round(shares_short / float_shares * 100, 2)
            else:
                short_pct_calculated = None

            if shares_short and info.get("averageVolume") and info["averageVolume"] > 0:
                days_to_cover = round(shares_short / info["averageVolume"], 1)
            else:
                days_to_cover = short_ratio

            # Shares dataframe (historical share count changes)
            share_history = []
            if shares_df is not None and not shares_df.empty:
                for idx, row in shares_df.head(10).iterrows():
                    share_history.append(
                        {
                            "date": str(idx)[:10] if idx else "",
                            "shares_outstanding": int(row.get("Shares Outstanding", 0)) if row.get("Shares Outstanding") else None,
                            "float_shares": int(row.get("Float", 0)) if row.get("Float") else None,
                        }
                    )

            # Institutional ownership percentage
            inst_pct = _safe("heldPercentInstitutions")
            insider_pct = _safe("heldPercentInsiders")

            # 5% holders
            five_pct = _safe("heldPercentMutualFunds")

            result = {
                "ticker": ticker,
                "name": info.get("longName") or info.get("shortName", ""),
                "shares_outstanding": shares_outstanding,
                "float_shares": float_shares,
                "short_interest": {
                    "shares_short": shares_short,
                    "shares_short_prior_month": shares_short_prior,
                    "short_pct_of_float": short_pct_calculated or short_pct_float,
                    "short_ratio": short_ratio,
                    "days_to_cover": days_to_cover,
                },
                "ownership": {
                    "institutional_pct": round(inst_pct * 100, 1) if inst_pct else None,
                    "insider_pct": round(insider_pct * 100, 1) if insider_pct else None,
                    "mutual_funds_pct": round(five_pct * 100, 1) if five_pct else None,
                },
                "share_history": share_history,
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.error(f"get_us_share_statistics failed for {ticker}: {e}")
            raise ValueError(f"get_us_share_statistics failed for {ticker}: {e}")

    # ------------------------------------------------------------------
    # US Financial Health Score
    # ------------------------------------------------------------------
    async def get_us_financial_health(self, ticker: str) -> Dict[str, Any]:
        """Compute comprehensive financial health score for a US stock.

        Aggregates data from income statement, balance sheet, cash flow
        and the info dict to compute profitability, liquidity, solvency,
        efficiency and growth ratios. Returns a composite 0-100 score
        with letter grade and key findings.
        """
        cache_key = f"yahoo:us_health:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        ticker_norm = self._to_yf_ticker(ticker)
        try:
            ticker_obj = await self._run(yf.Ticker, ticker_norm)

            def _fetch():
                info = ticker_obj.info
                return info

            info = await self._run(_fetch)
            if not info or not isinstance(info, dict):
                raise ValueError(f"No info data for {ticker}")

            import math

            def _safe(key):
                v = info.get(key)
                if v is None:
                    return None
                try:
                    f = float(v)
                    return None if math.isnan(f) or math.isinf(f) else f
                except Exception:
                    return None

            # ------------------------------------------------------------------
            # 1. Profitability ratios
            # ------------------------------------------------------------------
            gross_margin = _safe("grossMargins")
            operating_margin = _safe("operatingMargins")
            net_margin = _safe("profitMargins")
            roe = _safe("returnOnEquity")
            roa = _safe("returnOnAssets")

            profitability = {
                "gross_margin": round(gross_margin * 100, 1) if gross_margin else None,
                "operating_margin": round(operating_margin * 100, 1) if operating_margin else None,
                "net_margin": round(net_margin * 100, 1) if net_margin else None,
                "roe": round(roe * 100, 1) if roe else None,
                "roa": round(roa * 100, 1) if roa else None,
            }

            # ------------------------------------------------------------------
            # 2. Liquidity ratios
            # ------------------------------------------------------------------
            current_ratio = _safe("currentRatio")
            quick_ratio = _safe("quickRatio")

            liquidity = {
                "current_ratio": round(current_ratio, 2) if current_ratio else None,
                "quick_ratio": round(quick_ratio, 2) if quick_ratio else None,
            }

            # ------------------------------------------------------------------
            # 3. Solvency / Leverage ratios
            # ------------------------------------------------------------------
            debt_to_equity = _safe("debtToEquity")
            interest_coverage = None
            # Try to compute from raw data
            operating_income = _safe("operatingIncome") or _safe("ebit")
            interest_expense = _safe("interestExpense")
            if operating_income and interest_expense and interest_expense != 0:
                interest_coverage = round(operating_income / abs(interest_expense), 1)

            solvency = {
                "debt_to_equity": round(debt_to_equity, 2) if debt_to_equity else None,
                "interest_coverage": interest_coverage,
            }

            # ------------------------------------------------------------------
            # 4. Valuation metrics
            # ------------------------------------------------------------------
            pe_ttm = _safe("trailingPE")
            pe_forward = _safe("forwardPE")
            pb = _safe("priceToBook")
            ps = _safe("priceToSalesTrailing12Months")
            ev_ebitda = _safe("enterpriseToEbitda")
            peg = _safe("pegRatio")

            valuation = {
                "pe_ttm": round(pe_ttm, 1) if pe_ttm else None,
                "pe_forward": round(pe_forward, 1) if pe_forward else None,
                "pb": round(pb, 2) if pb else None,
                "ps": round(ps, 2) if ps else None,
                "ev_ebitda": round(ev_ebitda, 1) if ev_ebitda else None,
                "peg": round(peg, 2) if peg else None,
            }

            # ------------------------------------------------------------------
            # 5. Growth rates
            # ------------------------------------------------------------------
            revenue_growth = _safe("revenueGrowth")
            earnings_growth = _safe("earningsGrowth")
            revenue_per_share = _safe("revenuePerShare")
            earnings_per_share = _safe("trailingEps")

            growth = {
                "revenue_growth_yoy": round(revenue_growth * 100, 1) if revenue_growth else None,
                "earnings_growth_yoy": round(earnings_growth * 100, 1) if earnings_growth else None,
                "revenue_per_share": round(revenue_per_share, 2) if revenue_per_share else None,
                "eps_ttm": round(earnings_per_share, 2) if earnings_per_share else None,
            }

            # ------------------------------------------------------------------
            # 6. Dividend info
            # ------------------------------------------------------------------
            div_yield = _safe("dividendYield")
            payout_ratio = _safe("payoutRatio")
            div_rate = _safe("dividendRate")

            dividend = {
                "yield": round(div_yield * 100, 2) if div_yield else None,
                "payout_ratio": round(payout_ratio * 100, 1) if payout_ratio else None,
                "annual_rate": round(div_rate, 2) if div_rate else None,
            }

            # ------------------------------------------------------------------
            # 7. Compute composite health score (0-100)
            # ------------------------------------------------------------------
            score_components = []
            max_score = 0

            # Profitability (weight: 30)
            profit_weight = 30
            profit_score = 0
            if net_margin is not None:
                if net_margin > 0.20:
                    profit_score += 10
                elif net_margin > 0.10:
                    profit_score += 7
                elif net_margin > 0.05:
                    profit_score += 4
                elif net_margin > 0:
                    profit_score += 2
            if roe is not None:
                if 0.10 < roe < 0.40:
                    profit_score += 10
                elif 0.05 < roe < 0.50:
                    profit_score += 6
                elif roe > 0:
                    profit_score += 3
            if operating_margin is not None:
                if operating_margin > 0.20:
                    profit_score += 10
                elif operating_margin > 0.10:
                    profit_score += 7
                elif operating_margin > 0:
                    profit_score += 3
            score_components.append(("profitability", profit_score, profit_weight))
            max_score += profit_weight

            # Liquidity (weight: 15)
            liq_weight = 15
            liq_score = 0
            if current_ratio is not None:
                if 1.5 <= current_ratio <= 3.0:
                    liq_score += 8
                elif 1.0 <= current_ratio <= 5.0:
                    liq_score += 5
                elif current_ratio > 0:
                    liq_score += 2
            if quick_ratio is not None:
                if 1.0 <= quick_ratio <= 2.5:
                    liq_score += 7
                elif 0.5 <= quick_ratio <= 4.0:
                    liq_score += 4
            score_components.append(("liquidity", liq_score, liq_weight))
            max_score += liq_weight

            # Solvency (weight: 20)
            solv_weight = 20
            solv_score = 0
            if debt_to_equity is not None:
                if debt_to_equity < 0.5:
                    solv_score += 10
                elif debt_to_equity < 1.0:
                    solv_score += 8
                elif debt_to_equity < 2.0:
                    solv_score += 5
                elif debt_to_equity < 3.0:
                    solv_score += 2
            if interest_coverage is not None:
                if interest_coverage > 10:
                    solv_score += 10
                elif interest_coverage > 5:
                    solv_score += 7
                elif interest_coverage > 2:
                    solv_score += 4
                elif interest_coverage > 0:
                    solv_score += 1
            score_components.append(("solvency", solv_score, solv_weight))
            max_score += solv_weight

            # Growth (weight: 20)
            growth_weight = 20
            growth_score = 0
            if revenue_growth is not None:
                if revenue_growth > 0.20:
                    growth_score += 10
                elif revenue_growth > 0.10:
                    growth_score += 8
                elif revenue_growth > 0:
                    growth_score += 5
                elif revenue_growth > -0.10:
                    growth_score += 2
            if earnings_growth is not None:
                if earnings_growth > 0.20:
                    growth_score += 10
                elif earnings_growth > 0.10:
                    growth_score += 7
                elif earnings_growth > 0:
                    growth_score += 4
                elif earnings_growth > -0.10:
                    growth_score += 2
            score_components.append(("growth", growth_score, growth_weight))
            max_score += growth_weight

            # Valuation reasonableness (weight: 15)
            val_weight = 15
            val_score = 0
            if pe_ttm is not None and pe_ttm > 0:
                if 8 <= pe_ttm <= 25:
                    val_score += 5
                elif 25 < pe_ttm <= 40:
                    val_score += 3
                elif pe_ttm <= 50:
                    val_score += 1
            if peg is not None and peg > 0:
                if peg < 1.0:
                    val_score += 5
                elif peg < 2.0:
                    val_score += 3
                elif peg < 3.0:
                    val_score += 1
            if pb is not None and pb > 0:
                if pb < 3.0:
                    val_score += 5
                elif pb < 6.0:
                    val_score += 3
                elif pb < 10.0:
                    val_score += 1
            score_components.append(("valuation", val_score, val_weight))
            max_score += val_weight

            # Calculate total score
            total_score = sum(s for _, s, _ in score_components)
            health_score = round(total_score / max_score * 100, 1) if max_score > 0 else 0

            # Letter grade
            if health_score >= 85:
                grade = "A+"
                label = "极优"
            elif health_score >= 75:
                grade = "A"
                label = "优秀"
            elif health_score >= 65:
                grade = "B+"
                label = "良好"
            elif health_score >= 55:
                grade = "B"
                label = "中等偏上"
            elif health_score >= 45:
                grade = "B-"
                label = "中等"
            elif health_score >= 35:
                grade = "C+"
                label = "中等偏下"
            elif health_score >= 25:
                grade = "C"
                label = "较弱"
            else:
                grade = "D"
                label = "风险较高"

            # Key findings
            findings = []
            if net_margin and net_margin > 0.15:
                findings.append(f"高净利润率({net_margin*100:.1f}%)")
            elif net_margin and net_margin < 0.05:
                findings.append(f"低净利润率({net_margin*100:.1f}%)")
            if roe and roe > 0.20:
                findings.append(f"高ROE({roe*100:.1f}%)")
            if debt_to_equity and debt_to_equity > 2.0:
                findings.append(f"高负债率(D/E={debt_to_equity:.1f})")
            elif debt_to_equity and debt_to_equity < 0.3:
                findings.append(f"低负债率(D/E={debt_to_equity:.1f})")
            if revenue_growth and revenue_growth > 0.20:
                findings.append(f"高营收增长({revenue_growth*100:.1f}%)")
            elif revenue_growth and revenue_growth < -0.10:
                findings.append(f"营收下滑({revenue_growth*100:.1f}%)")
            if current_ratio and current_ratio < 1.0:
                findings.append(f"流动性风险(流动比率={current_ratio:.1f})")
            if div_yield and div_yield > 0.04:
                findings.append(f"高股息率({div_yield*100:.1f}%)")

            result = {
                "ticker": ticker,
                "name": info.get("longName") or info.get("shortName", ""),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "market_cap": _safe("marketCap"),
                "health_score": health_score,
                "grade": grade,
                "grade_label": label,
                "score_breakdown": {
                    name: {"score": s, "max": m, "pct": round(s / m * 100, 0) if m > 0 else 0}
                    for name, s, m in score_components
                },
                "profitability": profitability,
                "liquidity": liquidity,
                "solvency": solvency,
                "valuation": valuation,
                "growth": growth,
                "dividend": dividend,
                "key_findings": findings,
            }
            await self.cache.set(cache_key, result, ttl=1800)
            return result
        except Exception as e:
            self.logger.error(f"get_us_financial_health failed for {ticker}: {e}")
            raise ValueError(f"get_us_financial_health failed for {ticker}: {e}")

    # ------------------------------------------------------------------
    # US market overview / snapshot
    # ------------------------------------------------------------------

    async def get_us_market_overview(self) -> Dict[str, Any]:
        """Get US market overview: major indices, VIX, sector performance.

        Fetches data for key market proxies via yfinance:
        - SPY (S&P 500), QQQ (Nasdaq 100), DIA (Dow 30), IWM (Russell 2000)
        - VIX (volatility index)
        - Sector ETFs (XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLB, XLRE, XLU, XLC)

        Returns a comprehensive market snapshot for AI analysis.
        """
        def _safe(val):
            if val is None:
                return None
            try:
                f = float(val)
                return None if (math.isnan(f) or math.isinf(f)) else f
            except Exception:
                return None

        cache_key = "yahoo:us_market_overview"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        try:
            # Major indices
            index_tickers = {
                "SPY": "S&P 500",
                "QQQ": "Nasdaq 100",
                "DIA": "Dow 30",
                "IWM": "Russell 2000",
            }
            # Sector ETFs
            sector_etfs = {
                "XLK": "Technology",
                "XLF": "Financials",
                "XLE": "Energy",
                "XLV": "Healthcare",
                "XLY": "Consumer Disc.",
                "XLP": "Consumer Staples",
                "XLI": "Industrials",
                "XLB": "Materials",
                "XLRE": "Real Estate",
                "XLU": "Utilities",
                "XLC": "Communication",
            }
            vix_ticker = "^VIX"

            all_symbols = list(index_tickers.keys()) + list(sector_etfs.keys()) + [vix_ticker]

            def _fetch_all():
                result = {}
                for sym in all_symbols:
                    try:
                        t = yf.Ticker(sym)
                        info = t.info
                        result[sym] = {
                            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                            "change_pct": info.get("regularMarketChangePercent"),
                            "change": info.get("regularMarketChange"),
                            "volume": info.get("regularMarketVolume"),
                        }
                    except Exception:
                        result[sym] = None
                return result

            raw_quotes = await self._run(_fetch_all)

            # Build indices section
            indices = []
            for sym, name in index_tickers.items():
                q = raw_quotes.get(sym) or {}
                indices.append({
                    "symbol": sym,
                    "name": name,
                    "price": round(_safe(q.get("price")) or 0, 2),
                    "change_pct": round(_safe(q.get("change_pct")) or 0, 2),
                    "change": round(_safe(q.get("change")) or 0, 2),
                    "volume": q.get("volume"),
                })

            # Build sectors section
            sectors = []
            for sym, name in sector_etfs.items():
                q = raw_quotes.get(sym) or {}
                sectors.append({
                    "symbol": sym,
                    "name": name,
                    "change_pct": round(_safe(q.get("change_pct")) or 0, 2),
                    "price": round(_safe(q.get("price")) or 0, 2),
                })
            sectors.sort(key=lambda x: x.get("change_pct", 0), reverse=True)

            # VIX
            vix_q = raw_quotes.get(vix_ticker) or {}
            vix_level = _safe(vix_q.get("price"))
            if vix_level is not None and vix_level < 15:
                vix_signal = "低波动"
            elif vix_level is not None and vix_level < 20:
                vix_signal = "正常"
            elif vix_level is not None and vix_level < 30:
                vix_signal = "偏高"
            else:
                vix_signal = "高波动/恐慌"

            # Market sentiment summary
            spy_change = 0
            for idx in indices:
                if idx["symbol"] == "SPY":
                    spy_change = idx.get("change_pct", 0)
                    break

            up_sectors = sum(1 for s in sectors if s.get("change_pct", 0) > 0)
            down_sectors = len(sectors) - up_sectors

            if spy_change > 1.0:
                sentiment = "强势上涨"
            elif spy_change > 0:
                sentiment = "温和上涨"
            elif spy_change > -1.0:
                sentiment = "温和下跌"
            else:
                sentiment = "显著下跌"

            result = {
                "indices": indices,
                "sectors": sectors,
                "vix": {
                    "level": round(vix_level, 2) if vix_level else None,
                    "signal": vix_signal,
                },
                "market_breadth": {
                    "up_sectors": up_sectors,
                    "down_sectors": down_sectors,
                },
                "sentiment": sentiment,
                "source": "yahoo",
            }
            await self.cache.set(cache_key, result, ttl=300)
            return result

        except Exception as e:
            self.logger.error(f"get_us_market_overview failed: {e}")
            return {"error": str(e), "indices": [], "sectors": [], "source": "yahoo"}

    # ------------------------------------------------------------------
    # US Stock Fact Pack (COL-164)
    # ------------------------------------------------------------------

    async def get_us_stock_fact_pack(self, ticker: str) -> Dict[str, Any]:
        """Aggregate US stock fact pack: profile, valuation, financials,
        ownership, analyst, technical — 6 categories with error isolation."""
        t0 = time.perf_counter()
        cache_key = f"yahoo:us_fact_pack:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        entity = {"symbol": ticker, "asset_type": "us_stock"}
        facts: Dict[str, Any] = {}
        source_trace: Dict[str, Any] = {}
        coverage: Dict[str, str] = {}
        missing_fields: list = []

        async def _cat(name: str, coro):
            """Fetch one category; never lets a single failure cascade."""
            try:
                result = await coro
                if result and not (isinstance(result, dict) and result.get("error")):
                    facts[name] = result
                    coverage[name] = "complete"
                    source_trace[name] = {"provider": "yahoo"}
                else:
                    coverage[name] = "empty"
                    missing_fields.append(name)
            except Exception as e:
                self.logger.warning(f"US fact pack '{name}' failed for {ticker}: {e}")
                coverage[name] = "error"
                source_trace[name] = {"provider": "yahoo", "error": str(e)}
                missing_fields.append(name)

        # Run all 6 categories concurrently for speed
        await asyncio.gather(
            _cat("profile", self._us_fp_profile(ticker)),
            _cat("valuation", self._us_fp_valuation(ticker)),
            _cat("financials", self._us_fp_financials(ticker)),
            _cat("ownership", self._us_fp_ownership(ticker)),
            _cat("analyst", self._us_fp_analyst(ticker)),
            _cat("technical", self._us_fp_technical(ticker)),
        )

        elapsed = time.perf_counter() - t0
        result = {
            "source": "yahoo",
            "entity": entity,
            "facts": facts,
            "source_trace": source_trace,
            "coverage": coverage,
            "missing_fields": missing_fields,
            "categories_fetched": sum(1 for v in coverage.values() if v == "complete"),
            "categories_total": 6,
            "elapsed_seconds": round(elapsed, 2),
        }
        await self.cache.set(cache_key, result, ttl=600)
        return result

    # -- helper: safe float --
    def _sf(self, val) -> Optional[float]:
        if val is None:
            return None
        try:
            f = float(val)
            return None if (math.isnan(f) or math.isinf(f)) else f
        except Exception:
            return None

    # -- category helpers (private) --

    async def _us_fp_profile(self, ticker: str) -> Dict[str, Any]:
        profile = await self.get_us_company_profile(ticker)
        if not profile:
            return {}
        return {
            "company_name": profile.get("companyName"),
            "exchange": profile.get("exchange"),
            "industry": profile.get("industry"),
            "sector": profile.get("sector"),
            "country": profile.get("country"),
            "employees": self._sf(profile.get("fullTimeEmployees")),
            "website": profile.get("website"),
            "business_summary": (profile.get("longBusinessSummary") or "")[:500],
            "market_cap": self._sf(profile.get("marketCap")),
            "price": self._sf(profile.get("currentPrice")),
            "currency": profile.get("currency", "USD"),
        }

    async def _us_fp_valuation(self, ticker: str) -> Dict[str, Any]:
        val = await self.get_us_valuation_metrics(ticker)
        if not val:
            return {}
        return val

    async def _us_fp_financials(self, ticker: str) -> Dict[str, Any]:
        health, cashflow, earnings = await asyncio.gather(
            self.get_us_financial_health(ticker),
            self.get_cash_flow_quality(ticker),
            self.get_earnings_history(ticker, quarters=4),
        )
        result: Dict[str, Any] = {}
        if health:
            result["health_score"] = health
        if cashflow:
            result["cashflow_quality"] = cashflow
        if earnings:
            result["earnings_history"] = earnings
        return result

    async def _us_fp_ownership(self, ticker: str) -> Dict[str, Any]:
        inst, insider = await asyncio.gather(
            self.get_us_institutional_holdings(ticker),
            self.get_us_insider_trading(ticker),
        )
        result: Dict[str, Any] = {}
        if inst:
            result["institutional"] = inst
        if insider:
            result["insider"] = insider
        return result

    async def _us_fp_analyst(self, ticker: str) -> Dict[str, Any]:
        rec, segments = await asyncio.gather(
            self.get_us_analyst_recommendations(ticker),
            self.get_us_revenue_segments(ticker),
        )
        result: Dict[str, Any] = {}
        if rec:
            result["recommendations"] = rec
        if segments:
            result["revenue_segments"] = segments
        return result

    async def _us_fp_technical(self, ticker: str) -> Dict[str, Any]:
        price, volume = await asyncio.gather(
            self.get_us_price_history(ticker, days=60),
            self.get_us_volume_analysis(ticker, days=30),
        )
        result: Dict[str, Any] = {}
        if price:
            result["price_history"] = price
        if volume:
            result["volume_analysis"] = volume
        return result

