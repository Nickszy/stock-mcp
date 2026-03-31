# tests/test_earnings_forecast_tools.py
"""Tests for earnings forecast MCP tools."""

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


class TestEarningsPreviewAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_preview_data(self, adapter):
        mock_df = pd.DataFrame({
            "序号": [1],
            "股票代码": ["600519"],
            "股票简称": ["贵州茅台"],
            "预测指标": ["净利润"],
            "业绩变动": ["预增"],
            "预测数值": [None],
            "业绩变动幅度": [None],
            "业绩变动原因": ["销量增长"],
            "预告类型": ["预增"],
            "上年同期值": [None],
            "公告日期": ["2025-04-01"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_earnings_preview(period="20250331"))

        assert result["source"] == "akshare"
        assert result["period"] == "20250331"
        assert result["total"] == 1
        assert result["data"][0]["stock_code"] == "600519"
        assert result["data"][0]["preview_type"] == "预增"

    def test_returns_empty_on_failure(self, adapter):
        async def mock_run(func, *args, **kwargs):
            raise RuntimeError("API down")

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_earnings_preview())

        assert result["data"] == []
        assert "error" in result


class TestAnalystConsensusAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_consensus_data(self, adapter):
        mock_df = pd.DataFrame({
            "年份": [2025, 2026],
            "预测机构数": [45, 44],
            "最小值": [71.07, 71.26],
            "均值": [72.52, 76.01],
            "最大值": [75.23, 81.67],
            "行业平均数": [9.86, 10.31],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_analyst_consensus(symbol="600519"))

        assert result["source"] == "akshare"
        assert result["symbol"] == "600519"
        assert result["total"] == 2
        assert result["data"][0]["eps_mean"] == 72.52

    def test_requires_symbol(self, adapter):
        result = _run(adapter.get_analyst_consensus(symbol=""))
        assert "error" in result


class TestEarningsFlashAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_flash_data(self, adapter):
        mock_df = pd.DataFrame({
            "股票代码": ["600519"],
            "股票简称": ["贵州茅台"],
            "每股收益": [41.76],
            "营业收入-营业收入": [1500.0],
            "营业收入-同比增长": [18.5],
            "净利润-净利润": [750.0],
            "净利润-同比增长": [15.2],
            "每股净资产": [180.0],
            "净资产收益率": [23.2],
            "公告日期": ["2025-04-15"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_earnings_flash(period="20250331"))

        assert result["source"] == "akshare"
        assert result["period"] == "20250331"
        assert result["total"] == 1
        assert result["data"][0]["stock_code"] == "600519"
        assert result["data"][0]["eps"] == 41.76

    def test_returns_empty_on_failure(self, adapter):
        async def mock_run(func, *args, **kwargs):
            raise RuntimeError("API down")

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_earnings_flash())

        assert result["data"] == []
        assert "error" in result


class TestEarningsForecastToolRegistration:
    def test_registers_three_tools(self):
        from src.server.mcp.tools.earnings_forecast_tools import register_earnings_forecast_tools

        mcp = MagicMock()
        registered = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_earnings_forecast_tools(mcp)

        assert "get_earnings_preview" in registered
        assert "get_analyst_consensus" in registered
        assert "get_earnings_flash" in registered


class TestEarningsForecastRegistry:
    def test_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "earnings-forecast"]
        assert len(groups) == 1
        assert groups[0].enabled is True
        assert groups[0].count == 3

    def test_total_tool_count_updated(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total == 187, f"Expected 187, got {total}"
