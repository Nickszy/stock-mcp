# src/server/domain/response_contract.py
"""Unified response contract for REST API and MCP tools.

All data-returning endpoints (REST & MCP) share the same core structure
via ``create_data_response``. REST endpoints return this directly; MCP
tools wrap it inside the existing ``artifact`` envelope.

Three temporal shapes are supported via optional metadata fields:
- Period-based:  ``period`` (quarterly / annual / all)
- Time-series:   ``start_date`` + ``end_date`` + optional ``interval``
- Snapshot:      ``date``
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union


def create_data_response(
    data: Any,
    *,
    symbol: Optional[str] = None,
    source: Optional[str] = None,
    period: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    interval: Optional[str] = None,
    limit: Optional[Union[int, str]] = None,
    date: Optional[str] = None,
    **extra_metadata: Any,
) -> Dict[str, Any]:
    """Build a standardised data payload shared by REST and MCP layers.

    Parameters
    ----------
    data:
        The core payload (list, dict, scalar …).
    symbol:
        Ticker / identifier the data refers to.
    source:
        Data provider name (``"akshare"``, ``"yahoo"``, …).
    period:
        ``"quarterly"`` | ``"annual"`` | ``"all"`` — for period-based data.
    start_date / end_date:
        ISO date strings for time-series data.
    interval:
        Bar interval (``"1d"``, ``"1h"``, …) for time-series data.
    limit:
        Max number of records requested / returned.
    date:
        ISO date string for point-in-time snapshots.
    **extra_metadata:
        Any additional top-level keys to merge into the response.

    Returns
    -------
    dict
        A response dict with at minimum ``source`` and ``data`` keys.
    """
    result: Dict[str, Any] = {}

    if symbol is not None:
        result["symbol"] = symbol
    if period is not None:
        result["period"] = period
    if limit is not None:
        result["limit"] = int(limit)
    if start_date is not None:
        result["start_date"] = start_date
    if end_date is not None:
        result["end_date"] = end_date
    if interval is not None:
        result["interval"] = interval
    if date is not None:
        result["date"] = date

    result["source"] = {
        "provider": source or "unknown",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    result["data"] = data

    result.update(extra_metadata)
    return result


def rest_response(
    data: Any,
    *,
    symbol: Optional[str] = None,
    source: Optional[str] = None,
    **contract_kwargs: Any,
) -> Dict[str, Any]:
    """Convenience wrapper for REST endpoints.

    Returns the standard contract wrapped in the existing REST envelope
    ``{"code": 0, "message": "success", "data": <contract>}``.

    This keeps backward compatibility with the money_flow route pattern
    while embedding the full contract inside ``data``.
    """
    contract = create_data_response(
        data, symbol=symbol, source=source, **contract_kwargs
    )
    return {"code": 0, "message": "success", "data": contract}
