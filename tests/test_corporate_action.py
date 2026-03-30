# tests/test_corporate_action.py
"""Tests for COL-147: Corporate action data tools.

Covers:
  - Adapter methods: get_shareholder_holding_detail, get_ipo_calendar, get_ipo_info
  - MCP tools produce correct unified contract
  - Registry count updated

Run: uv run pytest tests/test_corporate_action.py -v
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
# Adapter: get_shareholder_holding_detail
# =====================================================================


class TestShareholderHoldingDetailAdapter:
    """Verify get_shareholder_holding_detail adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_data_on_success(self, adapter):
        mock_df = pd.DataFrame({
            "序号": [1, 2],
            "股东名称": ["Amgen Inc.", "HHLR Fund"],
            "股东类型": ["基金", "基金"],
            "股票代码": ["688235", "688235"],
            "股票简称": ["百济神州", "百济神州"],
            "期末持有-数量": [246269426, 142888241],
            "期末持有-持股变动": ["不变", "不变"],
            "期末持有-数量变化比例": [0.0, 0.0],
            "公告日期": ["2024-11-13", "2024-11-13"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_shareholder_holding_detail(symbol="688235"))

        assert result["source"] == "akshare"
        assert result["symbol"] == "688235"
        assert result["total"] == 2
        assert len(result["data"]) == 2
        # Check column renaming worked
        first = result["data"][0]
        assert "holder_name" in first
        assert "stock_code" in first

    def test_returns_empty_on_failure(self, adapter):
        async def mock_run(func, *args, **kwargs):
            raise RuntimeError("API error")

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_shareholder_holding_detail())

        assert result["data"] == []
        assert "error" in result

    def test_caches_result(self, adapter):
        mock_df = pd.DataFrame({
            "序号": [1],
            "股东名称": ["Test"],
            "股东类型": ["基金"],
            "股票代码": ["600519"],
            "股票简称": ["贵州茅台"],
            "期末持有-数量": [1000],
            "期末持有-持股变动": ["增持"],
            "期末持有-数量变化比例": [0.05],
            "公告日期": ["2024-11-13"],
        })
        call_count = 0

        async def mock_run(func, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result1 = _run(adapter.get_shareholder_holding_detail(symbol="600519"))
            result2 = _run(adapter.get_shareholder_holding_detail(symbol="600519"))

        assert call_count == 1  # Only called once, second hit cache
        assert result1["total"] == result2["total"]


# =====================================================================
# Adapter: get_ipo_calendar
# =====================================================================


class TestIpoCalendarAdapter:
    """Verify get_ipo_calendar adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_ipo_list(self, adapter):
        mock_df = pd.DataFrame({
            "证券代码": ["001257", "301513"],
            "证券简称": ["盛科通信", "富特科技"],
            "申购日期": ["2026-03-20", "2026-04-08"],
            "发行价格": [7.82, None],
            "网上发行中签率(%)": [0.037615, None],
            "上市日期": ["2026-03-24", None],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_ipo_calendar())

        assert result["source"] == "akshare"
        assert result["total"] == 2
        assert len(result["data"]) == 2
        first = result["data"][0]
        assert "stock_code" in first
        assert "stock_name" in first
        assert "subscribe_date" in first

    def test_returns_empty_on_failure(self, adapter):
        async def mock_run(func, *args, **kwargs):
            raise RuntimeError("API down")

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_ipo_calendar())

        assert result["data"] == []
        assert "error" in result


# =====================================================================
# Adapter: get_ipo_info
# =====================================================================


class TestIpoInfoAdapter:
    """Verify get_ipo_info adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_ipo_info(self, adapter):
        mock_df = pd.DataFrame({
            "item": ["上市板", "主承销商", "发行价格(元)", "上市日期"],
            "value": ["上海证券交易所", "华泰证券", 31.39, "2001-08-27"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_ipo_info(stock="600519"))

        assert result["source"] == "akshare"
        assert result["stock"] == "600519"
        data = result["data"]
        assert "上市板" in data
        assert data["发行价格(元)"] == 31.39

    def test_requires_stock_param(self, adapter):
        result = _run(adapter.get_ipo_info())
        assert "error" in result


# =====================================================================
# Unified Contract: MCP tools produce correct structure
# =====================================================================


class TestCorporateActionContract:
    """Verify MCP tools produce unified contract in artifact content."""

    def test_shareholder_holding_detail_contract(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
            summary="股东增减持明细",
            component_type=ComponentType.TABLE,
            name="股东增减持",
            data=[{"holder_name": "Test", "stock_code": "600519"}],
            source="akshare",
            symbol="600519",
            date="20240930",
        )

        assert "summary" in result
        content = result["artifact"]["content"]
        assert content["source"]["provider"] == "akshare"
        assert content["symbol"] == "600519"
        assert content["date"] == "20240930"
        assert len(content["data"]) == 1

    def test_ipo_calendar_contract(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
            summary="IPO日历",
            component_type=ComponentType.TABLE,
            name="新股IPO日历",
            data=[{"stock_code": "001257"}],
            source="akshare",
        )

        content = result["artifact"]["content"]
        assert content["source"]["provider"] == "akshare"
        assert content["data"][0]["stock_code"] == "001257"

    def test_ipo_info_contract(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
            summary="IPO详情: 600519",
            component_type=ComponentType.TABLE,
            name="IPO详情: 600519",
            data={"发行价格": 31.39},
            source="akshare",
            symbol="600519",
        )

        content = result["artifact"]["content"]
        assert content["symbol"] == "600519"
        assert content["data"]["发行价格"] == 31.39


# =====================================================================
# Registry: tool group registered with correct count
# =====================================================================


class TestCorporateActionRegistry:
    """Verify corporate-action group is registered correctly."""

    def test_corporate_action_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "corporate-action"]
        assert len(groups) == 1, "corporate-action group must exist"
        assert groups[0].enabled is True
        assert groups[0].count == 3

    def test_total_tool_count_updated(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total == 159, f"Expected 147, got {total}"

    def test_all_groups_present(self):
        from src.server.mcp.registry import TOOL_GROUPS
        names = {g.name for g in TOOL_GROUPS}
        for expected in ["corporate-action", "fund", "factor", "index", "etf"]:
            assert expected in names, f"Missing group: {expected}"
