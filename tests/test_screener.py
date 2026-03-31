# tests/test_screener.py
"""Tests for the A-share quantitative stock screener.

Validates:
1. Adapter screen_stocks method with various filter combinations
2. Gateway _MARKET_METHODS registration
3. Use case delegation
4. Registry tool group count
5. MCP tool output format

Run: uv run pytest tests/test_screener.py -v
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, ".")


# ---- Mock Infrastructure ----


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


def _make_sample_df():
    """Create a sample DataFrame mimicking stock_zh_a_spot_em output."""
    return pd.DataFrame({
        "代码": ["600519", "000001", "300750", "688981", "000858"],
        "名称": ["贵州茅台", "平安银行", "宁德时代", "中芯国际", "五粮液"],
        "最新价": [1800.0, 12.5, 210.0, 85.0, 160.0],
        "涨跌幅": [1.5, -0.8, 3.2, -1.2, 0.5],
        "涨跌额": [26.6, -0.1, 6.5, -1.03, 0.8],
        "成交量": [100000, 500000, 300000, 200000, 150000],
        "成交额": [1800000000, 62500000, 630000000, 170000000, 240000000],
        "振幅": [2.5, 1.8, 4.2, 3.1, 1.5],
        "最高": [1810.0, 12.8, 215.0, 87.0, 162.0],
        "最低": [1765.0, 12.2, 205.0, 83.0, 158.0],
        "今开": [1780.0, 12.6, 205.0, 86.0, 159.0],
        "昨收": [1773.4, 12.6, 203.5, 86.03, 159.2],
        "量比": [1.2, 0.8, 2.5, 1.5, 0.9],
        "换手率": [0.8, 2.5, 3.2, 1.8, 0.6],
        "市盈率-动态": [35.0, 6.5, 45.0, 80.0, 28.0],
        "市净率": [12.0, 0.7, 8.5, 3.2, 7.5],
        "总市值": [2260000000000, 240000000000, 950000000000, 680000000000, 620000000000],
        "流通市值": [2260000000000, 240000000000, 800000000000, 400000000000, 620000000000],
        "60日涨跌幅": [5.2, -3.1, 12.8, -8.5, 2.1],
        "年初至今涨跌幅": [8.5, -5.2, 15.3, -12.0, 3.8],
    })


# ---- Adapter Tests ----


class TestScreenStocksAdapter:
    """Test AkshareAdapter.screen_stocks method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_no_filters_returns_all_sorted(self, adapter):
        """With no filters, should return all stocks sorted by market_cap desc."""
        df = _make_sample_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.screen_stocks())

        assert result["total"] == 5
        assert result["returned"] == 5
        assert result["results"][0]["code"] == "600519"  # Largest market cap
        assert result["source"] == "akshare"

    def test_pe_range_filter(self, adapter):
        """Filter by PE range should exclude stocks outside range."""
        df = _make_sample_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.screen_stocks(min_pe=10, max_pe=40))

        # PE: 贵州茅台=35, 平安银行=6.5, 宁德时代=45, 中芯国际=80, 五粮液=28
        # After min_pe=10 filter, excluded: 平安银行(6.5)
        # After max_pe=40 filter, excluded: 宁德时代(45), 中芯国际(80)
        assert result["total"] == 2
        codes = [r["code"] for r in result["results"]]
        assert "600519" in codes  # PE=35
        assert "000858" in codes  # PE=28
        assert "000001" not in codes  # PE=6.5

    def test_market_cap_filter(self, adapter):
        """Filter by market cap in billions."""
        df = _make_sample_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            # market_cap in billions: 茅台=22600, 平安=2400, 宁德=9500, 中芯=6800, 五粮液=6200
            result = _run(adapter.screen_stocks(min_market_cap=5000))

        codes = [r["code"] for r in result["results"]]
        assert "600519" in codes  # 22600亿
        assert "300750" in codes  # 9500亿
        assert "688981" in codes  # 6800亿
        assert "000858" in codes  # 6200亿
        assert "000001" not in codes  # 2400亿

    def test_exchange_filter(self, adapter):
        """Filter by exchange."""
        df = _make_sample_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.screen_stocks(exchange="SSE"))

        # SSE: 600519, 688981, 000858 (codes starting with 6)
        codes = [r["code"] for r in result["results"]]
        assert "600519" in codes
        assert "688981" in codes
        assert "000001" not in codes  # SZSE

    def test_sort_asc(self, adapter):
        """Sort ascending by PE."""
        df = _make_sample_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.screen_stocks(sort_by="pe", sort_order="asc"))

        # PE: 平安银行=6.5, 五粮液=28, 茅台=35, 宁德=45, 中芯=80
        # But PE>0 filter doesn't apply here (no min/max_pe), so all pass
        pes = [r["pe"] for r in result["results"]]
        assert pes[0] <= pes[-1]  # Ascending order

    def test_limit(self, adapter):
        """Limit should cap number of results."""
        df = _make_sample_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.screen_stocks(limit=3))

        assert result["returned"] == 3
        assert result["total"] == 5

    def test_combined_filters(self, adapter):
        """Multiple filters applied simultaneously."""
        df = _make_sample_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.screen_stocks(
                min_pe=20, max_pe=50,
                min_market_cap=500,
                sort_by="pe",
                sort_order="asc",
            ))

        # PE 20-50: 茅台(35), 五粮液(28), 宁德(45)
        # market_cap > 500亿: all pass (min is 2400亿)
        codes = {r["code"] for r in result["results"]}
        assert "600519" in codes
        assert "000858" in codes
        assert "300750" in codes
        assert "000001" not in codes  # PE=6.5
        assert "688981" not in codes  # PE=80

    def test_output_structure(self, adapter):
        """Verify output structure has all expected keys."""
        df = _make_sample_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.screen_stocks())

        assert "results" in result
        assert "total" in result
        assert "returned" in result
        assert "sort_by" in result
        assert "sort_order" in result
        assert "filters_applied" in result
        assert "source" in result

        # Check individual result structure
        r = result["results"][0]
        assert "ticker" in r
        assert "code" in r
        assert "name" in r
        assert "price" in r
        assert "change_pct" in r
        assert "pe" in r
        assert "pb" in r
        assert "market_cap_b" in r
        assert "turnover_rate" in r
        assert "volume_ratio" in r

    def test_empty_result(self, adapter):
        """Very restrictive filter should return empty results."""
        df = _make_sample_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.screen_stocks(min_pe=100, max_pe=200))

        assert result["total"] == 0
        assert result["results"] == []


# ---- Gateway Registration Tests ----


class TestScreenerGateway:
    """Verify screen_stocks is in _MARKET_METHODS."""

    def test_screen_stocks_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "screen_stocks" in _MARKET_METHODS


# ---- Registry Tests ----


class TestScreenerRegistry:
    """Verify quantitative tool group in registry."""

    def test_quantitative_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        quant = [g for g in TOOL_GROUPS if g.name == "quantitative"]
        assert len(quant) == 1
        assert quant[0].count == 3
        assert quant[0].enabled is True

    def test_total_enabled_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        # Previous: 84+ tools, now +3 quantitative = 87+
        assert total >= 87, f"Expected >= 87, got {total}"


# ---- ComponentType Tests ----


class TestScreenerComponentType:
    """Verify STOCK_SCREENER ComponentType exists."""

    def test_stock_screener_component(self):
        from src.server.mcp.tools.artifact_utils import ComponentType
        assert ComponentType.STOCK_SCREENER.value == "stock_screener"


# ---- Industry/Concept Ranking Tests ----


class TestIndustryRankingAdapter:
    """Test AkshareAdapter ranking methods."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def _make_industry_df(self):
        return pd.DataFrame({
            "板块名称": ["白酒", "半导体", "新能源车", "人工智能", "医药"],
            "板块代码": ["bk0477", "bk1036", "bk0492", "bk0800", "bk0733"],
            "最新价": [8500.0, 3200.0, 4100.0, 2800.0, 5500.0],
            "涨跌幅": [2.5, -1.2, 3.8, 1.5, -0.3],
            "涨跌额": [207.3, -38.8, 150.2, 41.4, -16.5],
            "成交量": [5000000, 12000000, 8000000, 15000000, 9000000],
            "成交额": [42000000000, 38000000000, 32000000000, 35000000000, 28000000000],
            "振幅": [3.2, 2.8, 4.5, 3.1, 1.9],
            "最高": [8550.0, 3250.0, 4180.0, 2830.0, 5550.0],
            "最低": [8280.0, 3160.0, 3990.0, 2740.0, 5440.0],
            "今开": [8300.0, 3240.0, 3950.0, 2760.0, 5520.0],
            "昨收": [8292.7, 3238.8, 3949.8, 2758.6, 5516.5],
            "换手率": [2.5, 5.8, 4.2, 6.1, 3.0],
            "上涨家数": [25, 15, 30, 40, 20],
            "下跌家数": [5, 35, 10, 20, 30],
            "领涨股票": ["贵州茅台", "中微公司", "宁德时代", "科大讯飞", "恒瑞医药"],
            "领涨股票涨跌幅": [3.2, 5.1, 4.8, 6.2, 2.1],
        })

    def test_industry_ranking_default(self, adapter):
        """Default sort by change_pct desc."""
        df = self._make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_ranking())

        assert result["total"] == 5
        assert result["results"][0]["name"] == "新能源车"  # +3.8%
        assert result["results"][-1]["name"] == "半导体"  # -1.2%

    def test_industry_ranking_ascending(self, adapter):
        """Sort ascending by change_pct."""
        df = self._make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_ranking(sort_order="asc"))

        assert result["results"][0]["name"] == "半导体"  # -1.2% (worst)

    def test_industry_ranking_limit(self, adapter):
        """Limit results."""
        df = self._make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_ranking(limit=3))

        assert result["returned"] == 3
        assert result["total"] == 5

    def test_concept_ranking(self, adapter):
        """Concept ranking uses same logic with different data source."""
        df = self._make_industry_df()
        df["板块名称"] = ["AIGC", "Chiplet", "固态电池", "CPO", "创新药"]

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_concept_ranking())

        assert result["total"] == 5
        assert result["results"][0]["name"] == "固态电池"  # +3.8%

    def test_ranking_output_structure(self, adapter):
        """Verify output has all expected keys."""
        df = self._make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_ranking())

        r = result["results"][0]
        assert "name" in r
        assert "code" in r
        assert "change_pct" in r
        assert "rise_count" in r
        assert "fall_count" in r
        assert "turnover_rate" in r
        assert "top_stock" in r


class TestRankingGateway:
    """Verify ranking methods in _MARKET_METHODS."""

    def test_industry_ranking_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_industry_ranking" in _MARKET_METHODS

    def test_concept_ranking_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_concept_ranking" in _MARKET_METHODS


class TestRankingRegistry:
    """Verify quantitative tool group count."""

    def test_quantitative_tool_count(self):
        from src.server.mcp.registry import TOOL_GROUPS
        quant = [g for g in TOOL_GROUPS if g.name == "quantitative"]
        assert len(quant) == 1
        assert quant[0].count == 3

    def test_total_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        # Previous: 85 (84 + 1 screener), now +2 ranking tools = 87
        assert total >= 87, f"Expected >= 87, got {total}"
