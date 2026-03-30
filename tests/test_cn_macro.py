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
    """Verify all 9 cn-macro tools register with FastMCP."""

    def test_all_9_tools_registered(self):
        from src.server.mcp.tools.cn_macro_tools import register_cn_macro_tools
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_cn_macro_tools(mcp)

        # FastMCP stores tools internally; verify via _tool_manager
        tool_names = list(mcp._tool_manager._tools.keys())

        expected = [
            "get_cn_gdp", "get_cn_cpi", "get_cn_ppi", "get_cn_pmi",
            "get_cn_money_supply", "get_cn_interest_rates",
            "get_cn_trade_balance", "get_cn_social_financing",
            "get_cn_macro_overview",
        ]
        for name in expected:
            assert name in tool_names, f"Tool {name} not registered, found: {tool_names}"

    def test_tool_count(self):
        from src.server.mcp.tools.cn_macro_tools import register_cn_macro_tools
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_cn_macro_tools(mcp)

        tool_names = list(mcp._tool_manager._tools.keys())
        assert len(tool_names) == 9


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
