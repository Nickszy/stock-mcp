# tests/test_index_tools.py
"""Tests for index data MCP tools.

Run: uv run pytest tests/test_index_tools.py -v
"""

from __future__ import annotations

import asyncio
import math
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, ".")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# =====================================================================
# Adapter Tests
# =====================================================================


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


class TestIndexListAdapter:
    """Test get_index_list adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_index_list_structure(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "index_code": ["000001", "000300", "399006"],
            "display_name": ["上证指数", "沪深300", "创业板指"],
            "publish_date": ["1991-07-15", "2005-04-08", "2010-06-01"],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_index_list())

        assert result["total"] == 3
        assert result["results"][0]["index_code"] == "000001"
        assert result["results"][0]["index_name"] == "上证指数"


class TestIndexPePbAdapter:
    """Test get_index_pe_pb adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_pe_pb_structure(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "trade_date": ["2026-03-27", "2026-03-26"],
            "pe": [12.5, 12.3],
            "pb": [1.35, 1.34],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_index_pe_pb(symbol="沪深300", limit=10))

        assert result["total"] == 2
        assert "pe" in result["results"][0]
        assert "pb" in result["results"][0]


class TestIndexPerformanceAdapter:
    """Test get_index_performance adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_performance_structure(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "日期": ["2026-03-27", "2026-03-26"],
            "开盘": [3950.0, 3940.0],
            "收盘": [3960.0, 3950.0],
            "最高": [3970.0, 3960.0],
            "最低": [3940.0, 3930.0],
            "涨跌幅": [0.25, 0.15],
            "成交量": [250000000, 230000000],
            "成交额": [350000000000, 330000000000],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_index_performance(symbol="000300", period="daily", limit=10))

        assert result["total"] == 2
        r = result["results"][0]
        assert "open" in r
        assert "close" in r
        assert "change_pct" in r


# =====================================================================
# Gateway Tests
# =====================================================================


class TestIndexGateway:
    """Verify index methods are in _MARKET_METHODS."""

    def test_all_index_methods_registered(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        index_methods = ["get_index_list", "get_index_pe_pb", "get_index_performance"]
        for m in index_methods:
            assert m in _MARKET_METHODS, f"{m} not in _MARKET_METHODS"


# =====================================================================
# Registry Tests
# =====================================================================


class TestIndexRegistry:
    """Verify index tool group."""

    def test_index_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        idx = [g for g in TOOL_GROUPS if g.name == "index"]
        assert len(idx) == 1
        assert idx[0].count == 3
        assert idx[0].enabled is True

    def test_total_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        # Previous: 95, now +3 index = 98
        assert total >= 98, f"Expected >= 98, got {total}"
