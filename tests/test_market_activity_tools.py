# tests/test_market_activity_tools.py
"""Tests for market activity MCP tools."""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestLimitUpPoolAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_limit_up_data(self, adapter):
        mock_df = pd.DataFrame({
            "代码": ["000001"],
            "名称": ["平安银行"],
            "涨跌幅": [9.99],
            "连板数": [2],
            "首次封板时间": ["09:31:02"],
            "所属行业": ["银行"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_limit_up_pool(date="20260331"))

        assert result["source"] == "akshare"
        assert result["date"] == "20260331"
        assert result["total"] == 1
        assert result["data"][0]["stock_code"] == "000001"
        assert result["data"][0]["limit_up_streak"] == 2


class TestHotStockRankAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_hot_rank_data(self, adapter):
        mock_df = pd.DataFrame({
            "当前排名": [1],
            "股票代码": ["600519"],
            "股票名称": ["贵州茅台"],
            "最新价": [1688.0],
            "涨跌幅": [2.5],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_hot_stock_rank(symbol="全部股票"))

        assert result["source"] == "akshare"
        assert result["symbol"] == "全部股票"
        assert result["total"] == 1
        assert result["data"][0]["rank"] == 1
        assert result["data"][0]["stock_code"] == "600519"


class TestSectorChangeAlertAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_sector_change_data(self, adapter):
        mock_df = pd.DataFrame({
            "时间": ["10:15:00"],
            "板块名称": ["算力"],
            "涨跌幅": [3.2],
            "主力净流入": [120000000],
            "板块异动总次数": [5],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_sector_change_alert())

        assert result["source"] == "akshare"
        assert result["total"] == 1
        assert result["data"][0]["sector_name"] == "算力"
        assert result["data"][0]["change_count"] == 5


class TestMarketActivityToolRegistration:
    def test_registers_four_tools(self):
        from src.server.mcp.tools.market_activity_tools import register_market_activity_tools

        mcp = MagicMock()
        registered = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_market_activity_tools(mcp)

        expected = [
            "get_limit_up_pool",
            "get_limit_down_pool",
            "get_hot_stock_rank",
            "get_sector_change_alert",
        ]
        for name in expected:
            assert name in registered


class TestMarketActivityRegistry:
    def test_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "market-activity"]
        assert len(groups) == 1
        assert groups[0].enabled is True
        assert groups[0].count == 4

    def test_total_tool_count_updated(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total == 206, f"Expected 206, got {total}"
