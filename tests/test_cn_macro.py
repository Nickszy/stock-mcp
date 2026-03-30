# tests/test_cn_macro.py
"""Tests for China macro data MCP tools (COL-243).

Covers:
  - Adapter: get_trade_balance structure
  - Gateway: get_trade_balance in _MARKET_METHODS
  - MCP tools: cn-macro group count
  - REST routes: cn-macro endpoints

Run: uv run pytest tests/test_cn_macro.py -v
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

sys.path.insert(0, ".")


class MockCache:
    _store: Dict[str, Any] = {}

    async def get(self, key: str):
        return MockCache._store.get(key)

    async def set(self, key: str, value: Any, ttl: int = 0):
        MockCache._store[key] = value


@pytest.fixture
def mock_cache():
    MockCache._store = {}
    return MockCache()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# =====================================================================
# Adapter: get_trade_balance
# =====================================================================


class TestTradeBalanceAdapter:
    """Verify get_trade_balance adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_trade_balance_structure(self, adapter):
        mock_df = pd.DataFrame({
            "日期": ["2026-02-01", "2026-01-01", "2025-12-01"],
            "trade_balance": [820.0, 750.0, 680.0],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_trade_balance(months=12))

        assert result["source"] == "akshare"
        assert len(result["data"]) == 3

    def test_trade_balance_empty(self, adapter):
        async def mock_run(func, *args, **kwargs):
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_trade_balance())

        assert result["data"] == []

    def test_trade_balance_api_failure(self, adapter):
        async def mock_run(func, *args, **kwargs):
            raise RuntimeError("API down")

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_trade_balance())

        assert result["data"] == []
        assert "error" in result


# =====================================================================
# Gateway: _MARKET_METHODS
# =====================================================================


class TestCnMacroGateway:
    """Verify trade_balance is in _MARKET_METHODS."""

    def test_trade_balance_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_trade_balance" in _MARKET_METHODS

    def test_existing_macro_methods_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        for method in [
            "get_money_supply", "get_inflation_data", "get_pmi_data",
            "get_gdp_data", "get_social_financing", "get_interest_rates",
        ]:
            assert method in _MARKET_METHODS, f"{method} not in _MARKET_METHODS"


# =====================================================================
# Registry: cn-macro tool group
# =====================================================================


class TestCnMacroRegistry:
    """Verify cn-macro tool group registration."""

    def test_cn_macro_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        cn = [g for g in TOOL_GROUPS if g.name == "cn-macro"]
        assert len(cn) == 1
        assert cn[0].count == 9
        assert cn[0].enabled is True

    def test_total_tool_count_increased(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total >= 127, f"Expected >= 127, got {total}"


# =====================================================================
# MCP Tool registration
# =====================================================================


class TestCnMacroToolRegistration:
    """Verify cn-macro tools register without error."""

    def test_register_cn_macro_tools_succeeds(self):
        from src.server.mcp.tools.cn_macro_tools import register_cn_macro_tools
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_cn_macro_tools(mcp)

    def test_tool_count_matches_registry(self):
        from src.server.mcp.registry import TOOL_GROUPS
        cn = [g for g in TOOL_GROUPS if g.name == "cn-macro"]
        assert len(cn) == 1
        assert cn[0].count == 9


# =====================================================================
# REST Route: cn-macro endpoints
# =====================================================================


class TestCnMacroRoutes:
    """Verify REST route module loads."""

    def test_router_has_correct_prefix(self):
        from src.server.api.routes.cn_macro import router
        assert router.prefix == "/api/v1/cn-macro"

    def test_router_has_routes(self):
        from src.server.api.routes.cn_macro import router
        route_paths = [r.path for r in router.routes]
        # Routes include the prefix
        expected_suffixes = [
            "/gdp", "/cpi", "/ppi", "/pmi",
            "/money-supply", "/interest-rates",
            "/trade-balance", "/social-financing", "/overview",
        ]
        for suffix in expected_suffixes:
            full = f"/api/v1/cn-macro{suffix}"
            assert full in route_paths, f"Missing route {full}"

    @pytest.mark.asyncio
    async def test_cpi_and_ppi_routes_return_filtered_payloads(self):
        from src.server.api.routes import cn_macro as route_mod

        mock_result = {
            "data": {
                "CPI": [{"month": "202602", "nt_yoy": 0.7}],
                "PPI": [{"month": "202602", "ppi_yoy": -2.5}],
            },
            "source": "akshare",
        }

        with patch.object(route_mod.money_flow_use_cases, "get_inflation_data", AsyncMock(return_value=mock_result)):
            cpi_resp = await route_mod.get_cn_cpi(12)
            ppi_resp = await route_mod.get_cn_ppi(12)

        assert cpi_resp["data"]["cpi"] == mock_result["data"]["CPI"]
        assert ppi_resp["data"]["ppi"] == mock_result["data"]["PPI"]

    @pytest.mark.asyncio
    async def test_cpi_ppi_lowercase_fallback(self):
        from src.server.api.routes import cn_macro as route_mod

        mock_result = {
            "data": {
                "cpi": [{"month": "202601", "nt_yoy": 0.5}],
                "ppi": [{"month": "202601", "ppi_yoy": -1.2}],
            },
            "source": "akshare",
        }

        with patch.object(route_mod.money_flow_use_cases, "get_inflation_data", AsyncMock(return_value=mock_result)):
            cpi_resp = await route_mod.get_cn_cpi(12)
            ppi_resp = await route_mod.get_cn_ppi(12)

        assert cpi_resp["data"]["cpi"] == mock_result["data"]["cpi"]
        assert ppi_resp["data"]["ppi"] == mock_result["data"]["ppi"]


# =====================================================================
# Regression: _pick_trade_balance must not raise NameError
# =====================================================================


class TestTradeBalanceHelpers:
    """Verify _pick_trade_balance / _to_float work at runtime."""

    def test_pick_trade_balance_prefers_named_key(self):
        from src.server.mcp.tools.cn_macro_tools import _pick_trade_balance
        row = {"trade_balance": 820.5, "其他": 999}
        assert _pick_trade_balance(row) == 820.5

    def test_pick_trade_balance_chinese_key(self):
        from src.server.mcp.tools.cn_macro_tools import _pick_trade_balance
        row = {"贸易差额": 750.0}
        assert _pick_trade_balance(row) == 750.0

    def test_pick_trade_balance_empty_row(self):
        from src.server.mcp.tools.cn_macro_tools import _pick_trade_balance
        assert _pick_trade_balance({}) is None

    def test_pick_trade_balance_non_numeric_value(self):
        from src.server.mcp.tools.cn_macro_tools import _pick_trade_balance
        row = {"trade_balance": "N/A"}
        assert _pick_trade_balance(row) is None
