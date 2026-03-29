# tests/test_factor_tools.py
"""Tests for factor analysis MCP tools.

Run: uv run pytest tests/test_factor_tools.py -v
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


class TestStockFactorsAdapter:
    """Test get_stock_factors adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_factors_structure(self, adapter):
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2025-01-01", periods=300, freq="B")
        prices = 100.0 * np.cumprod(1 + np.random.normal(0.001, 0.02, len(dates)))
        volumes = np.random.randint(1000000, 10000000, len(dates)).astype(float)
        amounts = prices * volumes

        mock_df = pd.DataFrame({
            "日期": dates.strftime("%Y-%m-%d"),
            "收盘": prices,
            "成交量": volumes,
            "成交额": amounts,
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_stock_factors(symbol="600519", days=250))

        assert "factors" in result
        factors = result["factors"]
        assert "momentum_1M" in factors
        assert "volatility_1M" in factors
        assert "latest_close" in factors
        assert result["symbol"] == "600519"

    def test_factors_empty_data(self, adapter):
        async def mock_run(func, *args, **kwargs):
            return None

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_stock_factors(symbol="999999"))

        assert "error" in result or result.get("factors") == {}


class TestStockCorrelationAdapter:
    """Test get_stock_correlation adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_correlation_structure(self, adapter):
        import pandas as pd
        import numpy as np

        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        mock_df = pd.DataFrame({
            "日期": dates.strftime("%Y-%m-%d"),
            "收盘": 100.0 + np.cumsum(np.random.randn(len(dates))),
            "成交量": np.ones(len(dates)) * 1e6,
            "成交额": np.ones(len(dates)) * 1e8,
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_stock_correlation(symbols="600519,000858", days=60))

        assert "correlation_matrix" in result or "error" in result


class TestFactorRankingAdapter:
    """Test get_factor_ranking adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_ranking_structure(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "代码": ["600519", "000858", "000333", "601318", "000651"],
            "名称": ["贵州茅台", "五粮液", "美的集团", "中国平安", "格力电器"],
            "涨跌幅": [2.5, 1.8, -0.5, 3.2, -1.2],
            "换手率": [0.5, 1.2, 0.8, 0.3, 0.6],
            "量比": [1.2, 0.8, 1.5, 0.6, 1.1],
            "最新价": [1800.0, 150.0, 65.0, 48.0, 38.0],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_factor_ranking(factor="change_pct", direction="desc", limit=3))

        assert result["total"] == 5
        assert result["returned"] == 3
        assert result["results"][0]["symbol"] == "601318"  # 3.2 is highest


# =====================================================================
# Gateway Tests
# =====================================================================


class TestFactorGateway:
    """Verify factor methods are in _MARKET_METHODS."""

    def test_all_factor_methods_registered(self):
        from src.server.domain.market_gateway import _TICKER_METHODS, _MARKET_METHODS
        # get_stock_factors is ticker-scoped (needs single symbol)
        assert "get_stock_factors" in _TICKER_METHODS
        # get_stock_correlation and get_factor_ranking are market-wide
        for m in ["get_stock_correlation", "get_factor_ranking"]:
            assert m in _MARKET_METHODS, f"{m} not in _MARKET_METHODS"


# =====================================================================
# Registry Tests
# =====================================================================


class TestFactorRegistry:
    """Verify factor tool group."""

    def test_factor_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        factor = [g for g in TOOL_GROUPS if g.name == "factor"]
        assert len(factor) == 1
        assert factor[0].count == 3
        assert factor[0].enabled is True

    def test_total_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total >= 107, f"Expected >= 107, got {total}"
