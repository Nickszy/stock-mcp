# tests/test_etf_tools.py
"""Tests for ETF data MCP tools.

Run: uv run pytest tests/test_etf_tools.py -v
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

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
# Adapter Tests
# =====================================================================


class TestEtfListAdapter:
    """Test get_etf_list adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_etf_list_structure(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "代码": ["510300", "159919", "513100"],
            "名称": ["沪深300ETF", "嘉实300ETF", "纳指ETF"],
            "最新价": [4.5, 2.1, 3.2],
            "涨跌幅": [1.5, -0.8, 2.0],
            "成交额": [5000000000, 3000000000, 1500000000],
            "换手率": [3.5, 5.2, 4.1],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_etf_list(limit=10))

        assert result["total"] == 3
        assert result["returned"] == 3
        assert result["results"][0]["etf_code"] == "510300"

    def test_etf_type_filter(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "代码": ["510300", "511260", "513100"],
            "名称": ["沪深300ETF", "国泰上证10年期国债", "纳斯达克ETF"],
            "最新价": [4.5, 100.5, 3.2],
            "涨跌幅": [1.5, 0.05, 2.0],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_etf_list(etf_type="跨境型", limit=10))

        assert result["total"] == 1
        assert result["results"][0]["etf_code"] == "513100"


class TestEtfDetailAdapter:
    """Test get_etf_detail adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_etf_detail_found(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "基金代码": ["510300", "159919"],
            "基金简称": ["沪深300ETF", "嘉实300ETF"],
            "最新净值": [4.5, 2.1],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_etf_detail(symbol="510300"))

        assert result["symbol"] == "510300"
        assert "detail" in result

    def test_etf_detail_not_found(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "基金代码": ["510300"],
            "基金简称": ["沪深300ETF"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_etf_detail(symbol="999999"))

        assert "error" in result


class TestEtfPerformanceAdapter:
    """Test get_etf_performance adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_performance_structure(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "日期": ["2026-03-27", "2026-03-26"],
            "开盘": [4.5, 4.48],
            "收盘": [4.55, 4.5],
            "最高": [4.58, 4.53],
            "最低": [4.47, 4.46],
            "涨跌幅": [1.11, 0.44],
            "成交量": [50000000, 45000000],
            "成交额": [2270000000, 2020000000],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_etf_performance(symbol="510300", limit=10))

        assert result["total"] == 2
        assert "open" in result["results"][0]
        assert "close" in result["results"][0]
        assert "change_pct" in result["results"][0]


# =====================================================================
# Gateway Tests
# =====================================================================


class TestEtfGateway:
    """Verify ETF methods are in _MARKET_METHODS."""

    def test_all_etf_methods_registered(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        etf_methods = ["get_etf_list", "get_etf_detail", "get_etf_performance"]
        for m in etf_methods:
            assert m in _MARKET_METHODS, f"{m} not in _MARKET_METHODS"


# =====================================================================
# Registry Tests
# =====================================================================


class TestEtfRegistry:
    """Verify ETF tool group."""

    def test_etf_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        etf = [g for g in TOOL_GROUPS if g.name == "etf"]
        assert len(etf) == 1
        assert etf[0].count == 3
        assert etf[0].enabled is True

    def test_total_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        # Previous: 101 (98 + fund 3 for index), now +3 ETF = 104
        assert total >= 104, f"Expected >= 104, got {total}"
