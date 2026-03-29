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
        if isinstance(limit, str) and limit != "all":
            result["limit"] = int(limit)
        else:
            result["limit"] = limit if isinstance(limit, str) else int(limit)
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


def maybe_markdown_response(
    data: Any,
    format: str = "json",
    accept: str = "",
) -> Any:
    """Return Markdown Response if requested, else return the raw data dict.

    Checks ``format`` query param and ``Accept`` header.  If either asks for
    Markdown and the payload contains a ``fact_markdown`` string, return a
    FastAPI ``Response`` with ``Content-Type: text/markdown``.

    Usage in route::

        @router.get("/stock/{symbol}")
        async def handler(symbol: str, format: str = "json",
                          accept: str = Header(default="")):
            result = await gateway.get_stock_fact_pack(symbol=symbol)
            md = maybe_markdown_response(result, format, accept)
            if md is not None:
                return md
            return rest_response(data=result, symbol=symbol, source="akshare")
    """
    wants_md = format.lower() == "markdown" or "text/markdown" in accept
    if not wants_md:
        return None

    md_content = ""
    if isinstance(data, dict):
        md_content = data.get("fact_markdown", "")

    if not md_content:
        # No markdown available — generate a minimal fallback
        md_content = _json_to_markdown_fallback(data)

    from fastapi.responses import Response
    return Response(content=md_content, media_type="text/markdown")


def _json_to_markdown_fallback(data: Any) -> str:
    """Convert a JSON-serialisable dict to a simple Markdown representation."""
    if not isinstance(data, dict):
        return str(data)

    lines: list[str] = []
    for key, value in data.items():
        if key in ("source_trace", "coverage", "missing_fields", "categories_fetched",
                    "categories_total", "elapsed_seconds", "fact_markdown"):
            continue  # skip meta fields in fallback
        if isinstance(value, dict):
            lines.append(f"## {key}\n")
            for k, v in value.items():
                if isinstance(v, (dict, list)):
                    lines.append(f"- **{k}**: `{type(v).__name__}`\n")
                else:
                    lines.append(f"- **{k}**: {v}\n")
            lines.append("\n")
        elif isinstance(value, list):
            lines.append(f"## {key}\n")
            for item in value[:10]:
                lines.append(f"- {item}\n")
            lines.append("\n")
        else:
            lines.append(f"- **{key}**: {value}\n")

    return "\n".join(lines) if lines else "# No data available"
