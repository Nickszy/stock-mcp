# src/server/api/routes/preview.py
"""Data Preview Workbench API routes.

Provides:
- GET  /api/meta               — Service metadata (moved from root)
- GET  /api/v1/preview/catalog — Structured catalog of all gateway methods
- POST /api/v1/preview/query  — Multi-source dispatch with timing
- GET  /                       — HTML workbench page
"""

import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.server.core.dependencies import Container
from src.server.domain.market_gateway import _TICKER_METHODS, _MARKET_METHODS
from src.server.mcp.registry import get_enabled_tool_count

router = APIRouter()


# --- Request / Response Models ---

class PreviewQueryRequest(BaseModel):
    method: str
    params: Dict[str, Any] = {}
    sources: List[str] = ["auto"]


# --- Category grouping ---

_METHOD_CATEGORIES: Dict[str, List[str]] = {
    "Fundamental": [
        "get_financials", "get_financial_statements", "get_mainbz_info",
        "get_shareholder_info", "get_dividend_info", "get_forecast_info",
        "get_valuation_metrics",
    ],
    "US Fundamental": [
        "get_earnings_history", "get_cash_flow_quality",
        "get_us_valuation_metrics", "get_us_institutional_holdings",
        "get_us_company_profile", "get_us_analyst_recommendations",
        "get_us_revenue_segments", "get_us_insider_trading",
        "get_us_share_statistics", "get_us_financial_health",
    ],
    "US Technical": [
        "get_us_price_history", "get_us_volume_analysis",
    ],
    "Money Flow": [
        "get_money_flow", "get_chip_distribution",
        "get_stock_northbound_holdings", "get_stock_top10_shareholders",
        "get_stock_shareholder_changes",
    ],
    "Macro": [
        "get_north_bound_flow", "get_money_supply", "get_inflation_data",
        "get_pmi_data", "get_gdp_data", "get_social_financing",
        "get_interest_rates", "get_market_liquidity", "get_market_money_flow",
        "get_ggt_daily", "get_dragon_tiger_list", "get_block_trade",
        "get_margin_trading",
    ],
    "Sector": [
        "resolve_sector", "get_sector_trend",
        "get_sector_money_flow_history", "get_sector_valuation_metrics",
        "get_industry_ranking", "get_concept_ranking", "get_style_rotation",
    ],
    "Factor": [
        "get_stock_factors", "get_stock_correlation",
        "get_factor_ranking", "get_stock_factor_screen",
    ],
}

# Reverse lookup: method -> category
_METHOD_TO_CATEGORY: Dict[str, str] = {}
for _cat, _methods in _METHOD_CATEGORIES.items():
    for _m in _methods:
        _METHOD_TO_CATEGORY[_m] = _cat


def _get_adapters_by_name() -> Dict[str, Any]:
    """Build {adapter_name: adapter} dict from gateway."""
    gateway = Container.market_gateway()
    result: Dict[str, Any] = {}
    for _source, adapter in gateway.adapters.items():
        name = adapter.name if hasattr(adapter, "name") else _source.value
        result[name] = adapter
    return result


# --- Endpoints ---

@router.get("/api/meta")
async def api_meta():
    """Service metadata (moved from root /)."""
    return {
        "service": "Stock Tool Server",
        "version": "1.0.0",
        "description": "Financial data service with dual protocol support",
        "protocols": {
            "restful_api": {
                "description": "Standard HTTP JSON API",
                "base_url": "/api/v1",
                "documentation": {
                    "swagger_ui": "/docs",
                    "redoc": "/redoc",
                    "openapi_json": "/openapi.json",
                },
            },
            "mcp": {
                "description": "Model Context Protocol (for AI Agents)",
                "endpoint": "/mcp",
                "protocol": "Streamable HTTP (JSON-RPC 2.0)",
                "tools_count": get_enabled_tool_count(),
            },
        },
        "health_check": "/health",
        "supported_markets": ["US Stocks", "China A-Shares", "Cryptocurrency"],
        "supported_exchanges": ["NASDAQ", "NYSE", "SSE", "SZSE", "BINANCE", "OKX"],
    }


@router.get("/api/v1/preview/catalog")
async def preview_catalog():
    """Return structured catalog of all available gateway methods."""
    adapters_by_name = _get_adapters_by_name()
    all_methods: Dict[str, Dict[str, Any]] = {}

    for method_name in sorted(_TICKER_METHODS):
        available = [
            name for name, adapter in adapters_by_name.items()
            if hasattr(adapter, method_name) and callable(getattr(adapter, method_name))
        ]
        all_methods[method_name] = {
            "name": method_name,
            "type": "ticker",
            "sources": available,
        }

    for method_name in sorted(_MARKET_METHODS):
        available = [
            name for name, adapter in adapters_by_name.items()
            if hasattr(adapter, method_name) and callable(getattr(adapter, method_name))
        ]
        all_methods[method_name] = {
            "name": method_name,
            "type": "market",
            "sources": available,
        }

    # Group by category
    categories_dict: Dict[str, List] = {}
    uncategorized: List[Dict] = []
    for method_name, method_info in all_methods.items():
        cat = _METHOD_TO_CATEGORY.get(method_name)
        if cat:
            categories_dict.setdefault(cat, []).append(method_info)
        else:
            uncategorized.append(method_info)

    categories = [
        {"name": cat, "methods": methods}
        for cat, methods in categories_dict.items()
    ]
    if uncategorized:
        categories.append({"name": "Other", "methods": uncategorized})

    return {
        "total_methods": len(all_methods),
        "ticker_methods": len(_TICKER_METHODS),
        "market_methods": len(_MARKET_METHODS),
        "categories": categories,
    }


@router.post("/api/v1/preview/query")
async def preview_query(request: PreviewQueryRequest):
    """Execute a gateway method against one or more data sources."""
    method_name = request.method
    params = request.params
    sources = request.sources or ["auto"]

    if method_name not in _TICKER_METHODS and method_name not in _MARKET_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown method: {method_name}",
        )

    gateway = Container.market_gateway()
    adapters_by_name = _get_adapters_by_name()
    results: Dict[str, Any] = {}

    for source_name in sources:
        t0 = time.perf_counter()
        try:
            if source_name == "auto":
                method = getattr(gateway, method_name)
                data = await method(**params)
                elapsed = (time.perf_counter() - t0) * 1000
                results["auto"] = {
                    "data": data,
                    "source": "auto",
                    "elapsed_ms": round(elapsed, 1),
                    "error": None,
                }
            else:
                adapter = adapters_by_name.get(source_name)
                if not adapter:
                    elapsed = (time.perf_counter() - t0) * 1000
                    results[source_name] = {
                        "data": None,
                        "source": source_name,
                        "elapsed_ms": round(elapsed, 1),
                        "error": f"Source not found: {source_name}. "
                                 f"Available: {list(adapters_by_name.keys())}",
                    }
                    continue

                method = getattr(adapter, method_name, None)
                if not method or not callable(method):
                    elapsed = (time.perf_counter() - t0) * 1000
                    results[source_name] = {
                        "data": None,
                        "source": source_name,
                        "elapsed_ms": round(elapsed, 1),
                        "error": f"Method {method_name} not supported by {source_name}",
                    }
                    continue

                data = await method(**params)
                elapsed = (time.perf_counter() - t0) * 1000
                results[source_name] = {
                    "data": data,
                    "source": source_name,
                    "elapsed_ms": round(elapsed, 1),
                    "error": None,
                }
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            results[source_name] = {
                "data": None,
                "source": source_name,
                "elapsed_ms": round(elapsed, 1),
                "error": str(e),
            }

    return {"method": method_name, "results": results}


# --- Root page ---

_PLACEHOLDER_HTML = """<!DOCTYPE html>
<html><head><title>Stock MCP Preview</title></head>
<body><h1>Loading...</h1></body></html>"""


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def preview_page():
    """Serve the data preview workbench page."""
    try:
        from src.server.api.routes.preview_template import PREVIEW_HTML
        return HTMLResponse(content=PREVIEW_HTML)
    except ImportError:
        return HTMLResponse(content=_PLACEHOLDER_HTML)


@router.get("/preview", response_class=HTMLResponse, include_in_schema=False)
async def preview_page_alt():
    """Alternate path to workbench."""
    return await preview_page()
