# tests/test_fixed_income.py
"""Tests for fixed income / bond research MCP tools (COL-244).

Covers:
  - Adapter: get_bond_yield_curve / get_convertible_bond_history / get_convertible_bond_detail
  - Gateway: new methods in _MARKET_METHODS
  - Registry: fixed-income tool group
  - MCP tools: registration
  - REST routes: endpoint presence and shape

Run: uv run pytest tests/test_fixed_income.py -v
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
# Adapter: get_bond_yield_curve
# =====================================================================


class TestBondYieldCurveAdapter:
    """Verify get_bond_yield_curve adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_bond_yield_curve_structure(self, adapter):
        mock_df = pd.DataFrame({
            "曲线名称": ["中债国债收益率曲线", "中债国债收益率曲线"],
            "日期": ["2024-01-02", "2024-01-03"],
            "1年": [2.1, 2.11],
            "10年": [2.56, 2.57],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_bond_yield_curve(start_date="20240101", end_date="20240110"))

        assert result["source"] == "akshare"
        assert len(result["data"]) == 2

    def test_bond_yield_curve_empty(self, adapter):
        async def mock_run(func, *args, **kwargs):
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_bond_yield_curve())

        assert result["data"] == []


# =====================================================================
# Adapter: get_convertible_bond_history
# =====================================================================


class TestCBHistoryAdapter:
    """Verify get_convertible_bond_history adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_cb_history_structure(self, adapter):
        mock_df = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03"],
            "open": [130.0, 131.0],
            "close": [132.0, 130.5],
            "volume": [100000, 120000],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_convertible_bond_history(symbol="sz123138", days=30))

        assert result["source"] == "akshare"
        assert result["symbol"] == "sz123138"
        assert len(result["data"]) == 2


# =====================================================================
# Adapter: get_convertible_bond_detail
# =====================================================================


class TestCBDetailAdapter:
    """Verify get_convertible_bond_detail adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_cb_detail_structure(self, adapter):
        mock_df = pd.DataFrame({
            "SECURITY_CODE": ["123138"],
            "SECURITY_NAME_ABBR": ["测试转债"],
            "CONVERT_STOCK_CODE": ["300556"],
            "CONVERT_STOCK_PRICE": [17.79],
            "TRANSFER_PREMIUM_RATIO": [93.28],
            "COUPON_IR": [2.5],
            "RATING": ["A"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_convertible_bond_detail(symbol="123138"))

        assert result["source"] == "akshare"
        detail = result["data"]
        assert detail["bond_code"] == "123138"
        assert detail["stock_code"] == "300556"
        assert detail["coupon_rate"] == 2.5
        assert detail["rating"] == "A"


# =====================================================================
# Gateway: _MARKET_METHODS
# =====================================================================


class TestFixedIncomeGateway:
    """Verify new FI methods are in _MARKET_METHODS."""

    def test_bond_yield_curve_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_bond_yield_curve" in _MARKET_METHODS

    def test_convertible_bonds_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_convertible_bonds" in _MARKET_METHODS

    def test_convertible_bond_history_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_convertible_bond_history" in _MARKET_METHODS

    def test_convertible_bond_detail_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_convertible_bond_detail" in _MARKET_METHODS

    def test_credit_spread_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_credit_spread" in _MARKET_METHODS


# =====================================================================
# Registry: fixed-income tool group
# =====================================================================


class TestFixedIncomeRegistry:
    """Verify fixed-income tool group registration."""

    def test_fixed_income_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        fi = [g for g in TOOL_GROUPS if g.name == "fixed-income"]
        assert len(fi) == 1
        assert fi[0].count == 9
        assert fi[0].enabled is True

    def test_total_tool_count_increased(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total >= 155, f"Expected >= 155, got {total}"


# =====================================================================
# MCP Tool registration
# =====================================================================


class TestFixedIncomeToolRegistration:
    """Verify fixed-income tools register without error."""

    def test_register_fixed_income_tools_succeeds(self):
        from src.server.mcp.tools.fixed_income_tools import register_fixed_income_tools
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_fixed_income_tools(mcp)


# =====================================================================
# REST Route: fixed-income endpoints
# =====================================================================


class TestFixedIncomeRoutes:
    """Verify REST route module loads and has correct shape."""

    def test_router_has_correct_prefix(self):
        from src.server.api.routes.fixed_income import router
        assert router.prefix == "/api/v1/fixed-income"

    def test_router_has_routes(self):
        from src.server.api.routes.fixed_income import router
        route_paths = [r.path for r in router.routes]
        expected_suffixes = [
            "/bond-yield", "/convertible-bonds", "/convertible-bond-history",
            "/convertible-bond-detail", "/credit-spread", "/repo-rates",
            "/interbank-rate", "/bond-issuance", "/overview",
        ]
        for suffix in expected_suffixes:
            full = f"/api/v1/fixed-income{suffix}"
            assert full in route_paths, f"Missing route {full}"
