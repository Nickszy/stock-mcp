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

    # Auto-inherit source and symbol from data dict when not explicitly provided.
    # This prevents provider=unknown when routes call rest_response(data=result)
    # without passing source= — the adapter result already contains the real source.
    if source is None and isinstance(data, dict):
        _src = data.get("source")
        if isinstance(_src, str) and _src:
            source = _src
    if symbol is None and isinstance(data, dict):
        _sym = data.get("symbol") or data.get("ticker") or data.get("fund_code")
        if isinstance(_sym, str) and _sym:
            symbol = _sym

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
    """Build a flat REST envelope for API endpoints.

    Returns ``{"code": 0, "message": "success", "data": <flat_payload>}``.

    The payload is *flattened*: metadata (source, symbol, etc.) sits at the
    same level as the actual data fields.  No inner ``data`` wrapping —
    front-end simply accesses ``response.data.flow``, ``response.data.income``,
    etc.  without double-nesting.

    When *data* is a dict its keys are spread directly into the payload
    alongside metadata.  When *data* is a list or scalar it is placed under
    a ``"data"`` key (since it can't be spread).
    """
    payload: Dict[str, Any] = {}

    # Metadata fields
    if symbol is not None:
        payload["symbol"] = symbol
    for k, v in contract_kwargs.items():
        if v is not None:
            payload[k] = v

    # Source
    provider = source
    if provider is None and isinstance(data, dict):
        _src = data.get("source")
        if isinstance(_src, str) and _src:
            provider = _src
        elif isinstance(_src, dict):
            provider = _src.get("provider")
    if symbol is None and isinstance(data, dict):
        _sym = data.get("symbol") or data.get("ticker") or data.get("fund_code")
        if isinstance(_sym, str) and _sym:
            payload["symbol"] = _sym
    payload["source"] = {
        "provider": provider or "unknown",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    # Core data: spread dict keys or wrap non-dict
    if isinstance(data, dict):
        payload.update(data)
    else:
        payload["data"] = data

    return {"code": 0, "message": "success", "data": payload}


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
        md_content = json_to_markdown(data)

    from fastapi.responses import Response
    return Response(content=md_content, media_type="text/markdown")


def json_to_markdown(data: Any, title: str = "") -> str:
    """Convert a JSON-serialisable structure to a rich Markdown representation.

    Handles common REST API response shapes:
    - list[dict]  → markdown table
    - dict[dict]  → sectioned sub-tables
    - dict        → key-value pairs (scalar values) + nested sections
    - list        → bulleted list
    """
    if not isinstance(data, dict):
        return str(data)

    lines: list[str] = []

    if title:
        lines.append(f"# {title}\n")

    # Separate scalar fields from nested structures
    scalar_fields: list[tuple[str, Any]] = []
    nested_fields: list[tuple[str, Any]] = []

    for key, value in data.items():
        if key in ("source_trace", "coverage", "missing_fields", "categories_fetched",
                    "categories_total", "elapsed_seconds", "fact_markdown"):
            continue  # skip internal meta fields
        if isinstance(value, (dict, list)):
            nested_fields.append((key, value))
        else:
            scalar_fields.append((key, value))

    # Render scalar fields as a simple table
    if scalar_fields:
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        for k, v in scalar_fields:
            lines.append(f"| {k} | {v} |")
        lines.append("")

    # Render nested structures
    for key, value in nested_fields:
        lines.append(f"## {_pretty_key(key)}\n")

        if isinstance(value, list):
            if value and isinstance(value[0], dict):
                lines.append(_list_of_dicts_to_table(value))
            else:
                for item in value[:50]:
                    lines.append(f"- {item}")
                if len(value) > 50:
                    lines.append(f"- ... ({len(value) - 50} more items)")
            lines.append("")

        elif isinstance(value, dict):
            # Check if all values are dicts (dict of dicts → sub-tables)
            sub_values = list(value.values())
            if sub_values and all(isinstance(v, dict) for v in sub_values):
                for sub_key, sub_dict in value.items():
                    lines.append(f"### {sub_key}\n")
                    if sub_dict:
                        lines.append(_dict_to_kv_table(sub_dict))
                    lines.append("")
            else:
                lines.append(_dict_to_kv_table(value))
                lines.append("")

    return "\n".join(lines) if lines else "# No data available"


def _pretty_key(key: str) -> str:
    """Convert snake_case key to Title Case."""
    return key.replace("_", " ").title()


def _dict_to_kv_table(d: dict, max_depth: int = 3) -> str:
    """Render a dict as a key-value markdown table."""
    lines: list[str] = []
    lines.append("| Key | Value |")
    lines.append("|-----|-------|")
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            v_str = f"`{type(v).__name__}({len(v)})`"
        else:
            v_str = str(v)
        # Escape pipe characters
        v_str = v_str.replace("|", "\\|")
        lines.append(f"| {k} | {v_str} |")
    return "\n".join(lines)


def _list_of_dicts_to_table(items: list) -> str:
    """Render a list of dicts as a markdown table."""
    if not items:
        return "*No data*"

    # Collect all keys preserving order from first item
    keys: list[str] = []
    for item in items[:20]:
        for k in item:
            if k not in keys:
                keys.append(k)

    lines: list[str] = []
    lines.append("| " + " | ".join(keys) + " |")
    lines.append("| " + " | ".join("---" for _ in keys) + " |")

    for item in items[:50]:
        row = []
        for k in keys:
            v = item.get(k, "")
            if isinstance(v, (dict, list)):
                v = f"`{type(v).__name__}`"
            else:
                v = str(v).replace("|", "\\|")
                # Truncate long values
                if len(v) > 80:
                    v = v[:77] + "..."
            row.append(v)
        lines.append("| " + " | ".join(row) + " |")

    if len(items) > 50:
        lines.append(f"\n*... and {len(items) - 50} more rows*")

    return "\n".join(lines)
