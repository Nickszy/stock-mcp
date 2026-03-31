# tests/test_fund_tools.py
"""Tests for fund data MCP tools.

Run: uv run pytest tests/test_fund_tools.py -v
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
        return None


@pytest.fixture
def mock_cache():
    MockCache._store = {}
    return MockCache()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# =====================================================================
# Adapter Tests
# =====================================================================


class TestCleanRecords:
    """Test _clean_records utility."""

    def test_normal_records(self):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        records = [
            {"a": 1.5, "b": 2.0, "c": "text"},
            {"a": float("nan"), "b": float("inf"), "c": "more"},
        ]
        result = AkshareAdapter._clean_records(records, ("a", "b"))
        assert result[0]["a"] == 1.5
        assert result[0]["b"] == 2.0
        assert result[1]["a"] is None  # NaN -> None
        assert result[1]["b"] is None  # inf -> None
        assert result[1]["c"] == "more"

    def test_empty_records(self):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        result = AkshareAdapter._clean_records([], ())
        assert result == []


class TestFundSearchAdapter:
    """Test search_funds adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_keyword_filter(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "基金代码": ["000001", "110011", "005827"],
            "基金简称": ["华夏成长混合", "易方达中小盘混合", "易方达蓝筹精选混合"],
            "日期": ["2026-03-27"] * 3,
            "单位净值": [1.04, 2.56, 1.23],
            "累计净值": [1.04, 3.56, 1.83],
            "近1周": [1.5, -0.5, 2.0],
            "近1月": [3.2, 5.1, -1.0],
            "近3月": [8.5, 2.3, 10.5],
            "近6月": [15.2, 8.7, 5.3],
            "近1年": [25.0, 12.5, 3.2],
            "近2年": [50.0, 25.0, 8.0],
            "近3年": [80.0, 40.0, 15.0],
            "今年来": [5.0, -2.0, 3.0],
            "成立来": [150.0, 80.0, 50.0],
            "手续费": [0.15, 0.12, 0.08],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.search_funds(keyword="易方达", sort_by="近1年", sort_order="desc", limit=3))

        assert result["total"] == 2
        assert result["returned"] == 2
        codes = [r["fund_code"] for r in result["results"]]
        assert all(c in ["110011", "005827"] for c in codes)
        returns = [r["return_1y"] for r in result["results"]]
        assert returns[0] == 12.5
        assert returns[1] == 3.2


class TestFundRankingAdapter:
    """Test get_fund_ranking adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_ranking_sort(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "基金代码": ["F001", "F002", "F003"],
            "基金简称": ["基金A", "基金B", "基金C"],
            "日期": ["2026-03-27"] * 3,
            "单位净值": [1.0, 2.0, 3.0],
            "累计净值": [1.5, 2.5, 3.5],
            "近1周": [1.0, 2.0, 3.0],
            "近1月": [4.0, 5.0, 6.0],
            "近3月": [7.0, 8.0, 9.0],
            "近6月": [10.0, 11.0, 12.0],
            "近1年": [13.0, 14.0, 15.0],
            "近2年": [16.0, 17.0, 18.0],
            "近3年": [19.0, 20.0, 21.0],
            "今年来": [1.0, 2.0, 3.0],
            "成立来": [100.0, 200.0, 300.0],
            "手续费": [0.1, 0.2, 0.3],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_fund_ranking(sort_by="近1年", sort_order="asc", limit=2))

        assert result["returned"] == 2
        returns = [r["return_1y"] for r in result["results"]]
        assert returns[0] == 13.0  # asc order, smallest first
        assert returns[1] == 14.0


class TestFundManagerAdapter:
    """Test get_fund_manager adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_manager_filter(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "姓名": ["张坤", "刘彦春", "张坤"],
            "所属公司": ["易方达", "景顺长城", "易方达"],
            "现任基金代码": ["110011", "162605", "005827"],
            "现任基金": ["中小盘", "新兴成长", "蓝筹精选"],
            "累计从业时间": [3000, 2500, 3000],
            "现任基金资产总规模": [500.0, 300.0, 200.0],
            "现任基金最佳回报": [200.0, 150.0, 180.0],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_fund_manager(manager_name="张坤"))

        assert result["total"] == 2
        names = [r["manager_name"] for r in result["results"]]
        assert all(n == "张坤" for n in names)


class TestFundValuationAdapter:
    """Test get_fund_valuation adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_single_fund(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "序号": [1, 2],
            "基金代码": ["110011", "005827"],
            "基金名称": ["易方达中小盘", "易方达蓝筹"],
            "估算值": [2.55, 1.20],
            "估算涨跌幅": [1.5, -0.8],
            "单位净值": [2.52, 1.21],
            "涨跌幅": [1.2, -0.5],
            "估算偏差": [0.3, -0.3],
            "前单位净值": [2.49, 1.22],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_fund_valuation(fund_code="110011"))

        assert result["total"] == 1
        assert result["results"][0]["fund_code"] == "110011"


class TestFundPerformanceAdapter:
    """Test get_fund_performance adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_performance_structure(self, adapter):
        import pandas as pd

        async def mock_run(func, *args, **kwargs):
            func_name = func.__name__ if hasattr(func, "__name__") else str(func)
            if "achievement" in func_name:
                return pd.DataFrame({"业绩维度": ["近1年"], "名称": ["测试"], "同类平均排名": ["100/5000"]})
            elif "analysis" in func_name:
                return pd.DataFrame({"周期": ["近1年"], "收益概率": [60.0], "最大回撤": [15.0]})
            elif "profit" in func_name:
                return pd.DataFrame({"持有时间": ["近1年"], "盈利概率": [65], "平均收益": [10.5]})
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_fund_performance(fund_code="110011"))

        assert "achievement" in result
        assert "analysis" in result
        assert "profit_probability" in result
        assert result["source"] == "akshare"


class TestFundScaleAdapter:
    """Test get_fund_scale adapter method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_scale_structure(self, adapter):
        import pandas as pd

        mock_df = pd.DataFrame({
            "截止日期": ["2025-12-31", "2025-09-30"],
            "基金家数": [24681, 24013],
            "期间申购": [489260.32, 511777.23],
            "期间赎回": [482493.95, 513197.10],
            "期末总份额": [323508.63, 314070.01],
            "期末净资产": [375419.98, 364586.45],
        })

        async def mock_run(func, *args, **kwargs):
            return mock_df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_fund_scale())

        assert len(result["results"]) == 2
        assert result["results"][0]["subscription"] == 489260.32
        assert result["results"][0]["fund_count"] == 24681
        assert result["source"] == "akshare"


# =====================================================================
# Gateway Tests
# =====================================================================


class TestFundGateway:
    """Verify fund methods are in _MARKET_METHODS."""

    def test_all_fund_methods_registered(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        fund_methods = [
            "search_funds", "get_fund_detail", "get_fund_ranking",
            "get_fund_manager", "get_fund_valuation",
            "get_fund_performance", "get_fund_scale",
        ]
        for m in fund_methods:
            assert m in _MARKET_METHODS, f"{m} not in _MARKET_METHODS"


# =====================================================================
# Registry Tests
# =====================================================================


class TestFundRegistry:
    """Verify fund tool group."""

    def test_fund_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        fund = [g for g in TOOL_GROUPS if g.name == "fund"]
        assert len(fund) == 1
        assert fund[0].count == 8
        assert fund[0].enabled is True

    def test_total_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        # Previous: 88, now +7 fund = 95
        assert total >= 95, f"Expected >= 95, got {total}"


# =====================================================================
# ComponentType Tests
# =====================================================================


class TestFundComponentTypes:
    """Verify fund ComponentType values exist."""

    def test_fund_component_types(self):
        from src.server.mcp.tools.artifact_utils import ComponentType
        assert ComponentType.FUND_SEARCH.value == "fund_search"
        assert ComponentType.FUND_DETAIL.value == "fund_detail"
        assert ComponentType.FUND_RANKING.value == "fund_ranking"
        assert ComponentType.FUND_MANAGER.value == "fund_manager"
        assert ComponentType.FUND_VALUATION.value == "fund_valuation"
        assert ComponentType.FUND_PERFORMANCE.value == "fund_performance"
        assert ComponentType.FUND_SCALE.value == "fund_scale"
