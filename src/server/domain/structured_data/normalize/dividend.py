# src/server/domain/structured_data/normalize/dividend.py
"""Normalizer for dividend (分红送转) data.

Maps source-specific fields from tushare and baostock into a unified
canonical schema for dividend history records.

Canonical schema:
    business_key: {exchange}:{symbol}:{end_date}:cash
    symbol, exchange, end_date, ann_date, div_proc,
    cash_div, cash_div_tax, stk_div (每10股送转),
    stk_bo_rate (每10股送股比例), stk_co_rate (每10股转增比例),
    record_date, ex_date, pay_date, div_listdate,
    imp_ann_date, base_share
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger

from .engine import FieldMapping, MISSING, Normalizer

# ---------------------------------------------------------------------------
# Source field mappings
# ---------------------------------------------------------------------------

# Tushare dividend field mapping (client.dividend API)
_TUSHARE_ROW_MAP = [
    ("end_date", "end_date", str, MISSING),
    ("ann_date", "ann_date", str, MISSING),
    ("div_proc", "div_proc", str, MISSING),
    ("stk_div", "stk_div", float, MISSING),
    ("stk_bo_rate", "stk_bo_rate", float, MISSING),
    ("stk_co_rate", "stk_co_rate", float, MISSING),
    ("cash_div", "cash_div", float, MISSING),
    ("cash_div_tax", "cash_div_tax", float, MISSING),
    ("record_date", "record_date", str, MISSING),
    ("ex_date", "ex_date", str, MISSING),
    ("pay_date", "pay_date", str, MISSING),
    ("div_listdate", "div_listdate", str, MISSING),
    ("imp_ann_date", "imp_ann_date", str, MISSING),
    ("base_share", "base_share", float, MISSING),
]

# Baostock uses similar field names after normalization in the adapter
_BAOSTOCK_ROW_MAP = _TUSHARE_ROW_MAP  # baostock adapter normalizes to tushare-like schema


class DividendNormalizer(Normalizer):
    """Normalizer for dividend (分红送转) data dimension."""

    @property
    def dataset_key(self) -> str:
        return "dividend"

    async def normalize(
        self,
        raw_data: Dict[str, Any],
        source: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Transform raw dividend data to canonical schema.

        Expected raw_data shapes:

        tushare/baostock:
            {
                "ts_code": "600519.SH",
                "rows": [
                    {
                        "end_date": "20231231",
                        "cash_div": 25.91,
                        "cash_div_tax": 30.87,
                        "stk_bo_rate": 0.0,
                        "stk_co_rate": 0.0,
                        ...
                    }
                ]
            }
        """
        now = datetime.now(timezone.utc).isoformat()

        # Extract symbol and exchange from kwargs or raw_data
        symbol = kwargs.get("symbol", "")
        exchange = kwargs.get("exchange", "")

        if not symbol:
            ts_code = raw_data.get("ts_code", "")
            if ts_code:
                symbol, exchange = _parse_ts_code(ts_code)

        # Normalize rows
        raw_rows = raw_data.get("rows", [])
        canonical_rows = []

        if source in ("tushare", "baostock"):
            mapping = FieldMapping(_TUSHARE_ROW_MAP)
            for row in raw_rows:
                mapped = mapping.apply(row)
                # Format YYYYMMDD dates to YYYY-MM-DD
                for date_field in ("end_date", "ann_date", "record_date",
                                   "ex_date", "pay_date", "div_listdate", "imp_ann_date"):
                    val = mapped.get(date_field)
                    if val and isinstance(val, str) and len(val) == 8 and val.isdigit():
                        mapped[date_field] = f"{val[:4]}-{val[4:6]}-{val[6:8]}"
                canonical_rows.append(mapped)
        else:
            # Generic: pass through rows as-is
            canonical_rows = list(raw_rows)

        # Build business keys for each row
        for row in canonical_rows:
            end_date = str(row.get("end_date", "")).replace("-", "")[:8]
            row["business_key"] = f"{exchange}:{symbol}:{end_date}:cash"

        # Determine latest end_date for the overall record
        latest_end_date = ""
        for row in canonical_rows:
            ed = str(row.get("end_date", "")).replace("-", "")[:8]
            if ed > latest_end_date:
                latest_end_date = ed

        if not latest_end_date:
            latest_end_date = kwargs.get("report_period", "")

        biz_key = f"{exchange}:{symbol}:{latest_end_date}:cash" if exchange and symbol else ""
        result: Dict[str, Any] = {
            "business_key": biz_key,
            "symbol": symbol,
            "exchange": exchange,
            "rows": canonical_rows,
            "row_count": len(canonical_rows),
            "_source": source,
            "_normalized_at": now,
        }

        return result


def _parse_ts_code(ts_code: str) -> tuple:
    """Parse tushare ts_code like '600519.SH' to (symbol, exchange)."""
    if not ts_code:
        return "", ""
    parts = ts_code.split(".")
    if len(parts) == 2:
        sym = parts[0]
        suffix = parts[1].upper()
        exchange_map = {
            "SH": "SSE",
            "SZ": "SZSE",
            "BJ": "BSE",
        }
        exchange = exchange_map.get(suffix, suffix)
        return sym, exchange
    return ts_code, ""
