# tests/test_us_market_overview.py
"""Tests for US market overview MCP tool.

Validates:
1. Adapter method structure
2. Gateway _MARKET_METHODS registration
3. Registry tool count
4. MCP tool output format

Run: uv run pytest tests/test_us_market_overview.py -v
"""

from __future__ import annotations

import asyncio
import math
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestUSMarketOverviewAdapter:
    """Test YahooAdapter.get_us_market_overview method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.yahoo_adapter import YahooAdapter
        return YahooAdapter(mock_cache)

    def test_overview_structure(self, adapter):
        """Should return expected top-level keys."""
        mock_quotes = {
            "SPY": {"price": 520.5, "change_pct": 1.2, "change": 6.18, "volume": 50000000},
            "QQQ": {"price": 450.2, "change_pct": 1.8, "change": 7.95, "volume": 40000000},
            "DIA": {"price": 410.3, "change_pct": 0.5, "change": 2.05, "volume": 10000000},
            "IWM": {"price": 210.1, "change_pct": -0.3, "change": -0.63, "volume": 20000000},
            "XLK": {"price": 200.0, "change_pct": 2.1},
            "XLF": {"price": 40.0, "change_pct": 0.8},
            "XLE": {"price": 85.0, "change_pct": -1.5},
            "XLV": {"price": 130.0, "change_pct": 0.3},
            "XLY": {"price": 180.0, "change_pct": 1.0},
            "XLP": {"price": 75.0, "change_pct": -0.2},
            "XLI": {"price": 110.0, "change_pct": 0.6},
            "XLB": {"price": 90.0, "change_pct": -0.8},
            "XLRE": {"price": 45.0, "change_pct": -1.2},
            "XLU": {"price": 65.0, "change_pct": 0.1},
            "XLC": {"price": 80.0, "change_pct": 1.5},
            "^VIX": {"price": 18.5},
        }

        async def mock_run(func, *args, **kwargs):
            return mock_quotes

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_us_market_overview())

        assert "indices" in result
        assert "sectors" in result
        assert "vix" in result
        assert "market_breadth" in result
        assert "sentiment" in result
        assert result["source"] == "yahoo"

        # Check indices
        assert len(result["indices"]) == 4
        spy_data = [i for i in result["indices"] if i["symbol"] == "SPY"][0]
        assert spy_data["change_pct"] == 1.2

        # Check sectors sorted by change_pct desc
        assert result["sectors"][0]["symbol"] == "XLK"  # +2.1%
        assert result["sectors"][-1]["symbol"] == "XLE"  # -1.5%

        # Check VIX
        assert result["vix"]["level"] == 18.5
        assert result["vix"]["signal"] == "正常"

        # Check sentiment (SPY change_pct=1.2 > 1.0 → "强势上涨")
        assert result["sentiment"] == "强势上涨"

    def test_vix_fear_signal(self, adapter):
        """VIX > 30 should show fear signal."""
        mock_quotes = {
            "SPY": {"price": 520.5, "change_pct": -2.5, "change": -13.3, "volume": 50000000},
            "QQQ": {"price": 450.2, "change_pct": -3.0, "change": -13.9, "volume": 40000000},
            "DIA": {"price": 410.3, "change_pct": -2.0, "change": -8.4, "volume": 10000000},
            "IWM": {"price": 210.1, "change_pct": -4.0, "change": -8.8, "volume": 20000000},
            "^VIX": {"price": 35.0},
        }
        # Add all sector ETFs with None
        for etf in ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLRE", "XLU", "XLC"]:
            mock_quotes[etf] = {"price": 100.0, "change_pct": -1.0}

        async def mock_run(func, *args, **kwargs):
            return mock_quotes

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_us_market_overview())

        assert result["vix"]["signal"] == "高波动/恐慌"
        assert result["sentiment"] == "显著下跌"


class TestUSMarketOverviewGateway:
    """Verify get_us_market_overview is in _MARKET_METHODS."""

    def test_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_us_market_overview" in _MARKET_METHODS


class TestUSMarketOverviewRegistry:
    """Verify us-technical tool count."""

    def test_us_technical_tool_count(self):
        from src.server.mcp.registry import TOOL_GROUPS
        us_tech = [g for g in TOOL_GROUPS if g.name == "us-technical"]
        assert len(us_tech) == 1
        assert us_tech[0].count == 5

    def test_total_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        # Previous: 87 (85 base + 2 ranking), now +1 US overview = 88
        assert total >= 88, f"Expected >= 88, got {total}"
