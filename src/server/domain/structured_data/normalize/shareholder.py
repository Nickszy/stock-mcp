# src/server/domain/structured_data/normalize/shareholder.py
"""Normalizer for shareholder (股东与持股变化) data.

Maps source-specific fields from tushare into a unified canonical schema
for shareholder information including top 10 holders, float holders,
holder count trends, and insider trades.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger

from .engine import FieldMapping, MISSING, Normalizer

# ---------------------------------------------------------------------------
# Source field mappings
# ---------------------------------------------------------------------------

# Tushare top10_holders fields
_TOP10_HOLDERS_MAP = [
    ("ts_code", "ts_code", str, MISSING),
    ("ann_date", "ann_date", str, MISSING),
    ("end_date", "end_date", str, MISSING),
    ("holder_name", "holder_name", str, MISSING),
    ("hold_amount", "hold_amount", float, MISSING),
    ("hold_ratio", "hold_ratio", float, MISSING),
]

# Tushare top10_floatholders fields
_TOP10_FLOAT_MAP = [
    ("ts_code", "ts_code", str, MISSING),
    ("ann_date", "ann_date", str, MISSING),
    ("end_date", "end_date", str, MISSING),
    ("holder_name", "holder_name", str, MISSING),
    ("hold_amount", "hold_amount", float, MISSING),
    ("hold_ratio", "hold_ratio", float, MISSING),
]

# Tushare stk_holdernumber fields
_HOLDER_NUMBER_MAP = [
    ("ts_code", "ts_code", str, MISSING),
    ("ann_date", "ann_date", str, MISSING),
    ("end_date", "end_date", str, MISSING),
    ("holder_num", "holder_num", float, MISSING),
]

# Tushare stk_holdertrade fields
_HOLDER_TRADE_MAP = [
    ("ts_code", "ts_code", str, MISSING),
    ("ann_date", "ann_date", str, MISSING),
    ("holder_name", "holder_name", str, MISSING),
    ("trade_type", "trade_type", str, MISSING),
    ("vol", "vol", float, MISSING),
    ("change_vol", "change_vol", float, MISSING),
]


def _format_dates(rows: List[Dict[str, Any]], date_fields: tuple = ("end_date", "ann_date")) -> None:
    """Convert YYYYMMDD dates to YYYY-MM-DD in-place."""
    for row in rows:
        if not isinstance(row, dict):
            continue
        for field in date_fields:
            val = row.get(field)
            if val and isinstance(val, str) and len(val) == 8 and val.isdigit():
                row[field] = f"{val[:4]}-{val[4:6]}-{val[6:8]}"


def _parse_ts_code(ts_code: str) -> tuple:
    """Parse tushare ts_code like '600519.SH' to (symbol, exchange)."""
    if not ts_code:
        return "", ""
    parts = ts_code.split(".")
    if len(parts) == 2:
        sym = parts[0]
        suffix = parts[1].upper()
        exchange_map = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
        exchange = exchange_map.get(suffix, suffix)
        return sym, exchange
    return ts_code, ""


class ShareholderNormalizer(Normalizer):
    """Normalizer for shareholder (股东与持股变化) data dimension."""

    @property
    def dataset_key(self) -> str:
        return "shareholder"

    async def normalize(
        self,
        raw_data: Dict[str, Any],
        source: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Transform raw shareholder data to canonical schema.

        Expected raw_data shapes:

        tushare:
            {
                "ts_code": "600519.SH",
                "data": {
                    "top10_holders": [...],
                    "top10_floatholders": [...],
                    "holder_number": [...],
                    "holder_trade": [...]
                }
            }
        """
        now = datetime.now(timezone.utc).isoformat()

        # Extract symbol and exchange
        symbol = kwargs.get("symbol", "")
        exchange = kwargs.get("exchange", "")

        if not symbol:
            ts_code = raw_data.get("ts_code", "")
            if ts_code:
                symbol, exchange = _parse_ts_code(ts_code)

        # Extract data sections
        raw_sections = raw_data.get("data", raw_data)

        # Determine report_period from end_date of first holder entry
        report_period = kwargs.get("report_period", "")
        if not report_period:
            all_holders = raw_sections.get("top10_holders", [])
            if all_holders and isinstance(all_holders[0], dict):
                ed = str(all_holders[0].get("end_date", ""))
                report_period = ed.replace("-", "")[:8]

        # Determine holder_type for business key
        holder_type = kwargs.get("holder_type", "all")

        # Normalize each section based on source
        if source in ("tushare", "baostock"):
            top10 = self._normalize_section(raw_sections.get("top10_holders", []), _TOP10_HOLDERS_MAP)
            top10_float = self._normalize_section(raw_sections.get("top10_floatholders", []), _TOP10_FLOAT_MAP)
            holder_number = self._normalize_section(raw_sections.get("holder_number", []), _HOLDER_NUMBER_MAP)
            holder_trade = self._normalize_section(raw_sections.get("holder_trade", []), _HOLDER_TRADE_MAP)
        else:
            top10 = raw_sections.get("top10_holders", [])
            top10_float = raw_sections.get("top10_floatholders", [])
            holder_number = raw_sections.get("holder_number", [])
            holder_trade = raw_sections.get("holder_trade", [])

        biz_key = (
            f"{exchange}:{symbol}:{report_period}:{holder_type}"
            if exchange and symbol and report_period
            else ""
        )

        result: Dict[str, Any] = {
            "business_key": biz_key,
            "symbol": symbol,
            "exchange": exchange,
            "report_period": report_period,
            "top10_holders": top10,
            "top10_floatholders": top10_float,
            "holder_number": holder_number,
            "holder_trade": holder_trade,
            "_source": source,
            "_normalized_at": now,
        }

        return result

    def _normalize_section(
        self, raw_rows: List[Dict[str, Any]], field_map: list
    ) -> List[Dict[str, Any]]:
        """Normalize a section of shareholder data using field mapping."""
        mapping = FieldMapping(field_map)
        normalized = []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            mapped = mapping.apply(row)
            _format_dates([mapped])
            normalized.append(mapped)
        return normalized
