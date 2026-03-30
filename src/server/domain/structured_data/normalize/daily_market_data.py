# src/server/domain/structured_data/normalize/daily_market_data.py
"""Normalizer for daily market data (日频市场数据).

Maps AssetPrice objects from gateway adapters into a unified canonical
schema for daily OHLCV + valuation snapshots.

Canonical schema:
    business_key: {exchange}:{symbol}:{trade_date}
    symbol, exchange, trade_date,
    open, high, low, close, volume,
    change, change_percent, market_cap
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger

from .engine import Normalizer


class DailyMarketDataNormalizer(Normalizer):
    """Normalizer for daily market data (OHLCV) dimension."""

    @property
    def dataset_key(self) -> str:
        return "daily_market_data"

    async def normalize(
        self,
        raw_data: Dict[str, Any],
        source: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Transform raw daily market data to canonical schema.

        Expected raw_data shapes:

        gateway historical prices (via adapter.get_historical_prices):
            Returns AssetPrice objects; caller should convert to dicts first.
            Each dict: {ticker, price, currency, timestamp, volume,
                        open_price, high_price, low_price, close_price,
                        change, change_percent, market_cap}

        Or pre-converted list of dicts under "rows" key.
        """
        now = datetime.now(timezone.utc).isoformat()

        symbol = kwargs.get("symbol", "")
        exchange = kwargs.get("exchange", "")

        # Handle single-row input (one day)
        rows = raw_data.get("rows", [])
        if not rows and self._is_single_row(raw_data):
            rows = [raw_data]

        # Normalize each row
        canonical_rows = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            canonical_rows.append(self._normalize_row(row, symbol, exchange, source))

        # Extract symbol/exchange from first row if not provided
        if not symbol and canonical_rows:
            symbol = canonical_rows[0].get("symbol", "")
            exchange = canonical_rows[0].get("exchange", "")

        # Use latest trade_date for overall business_key
        trade_date = ""
        if canonical_rows:
            trade_date = canonical_rows[-1].get("trade_date", "")

        biz_key = f"{exchange}:{symbol}:{trade_date}" if exchange and symbol and trade_date else ""

        return {
            "business_key": biz_key,
            "symbol": symbol,
            "exchange": exchange,
            "trade_date": trade_date,
            "rows": canonical_rows,
            "row_count": len(canonical_rows),
            "_source": source,
            "_normalized_at": now,
        }

    def _is_single_row(self, raw: Dict[str, Any]) -> bool:
        """Check if raw_data is a single row rather than a container."""
        return any(k in raw for k in ("open_price", "close_price", "price", "ticker", "timestamp"))

    def _normalize_row(
        self, row: Dict[str, Any], symbol: str, exchange: str, source: str
    ) -> Dict[str, Any]:
        """Normalize a single day's market data."""
        # Extract trade_date from timestamp
        trade_date = ""
        ts = row.get("timestamp") or row.get("trade_date")
        if ts:
            ts_str = str(ts)[:10]  # YYYY-MM-DD
            trade_date = ts_str.replace("-", "")

        # Extract symbol/exchange from ticker if not provided
        row_symbol = symbol
        row_exchange = exchange
        ticker = row.get("ticker", "")
        if not row_symbol and ticker and ":" in ticker:
            row_exchange, row_symbol = ticker.split(":", 1)
        elif not row_symbol:
            row_symbol = ticker

        # OHLCV values
        def _float(val, default=None):
            if val is None:
                return default
            try:
                return float(val)
            except (TypeError, ValueError):
                return default

        return {
            "symbol": row_symbol,
            "exchange": row_exchange,
            "trade_date": trade_date,
            "open": _float(row.get("open_price")),
            "high": _float(row.get("high_price")),
            "low": _float(row.get("low_price")),
            "close": _float(row.get("close_price") or row.get("price")),
            "volume": _float(row.get("volume")),
            "change": _float(row.get("change")),
            "change_percent": _float(row.get("change_percent")),
            "market_cap": _float(row.get("market_cap")),
            "currency": row.get("currency", ""),
        }
