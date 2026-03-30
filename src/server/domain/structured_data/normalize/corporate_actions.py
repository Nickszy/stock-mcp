# src/server/domain/structured_data/normalize/corporate_actions.py
"""Normalizer for corporate actions (公司结构化事件) data.

Maps source-specific fields from akshare/tushare into a unified canonical
schema for corporate events including buybacks, restricted share releases,
and block trades.

Canonical schema:
    business_key: {exchange}:{symbol}:{event_type}:{event_date}
    symbol, exchange, event_type, event_date,
    events: [
        {
            event_type, event_date, description,
            amount, price, currency, raw_data
        }
    ]
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger

from .engine import FieldMapping, MISSING, Normalizer

# ---------------------------------------------------------------------------
# Akshare field mappings
# ---------------------------------------------------------------------------

# Akshare repurchase (stock_repurchase_em)
_REPURCHASE_MAP = [
    ("股票代码", "symbol", str, MISSING),
    ("公司名称", "company_name", str, MISSING),
    ("回购期限", "period", str, MISSING),
    ("回购目的", "purpose", str, MISSING),
    ("实施进度", "progress", str, MISSING),
    ("回购价格区间", "price_range", str, MISSING),
    ("回购数量", "volume", float, MISSING),
    ("回购金额", "amount", float, MISSING),
    ("最新公告日期", "announce_date", str, MISSING),
]

# Akshare restricted release summary
_RESTRICTED_SUMMARY_MAP = [
    ("股票代码", "symbol", str, MISSING),
    ("股票简称", "short_name", str, MISSING),
    ("解禁日期", "release_date", str, MISSING),
    ("解禁数量", "release_volume", float, MISSING),
    ("解禁市值", "release_value", float, MISSING),
    ("限售股类型", "restricted_type", str, MISSING),
]

# Akshare block trade (stock_dzjy_mrmx)
_BLOCK_TRADE_MAP = [
    ("交易日期", "trade_date", str, MISSING),
    ("证券代码", "symbol", str, MISSING),
    ("证券简称", "short_name", str, MISSING),
    ("成交价", "price", float, MISSING),
    ("成交量", "volume", float, MISSING),
    ("成交额", "amount", float, MISSING),
    ("折溢率", "premium_rate", float, MISSING),
    ("买方营业部", "buyer", str, MISSING),
    ("卖方营业部", "seller", str, MISSING),
]


def _safe_float(val: Any, default: Optional[float] = None) -> Optional[float]:
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _format_date(val: Any) -> str:
    """Convert date value to YYYY-MM-DD string."""
    if not val:
        return ""
    s = str(val).strip()
    # Already in YYYY-MM-DD
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    # YYYYMMDD format
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    # ISO format with time
    if len(s) >= 10:
        return s[:10]
    return s


class CorporateActionsNormalizer(Normalizer):
    """Normalizer for corporate actions (公司结构化事件) data dimension."""

    @property
    def dataset_key(self) -> str:
        return "corporate_actions"

    async def normalize(
        self,
        raw_data: Dict[str, Any],
        source: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Transform raw corporate action data to canonical schema.

        Expected raw_data shapes:

        akshare:
            {
                "repurchase": {"data": [...], ...},
                "restricted_release": {"data": {"summary": [...], "queue": [...]}, ...},
                "block_trade": {"data": [...], ...},
            }
        Or pre-sectioned with sections as top-level keys.
        """
        now = datetime.now(timezone.utc).isoformat()

        symbol = kwargs.get("symbol", "")
        exchange = kwargs.get("exchange", "")
        event_type = kwargs.get("event_type", "all")

        # Collect all events into a unified list
        events: List[Dict[str, Any]] = []

        if source in ("akshare", "tushare"):
            events = self._normalize_akshare(raw_data, symbol, exchange)
        else:
            # Generic passthrough
            events = raw_data.get("events", [])
            if not events and isinstance(raw_data.get("data"), list):
                events = raw_data["data"]

        # Determine event_date from latest event for business_key
        event_date = ""
        if events:
            dates = [e.get("event_date", "") for e in events if e.get("event_date")]
            if dates:
                event_date = sorted(dates)[-1]  # latest date

        biz_key = (
            f"{exchange}:{symbol}:{event_type}:{event_date}"
            if exchange and symbol and event_date
            else ""
        )

        return {
            "business_key": biz_key,
            "symbol": symbol,
            "exchange": exchange,
            "event_type": event_type,
            "event_date": event_date,
            "events": events,
            "event_count": len(events),
            "_source": source,
            "_normalized_at": now,
        }

    def _normalize_akshare(
        self,
        raw_data: Dict[str, Any],
        symbol: str,
        exchange: str,
    ) -> List[Dict[str, Any]]:
        """Normalize akshare corporate action data."""
        events: List[Dict[str, Any]] = []

        # --- Repurchase events ---
        repo_data = raw_data.get("repurchase", {})
        repo_rows = repo_data.get("data", []) if isinstance(repo_data, dict) else []
        if isinstance(repo_rows, list):
            mapping = FieldMapping(_REPURCHASE_MAP)
            for row in repo_rows:
                if not isinstance(row, dict):
                    continue
                mapped = mapping.apply(row)
                evt_date = _format_date(mapped.get("announce_date", ""))
                events.append({
                    "event_type": "buyback",
                    "event_date": evt_date,
                    "description": f"{mapped.get('company_name', '')} 回购: {mapped.get('purpose', '')}",
                    "amount": _safe_float(mapped.get("amount")),
                    "volume": _safe_float(mapped.get("volume")),
                    "price_range": mapped.get("price_range", ""),
                    "progress": mapped.get("progress", ""),
                    "currency": "CNY",
                    "raw_data": mapped,
                })

        # --- Restricted release events ---
        restricted_data = raw_data.get("restricted_release", {})
        if isinstance(restricted_data, dict):
            summary_rows = restricted_data.get("summary", [])
            if isinstance(summary_rows, list):
                mapping = FieldMapping(_RESTRICTED_SUMMARY_MAP)
                for row in summary_rows:
                    if not isinstance(row, dict):
                        continue
                    mapped = mapping.apply(row)
                    # Filter by symbol if provided
                    row_sym = str(mapped.get("symbol", ""))
                    if symbol and row_sym and symbol not in row_sym:
                        continue
                    evt_date = _format_date(mapped.get("release_date", ""))
                    events.append({
                        "event_type": "restricted_release",
                        "event_date": evt_date,
                        "description": f"{mapped.get('short_name', row_sym)} 解禁: {mapped.get('restricted_type', '')}",
                        "amount": _safe_float(mapped.get("release_value")),
                        "volume": _safe_float(mapped.get("release_volume")),
                        "restricted_type": mapped.get("restricted_type", ""),
                        "currency": "CNY",
                        "raw_data": mapped,
                    })

        # --- Block trade events ---
        block_data = raw_data.get("block_trade", {})
        block_rows = block_data.get("data", []) if isinstance(block_data, dict) else []
        if isinstance(block_rows, list):
            mapping = FieldMapping(_BLOCK_TRADE_MAP)
            for row in block_rows:
                if not isinstance(row, dict):
                    continue
                mapped = mapping.apply(row)
                # Filter by symbol if provided
                row_sym = str(mapped.get("symbol", ""))
                if symbol and row_sym and symbol not in row_sym:
                    continue
                evt_date = _format_date(mapped.get("trade_date", ""))
                events.append({
                    "event_type": "block_trade",
                    "event_date": evt_date,
                    "description": f"{mapped.get('short_name', row_sym)} 大宗交易",
                    "amount": _safe_float(mapped.get("amount")),
                    "volume": _safe_float(mapped.get("volume")),
                    "price": _safe_float(mapped.get("price")),
                    "premium_rate": _safe_float(mapped.get("premium_rate")),
                    "currency": "CNY",
                    "raw_data": mapped,
                })

        return events
