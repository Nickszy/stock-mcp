# src/server/domain/structured_data/normalize/company_profile.py
"""Normalizer for company profile data.

Maps source-specific fields from akshare and tushare into a unified
canonical schema for company basic information.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.server.utils.logger import logger

from .engine import FieldMapping, MISSING, Normalizer

# ---------------------------------------------------------------------------
# Canonical schema for company profile
# ---------------------------------------------------------------------------
# Business key format: {exchange}:{symbol}
# Example: SSE:600519

# Akshare field mapping (stock_individual_info_em returns key-value pairs)
_AKSHARE_FIELD_MAP = {
    "股票简称": "short_name",
    "行业": "industry",
    "上市时间": "listing_date",
    "总股本": "total_shares",
    "流通股": "float_shares",
}

# Tushare field mapping (stock_basic API)
_TUSHARE_FIELD_MAP = {
    "name": "short_name",
    "fullname": "full_name",
    "industry": "industry",
    "market": "market",
    "list_date": "listing_date",
    "curr_type": "currency",
    "area": "area",
    "cnspell": "cnspell",
    "enname": "en_name",
    "exchange": "exchange_src",
}


class CompanyProfileNormalizer(Normalizer):
    """Normalizer for company profile data dimension."""

    @property
    def dataset_key(self) -> str:
        return "company_profile"

    async def normalize(
        self,
        raw_data: Dict[str, Any],
        source: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Transform raw company profile data to canonical schema.

        Expected raw_data shapes:

        akshare: {"short_name": "贵州茅台", "industry": "白酒", ...}
                  or Asset properties dict from get_asset_info

        tushare: {"name": "贵州茅台", "fullname": "...", "list_date": "20010827", ...}
                  or Asset model_dump()
        """
        now = datetime.now(timezone.utc).isoformat()

        # Extract symbol and exchange from kwargs or raw_data
        symbol = kwargs.get("symbol", "")
        exchange = kwargs.get("exchange", "")

        if not symbol:
            ticker = raw_data.get("ticker", "")
            if ":" in ticker:
                exchange, symbol = ticker.split(":", 1)
            else:
                symbol = ticker

        # Build canonical result
        result: Dict[str, Any] = {
            "business_key": f"{exchange}:{symbol}" if exchange and symbol else "",
            "symbol": symbol,
            "exchange": exchange,
            "_source": source,
            "_normalized_at": now,
        }

        if source == "akshare":
            self._normalize_akshare(raw_data, result)
        elif source == "tushare":
            self._normalize_tushare(raw_data, result)
        else:
            # Generic: try to map fields directly
            self._normalize_generic(raw_data, result)

        return result

    def _normalize_akshare(self, raw: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Normalize akshare company profile data.

        Akshare returns data as either:
        1. Key-value pairs from stock_individual_info_em
        2. Asset model with properties dict
        """
        # If raw has 'properties' (from Asset model), flatten it
        props = raw.get("properties", {})
        data = {**raw}
        if props:
            for k, v in props.items():
                data[k] = v

        # Map akshare-specific fields
        for ak_key, canonical_key in _AKSHARE_FIELD_MAP.items():
            if ak_key in data and data[ak_key]:
                result[canonical_key] = str(data[ak_key]).strip()

        # Also try English field names (from Asset model)
        if "name" in data and "short_name" not in result:
            result["short_name"] = str(data["name"]).strip()

        # Total/float shares — convert numeric strings to float
        for canonical_key in ("total_shares", "float_shares"):
            val = result.get(canonical_key)
            if val is not None:
                result[canonical_key] = _safe_float(val)

        # Industry from English key (only if not already set by Chinese mapping)
        if "industry" not in result and "industry" in data and data["industry"]:
            result["industry"] = str(data["industry"]).strip()

    def _normalize_tushare(self, raw: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Normalize tushare company profile data (stock_basic format)."""
        for ts_key, canonical_key in _TUSHARE_FIELD_MAP.items():
            if ts_key in raw and raw[ts_key]:
                val = raw[ts_key]
                # Convert NaN/None to empty
                if isinstance(val, float) and val != val:  # NaN check
                    continue
                result[canonical_key] = str(val).strip() if not isinstance(val, (int, float)) else val

        # Parse listing_date to ISO format if YYYYMMDD
        ld = result.get("listing_date")
        if ld and isinstance(ld, str) and len(ld) == 8 and ld.isdigit():
            result["listing_date"] = f"{ld[:4]}-{ld[4:6]}-{ld[6:8]}"

    def _normalize_generic(self, raw: Dict[str, Any], result: Dict[str, Any]) -> None:
        """Generic normalization — pass through common field names."""
        direct_fields = [
            "short_name", "full_name", "industry", "listing_date",
            "total_shares", "float_shares", "currency", "area",
            "market", "en_name", "description",
        ]
        for field in direct_fields:
            if field in raw and raw[field] is not None and field not in result:
                result[field] = raw[field]


def _safe_float(value: Any) -> Any:
    """Convert value to float, stripping locale formatting. Returns original on failure."""
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return value
