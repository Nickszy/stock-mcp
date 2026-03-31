# tests/test_corporate_event_tools.py
"""Tests for COL-226: Corporate event calendar tools.

Covers:
  - Adapter methods: get_earnings_calendar, get_dividend_calendar
  - MCP tools produce correct unified contract
  - Registry count updated

Run: uv run pytest tests/test_corporate_event_tools.py -v
"""

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


# =====================================================================
# Adapter: get_earnings_calendar
# =====================================================================


class TestEarningsCalendarAdapter:
    """Verify get_earnings_calendar adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_earnings_data(self, adapter):
        mock_df = pd.DataFrame({
            "股票代码": ["000001", "000002"],
            "股票简称": ["平安银行", "万科A"],
            "首次预约": ["2025-03-15", "2025-03-29"],
            "初次变更": [None, "2025-04-01"],
            "二次变更": [None, None],
            "三次变更": [None, None],
            "实际披露": ["2025-03-15", "2025-04-01"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_earnings_calendar(
                market="沪深京", period="2024年报",
            ))

        assert result["source"] == "akshare"
        assert result["period"] == "2024年报"
        assert result["market"] == "沪深京"
        assert result["total"] == 2
        assert len(result["data"]) == 2
        first = result["data"][0]
        assert "stock_code" in first
        assert "stock_name" in first
        assert "first_scheduled" in first
        assert "actual_date" in first

    def test_returns_empty_on_failure(self, adapter):
        async def mock_run(func, *args, **kwargs):
            raise RuntimeError("API down")

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_earnings_calendar())

        assert result["data"] == []
        assert "error" in result

    def test_caches_result(self, adapter):
        mock_df = pd.DataFrame({
            "股票代码": ["600519"],
            "股票简称": ["贵州茅台"],
            "首次预约": ["2025-04-01"],
            "初次变更": [None],
            "二次变更": [None],
            "三次变更": [None],
            "实际披露": [None],
        })
        call_count = 0

        async def mock_run(func, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result1 = _run(adapter.get_earnings_calendar(period="2024年报"))
            result2 = _run(adapter.get_earnings_calendar(period="2024年报"))

        assert call_count == 1
        assert result1["total"] == result2["total"]


# =====================================================================
# Adapter: get_dividend_calendar
# =====================================================================


class TestDividendCalendarAdapter:
    """Verify get_dividend_calendar adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_dividend_data(self, adapter):
        mock_df = pd.DataFrame({
            "实施方案公告日期": ["2024-06-18"],
            "分红类型": ["年度分红"],
            "送股比例": [None],
            "转增比例": [None],
            "派息比例": [30.0],
            "股权登记日": ["2024-06-24"],
            "除权日": ["2024-06-25"],
            "派息日": ["2024-06-25"],
            "股份到账日": [None],
            "实施方案分红说明": ["10派30元(含税)"],
            "报告时间": ["2023年报"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_dividend_calendar(symbol="600519"))

        assert result["source"] == "akshare"
        assert result["symbol"] == "600519"
        assert result["total"] == 1
        first = result["data"][0]
        assert "announce_date" in first
        assert "ex_date" in first
        assert "pay_date" in first
        assert "cash_div_ratio" in first

    def test_requires_symbol(self, adapter):
        result = _run(adapter.get_dividend_calendar())
        assert "error" in result

    def test_returns_empty_on_failure(self, adapter):
        async def mock_run(func, *args, **kwargs):
            raise RuntimeError("API error")

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_dividend_calendar(symbol="600519"))

        assert result["data"] == []
        assert "error" in result


# =====================================================================
# MCP Tool Registration
# =====================================================================


class TestCorporateEventToolRegistration:
    """Verify tools are properly registered."""

    def test_registers_five_tools(self):
        from src.server.mcp.tools.corporate_event_tools import register_corporate_event_tools

        mcp = MagicMock()
        registered = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_corporate_event_tools(mcp)

        expected = [
            "get_earnings_calendar",
            "get_dividend_calendar",
            "get_restricted_release_calendar",
            "get_stock_repurchase",
            "get_block_trade",
        ]
        for name in expected:
            assert name in registered, f"Missing tool: {name}"

    def test_get_dividend_calendar_rejects_empty_symbol(self):
        """The tool should return an error when symbol is empty."""
        from src.server.mcp.tools.corporate_event_tools import register_corporate_event_tools

        mcp = MagicMock()
        registered_fns = {}

        def capture_tool(**kwargs):
            def decorator(fn):
                registered_fns[fn.__name__] = fn
                return fn
            return decorator

        mcp.tool = capture_tool
        register_corporate_event_tools(mcp)

        # Run synchronously using _run helper
        result = _run(registered_fns["get_dividend_calendar"](symbol=""))
        assert "需要提供股票代码" in result["summary"]


# =====================================================================
# Unified Contract: create_standard_artifact_response
# =====================================================================


class TestCorporateEventContract:
    """Verify MCP tools produce unified contract in artifact content."""

    def test_earnings_calendar_contract(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
            summary="财报披露日历",
            component_type=ComponentType.TABLE,
            name="财报日历",
            data=[{"stock_code": "600519", "stock_name": "贵州茅台"}],
            source="akshare",
        )

        content = result["artifact"]["content"]
        assert content["source"]["provider"] == "akshare"
        assert content["data"][0]["stock_code"] == "600519"

    def test_dividend_calendar_contract(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
            summary="分红送股日历",
            component_type=ComponentType.TABLE,
            name="分红: 600519",
            data=[{"ex_date": "2024-06-25", "pay_date": "2024-06-25"}],
            source="akshare",
            symbol="600519",
        )

        content = result["artifact"]["content"]
        assert content["symbol"] == "600519"
        assert content["data"][0]["ex_date"] == "2024-06-25"

    def test_restricted_release_contract(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
            summary="限售解禁日历",
            component_type=ComponentType.TABLE,
            name="解禁日历",
            data={"summary": [], "queue": [{"stock_code": "688001"}]},
            source="akshare",
        )

        content = result["artifact"]["content"]
        assert content["data"]["queue"][0]["stock_code"] == "688001"


# =====================================================================
# Registry: tool group registered with correct count
# =====================================================================


class TestCorporateEventRegistry:
    """Verify corporate-event group is registered correctly."""

    def test_corporate_event_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "corporate-event"]
        assert len(groups) == 1, "corporate-event group must exist"
        assert groups[0].enabled is True
        assert groups[0].count == 5

    def test_total_tool_count_updated(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total == 191, f"Expected 191, got {total}"

    def test_all_event_groups_present(self):
        from src.server.mcp.registry import TOOL_GROUPS
        names = {g.name for g in TOOL_GROUPS}
        for expected in ["corporate-event", "corporate-action", "fundamental", "factor"]:
            assert expected in names, f"Missing group: {expected}"
