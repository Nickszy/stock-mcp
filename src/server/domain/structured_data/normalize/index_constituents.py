# src/server/domain/structured_data/normalize/index_constituents.py
"""Normalizer for index constituents (指数成分与权重) data.

Maps source-specific fields from akshare into a unified canonical schema
for index constituent listings and their weights.

Canonical schema:
    business_key: {index_code}:{effective_date}
    index_code, index_name, effective_date,
    constituents: [
        {
            symbol, exchange, weight, constituent_name,
            currency, market
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

# Akshare index_stock_cons_csindex output
_CONSTITUENTS_MAP = [
    ("日期", "effective_date", str, MISSING),
    ("指数代码", "index_code", str, MISSING),
    ("指数名称", "index_name", str, MISSING),
    ("成分券代码", "symbol", str, MISSING),
    ("成分券名称", "constituent_name", str, MISSING),
    ("交易所", "market", str, MISSING),
]

# Akshare index_stock_cons_weight_csindex output
_WEIGHTS_MAP = [
    ("日期", "effective_date", str, MISSING),
    ("指数代码", "index_code", str, MISSING),
    ("指数名称", "index_name", str, MISSING),
    ("成分券代码", "symbol", str, MISSING),
    ("成分券名称", "constituent_name", str, MISSING),
    ("权重", "weight", float, MISSING),
]


def _infer_exchange(market: str, symbol: str) -> str:
    """Infer exchange from market field or symbol suffix."""
    if not market:
        return ""
    m = str(market).upper()
    if "上海" in m or "SH" in m:
        return "SSE"
    if "深圳" in m or "SZ" in m:
        return "SZSE"
    if "北京" in m or "BJ" in m:
        return "BSE"
    # Fallback: check symbol suffix
    if symbol.endswith(".SH"):
        return "SSE"
    if symbol.endswith(".SZ"):
        return "SZSE"
    return ""


class IndexConstituentsNormalizer(Normalizer):
    """Normalizer for index constituents (指数成分与权重) data dimension."""

    @property
    def dataset_key(self) -> str:
        return "index_constituents"

    async def normalize(
        self,
        raw_data: Dict[str, Any],
        source: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """Transform raw index constituent data to canonical schema.

        Expected raw_data shapes:

        akshare:
            {
                "constituents": {"data": [...], "index_code": "000300"},
                "weights": {"data": [...], "index_code": "000300"},
            }

        Or single source:
            {
                "data": [...],
                "index_code": "000300",
            }
        """
        now = datetime.now(timezone.utc).isoformat()

        index_code = kwargs.get("index_code", "") or kwargs.get("symbol", "")

        # Extract data sections
        constituents_raw = raw_data.get("constituents", {})
        weights_raw = raw_data.get("weights", {})

        # If no sections, treat entire raw_data as constituents
        if not constituents_raw and not weights_raw:
            constituents_raw = raw_data

        # Get constituent rows
        const_rows = (
            constituents_raw.get("data", [])
            if isinstance(constituents_raw, dict)
            else constituents_raw
        )
        weight_rows = (
            weights_raw.get("data", [])
            if isinstance(weights_raw, dict)
            else weights_raw
        )

        # Extract index_code from data if not in kwargs
        if not index_code:
            if isinstance(constituents_raw, dict):
                index_code = constituents_raw.get("index_code", "")
            if not index_code and const_rows and isinstance(const_rows[0], dict):
                index_code = str(const_rows[0].get("指数代码", const_rows[0].get("index_code", "")))

        # Build weight lookup: symbol -> weight
        weight_lookup: Dict[str, float] = {}
        if weight_rows:
            mapping = FieldMapping(_WEIGHTS_MAP)
            for row in weight_rows:
                if not isinstance(row, dict):
                    continue
                mapped = mapping.apply(row)
                sym = str(mapped.get("symbol", ""))
                w = mapped.get("weight")
                if sym and w is not None:
                    weight_lookup[sym] = w

        # Normalize constituent rows
        constituents: List[Dict[str, Any]] = []
        effective_date = ""

        if source in ("akshare", "tushare", "baostock"):
            const_mapping = FieldMapping(_CONSTITUENTS_MAP)
            for row in const_rows:
                if not isinstance(row, dict):
                    continue
                mapped = const_mapping.apply(row)
                sym = str(mapped.get("symbol", ""))
                market = str(mapped.get("market", ""))
                exchange = _infer_exchange(market, sym)

                # Clean symbol (remove exchange suffix)
                clean_sym = sym.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")

                entry: Dict[str, Any] = {
                    "symbol": clean_sym,
                    "exchange": exchange,
                    "constituent_name": mapped.get("constituent_name", ""),
                    "market": market,
                    "currency": "CNY",
                }
                # Attach weight from lookup
                entry["weight"] = weight_lookup.get(sym) or weight_lookup.get(clean_sym)

                constituents.append(entry)

                # Track effective_date
                ed = mapped.get("effective_date", "")
                if ed and not effective_date:
                    effective_date = str(ed)
        else:
            # Generic passthrough
            for row in const_rows:
                if isinstance(row, dict):
                    constituents.append(row)
            if const_rows and isinstance(const_rows[0], dict):
                effective_date = str(const_rows[0].get("effective_date", ""))

        index_name = ""
        if const_rows and isinstance(const_rows[0], dict):
            index_name = str(const_rows[0].get("指数名称", const_rows[0].get("index_name", "")))

        biz_key = f"{index_code}:{effective_date}" if index_code and effective_date else ""

        return {
            "business_key": biz_key,
            "index_code": index_code,
            "index_name": index_name,
            "effective_date": effective_date,
            "constituents": constituents,
            "constituent_count": len(constituents),
            "_source": source,
            "_normalized_at": now,
        }
