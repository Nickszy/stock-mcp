# src/server/domain/structured_data/canonical_reader.py
"""Canonical-first data bridge -- source attribution.

When canonical data exists, return it directly (high quality, validated,
structured data).  When canonical is not available, fall back to live
gateway call.  Response includes source attribution.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.server.api.routes.structured_data import _get_canonical_repo
from src.server.utils.logger import logger


async def read_canonical_financial_statements(
    dataset_key: str,
    symbol: str,
    exchange: str,
    limit: int = 10,
) -> Optional[List[Dict[str, Any]]]:
    """Read canonical financial statements from canonical_records.

    Queries by business_key prefix (exchange:symbol) and returns structured data,
    or None if no canonical data exists.
    """
    canonical_repo = _get_canonical_repo()
    if canonical_repo is None:
        return None

    try:
        records = await canonical_repo.find_by_symbol(
            dataset_key=dataset_key,
            exchange=exchange,
            symbol=symbol,
            limit=limit,
        )
    except Exception:
        logger.warning(
            "canonical_reader: query failed",
            dataset_key=dataset_key,
            exchange=exchange,
            symbol=symbol,
            exc_info=True,
        )
        return None

    if not records:
        return None

    records.sort(
        key=lambda r: _extract_report_period(r.get("business_key", "")),
        reverse=True,
    )

    results: List[Dict[str, Any]] = []
    for rec in records:
        data = rec.get("data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("canonical_reader: JSON parse failed", business_key=bk)
        bk = rec.get("business_key", "")
        period = _extract_report_period(bk)
        results.append({
            "report_period": period,
            "data": data,
            "version": rec.get("version"),
            "source_type": "canonical",
            "published_at": str(rec.get("published_at", "")),
            "provider": rec.get("source", ""),
        })

    return results if results else None


def _extract_report_period(business_key: str) -> str:
    """Extract report period from business_key like SSE:600519:20240930:all."""
    parts = business_key.split(":")
    if len(parts) >= 3:
        return parts[2]
    return ""


def build_business_key(exchange: str, symbol: str, report_period: str) -> str:
    """Build canonical lookup business key."""
    if not report_period:
        return f"{exchange}:{symbol}"
    return f"{exchange}:{symbol}:{report_period}:all"
