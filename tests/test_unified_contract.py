# tests/test_unified_contract.py
"""Tests for COL-139: Unified REST/MCP response contract.

Verify that MCP tools migrated to create_standard_artifact_response produce
the correct contract structure with source, data, symbol metadata.

Run: uv run pytest tests/test_unified_contract.py -v
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
# Contract Structure Tests
# =====================================================================


class TestContractStructure:
    """Verify create_standard_artifact_response produces correct contract."""

    def test_contract_has_source_and_data(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
                summary="test",
                component_type=ComponentType.TABLE,
                name="test",
                data=[{"a": 1}],
                symbol="600519",
                source="akshare",
                limit=10,
            )

        assert "summary" in result
        assert "artifact" in result
        content = result["artifact"]["content"]

        # Unified contract fields
        assert content["symbol"] == "600519"
        assert content["source"]["provider"] == "akshare"
        assert "fetched_at" in content["source"]
        assert content["limit"] == 10
        assert content["data"] == [{"a": 1}]

    def test_contract_with_markdown(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
                summary="test",
                component_type=ComponentType.TABLE,
                name="test",
                data=[1, 2, 3],
                source="akshare",
                markdown="# Hello",
            )

        content = result["artifact"]["content"]
        assert content["markdown"] == "# Hello"
        assert content["data"] == [1, 2, 3]

    def test_contract_temporal_fields(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
                summary="test",
                component_type=ComponentType.TABLE,
                name="test",
                data=[],
                symbol="600519",
                source="akshare",
                start_date="2025-01-01",
                end_date="2025-12-31",
                interval="1d",
                period="quarterly",
            )

        content = result["artifact"]["content"]
        assert content["start_date"] == "2025-01-01"
        assert content["end_date"] == "2025-12-31"
        assert content["interval"] == "1d"
        assert content["period"] == "quarterly"

    def test_contract_error_response(self):
        from src.server.mcp.tools.artifact_utils import (
            create_standard_artifact_response,
            ComponentType,
        )

        result = create_standard_artifact_response(
                summary="查询失败: timeout",
                component_type=ComponentType.TABLE,
                name="错误",
                data={"error": "timeout"},
                source="akshare",
                description="查询失败: timeout",
            )

        content = result["artifact"]["content"]
        assert content["data"]["error"] == "timeout"
        assert content["source"]["provider"] == "akshare"


# =====================================================================
# response_contract Tests
# =====================================================================


class TestResponseContract:
    """Verify response_contract.py creates correct structures."""

    def test_create_data_response_minimal(self):
        from src.server.domain.response_contract import create_data_response

        result = create_data_response([1, 2, 3])
        assert result["data"] == [1, 2, 3]
        assert result["source"]["provider"] == "unknown"
        assert "fetched_at" in result["source"]

    def test_create_data_response_full(self):
        from src.server.domain.response_contract import create_data_response

        result = create_data_response(
            {"revenue": 100},
            symbol="SSE:600519",
            source="tushare",
            period="quarterly",
            limit="all",
            start_date="2024-01-01",
            end_date="2025-12-31",
            currency="CNY",
        )

        assert result["symbol"] == "SSE:600519"
        assert result["source"]["provider"] == "tushare"
        assert result["period"] == "quarterly"
        assert result["limit"] == "all"
        assert result["currency"] == "CNY"
        assert result["data"] == {"revenue": 100}

    def test_rest_response(self):
        from src.server.domain.response_contract import rest_response

        result = rest_response(
            [{"close": 100}],
            symbol="600519",
            source="akshare",
            limit=10,
        )

        assert result["code"] == 0
        assert result["message"] == "success"
        contract = result["data"]
        assert contract["symbol"] == "600519"
        assert contract["limit"] == 10
        assert contract["data"] == [{"close": 100}]


# =====================================================================
# Migrated Tool Contract Verification
# =====================================================================


class TestFundToolsContract:
    """Verify fund tools produce unified contract in artifact content."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_search_funds_contract(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "基金代码": ["110011", "005827"],
            "基金简称": ["易方达中小盘", "华夏沪深300"],
            "最新净值": [3.5, 1.8],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.search_funds(keyword="易方达"))

        assert "results" in result
        assert "total" in result


class TestFactorToolsContract:
    """Verify factor tools produce unified contract."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_stock_factors_contract(self, adapter):
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2025-01-01", periods=300, freq="B")
        mock_df = pd.DataFrame({
            "日期": dates.strftime("%Y-%m-%d"),
            "收盘": 100.0 + np.cumsum(np.random.randn(len(dates))),
            "成交量": np.ones(len(dates)) * 1e6,
            "成交额": np.ones(len(dates)) * 1e8,
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_stock_factors(symbol="600519", days=250))

        assert "factors" in result
        assert result["symbol"] == "600519"


# =====================================================================
# Registry & Count Tests
# =====================================================================


class TestRegistryAfterMerge:
    """Verify registry is consistent after COL-139 merge."""

    def test_total_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total == 155, f"Expected 147, got {total}"

    def test_fundamental_count(self):
        from src.server.mcp.registry import TOOL_GROUPS
        fundamental = [g for g in TOOL_GROUPS if g.name == "fundamental"]
        assert len(fundamental) == 1
        # Was 6, now 9 after re-adding get_financial_reports + forecast + ratios
        assert fundamental[0].count == 9

    def test_all_contract_groups_present(self):
        from src.server.mcp.registry import TOOL_GROUPS
        names = {g.name for g in TOOL_GROUPS}
        for expected in ["fundamental", "fund", "factor", "index", "etf"]:
            assert expected in names, f"Missing group: {expected}"
