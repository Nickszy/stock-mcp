# tests/test_shareholder_behavior_tools.py
"""Tests for shareholder behavior MCP tools.

Covers:
  - Adapter method: get_stock_pledge
  - MCP tools registration
  - Unified contract
  - Registry count updated
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


class TestStockPledgeAdapter:
    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_pledge_data(self, adapter):
        mock_df = pd.DataFrame({
            "序号": [1],
            "股票代码": ["000567"],
            "股票简称": ["海德股份"],
            "交易日期": ["2025-03-28"],
            "所属行业": ["多元金融"],
            "质押比例": [75.09],
            "质押股数": [146779.06],
            "质押市值": [880674.36],
            "质押笔数": [8],
            "无限售股质押数": [146779.06],
            "限售股份质押数": [0.0],
            "近一年涨跌幅": [4.48934],
            "所属行业代码": [738],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_stock_pledge(date="20250328"))

        assert result["source"] == "akshare"
        assert result["date"] == "20250328"
        assert result["total"] == 1
        first = result["data"][0]
        assert first["stock_code"] == "000567"
        assert first["pledge_ratio"] == 75.09
        assert first["industry"] == "多元金融"

    def test_returns_empty_on_failure(self, adapter):
        async def mock_run(func, *args, **kwargs):
            raise RuntimeError("API down")

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_stock_pledge(date="20250328"))

        assert result["data"] == []
        assert "error" in result


class TestShareholderBehaviorToolRegistration:
    def test_registers_two_tools(self):
        from src.server.mcp.tools.shareholder_behavior_tools import register_shareholder_behavior_tools

        mcp = MagicMock()
        registered = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_shareholder_behavior_tools(mcp)

        expected = ["get_institutional_research", "get_stock_pledge"]
        for name in expected:
            assert name in registered, f"Missing tool: {name}"


class TestShareholderBehaviorContract:
    def test_pledge_contract(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
            summary="股票质押",
            component_type=ComponentType.TABLE,
            name="股票质押",
            data=[{"stock_code": "000567", "pledge_ratio": 75.09}],
            source="akshare",
        )

        content = result["artifact"]["content"]
        assert content["source"]["provider"] == "akshare"
        assert content["data"][0]["stock_code"] == "000567"


class TestShareholderBehaviorRegistry:
    def test_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "shareholder-behavior"]
        assert len(groups) == 1, "shareholder-behavior group must exist"
        assert groups[0].enabled is True
        assert groups[0].count == 2

    def test_total_tool_count_updated(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total == 191, f"Expected 191, got {total}"
