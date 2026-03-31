# tests/test_money_flow_tools.py
"""Tests for additional money flow MCP tools."""

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


class TestDragonTigerStatisticsAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_dragon_tiger_statistics(self, adapter):
        mock_df = pd.DataFrame([
            [1, "600519", "贵州茅台", "2026-03-31", 1688.0, 2.5, 3, 120000000.0, 350000000.0, 230000000.0, 580000000.0, None, None, None, None, None, 8.2, 15.4, 28.7, 42.1],
        ])

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_dragon_tiger_statistics(symbol="近一月"))

        assert result["source"] == "akshare"
        assert result["symbol"] == "近一月"
        assert result["total"] == 1
        first = result["data"][0]
        assert first["stock_code"] == "600519"
        assert first["list_count"] == 3
        assert first["net_buy"] == 120000000.0
        assert first["rise_1y"] == 42.1


class TestMoneyFlowToolRegistration:
    def test_registers_dragon_tiger_statistics_tool(self):
        from src.server.mcp.tools.money_flow_tools import register_money_flow_tools

        mcp = MagicMock()
        registered = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_money_flow_tools(mcp)

        assert "get_dragon_tiger_statistics" in registered
        assert "get_dragon_tiger_list" in registered


class TestMoneyFlowRegistry:
    def test_money_flow_group_updated(self):
        from src.server.mcp.registry import TOOL_GROUPS

        groups = [g for g in TOOL_GROUPS if g.name == "money-flow"]
        assert len(groups) == 1
        assert groups[0].enabled is True
        assert groups[0].count == 43

    def test_total_tool_count_updated(self):
        from src.server.mcp.registry import get_enabled_tool_count

        total = get_enabled_tool_count()
        assert total == 206, f"Expected 206, got {total}"
