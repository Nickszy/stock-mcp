# tests/test_fund_manager_changes_tools.py
"""Tests for fund manager changes MCP tool."""

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


class TestFundManagerChangesAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_manager_changes(self, adapter):
        mock_df = pd.DataFrame({
            "公告标题": ["关于增聘基金经理的公告", "关于基金经理离任的公告"],
            "公告日期": ["2025-03-01", "2025-02-01"],
            "基金简称": ["易方达中小盘", "易方达中小盘"],
            "公告ID": ["A1", "A2"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_fund_manager_changes(fund_code="110011", limit=10))

        assert result["fund_code"] == "110011"
        assert result["total"] == 2
        assert result["changes"][0]["change_type"] == "appoint"
        assert result["changes"][1]["change_type"] == "resign"


class TestFundManagerChangesToolRegistration:
    def test_registers_tool(self):
        from src.server.mcp.tools.fund_tools import register_fund_tools

        mcp = MagicMock()
        registered = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_fund_tools(mcp)

        assert "get_fund_manager_changes" in registered


class TestFundManagerChangesRegistry:
    def test_fund_group_count_updated(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "fund"]
        assert len(groups) == 1
        assert groups[0].count == 8

    def test_total_tool_count_updated(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total == 191, f"Expected 191, got {total}"
