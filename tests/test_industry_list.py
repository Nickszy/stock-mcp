# tests/test_industry_list.py
"""Tests for the industry board list API (COL-257).

Validates:
1. AkshareAdapter.get_industry_list() method
2. MarketGateway _MARKET_METHODS registration
3. REST endpoint GET /api/v1/sector/industry-list

Run: uv run pytest tests/test_industry_list.py -v
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

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


def _make_industry_df():
    """Create sample DataFrame mimicking stock_board_industry_name_em output."""
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


# ---- Adapter Tests ----


class TestIndustryListAdapter:
    """Test AkshareAdapter.get_industry_list method."""

    @pytest.fixture
    def adapter(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter
        return AkshareAdapter(mock_cache)

    def test_returns_all_boards(self, adapter):
        """Should return all industry boards without sorting/ranking."""
        df = _make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_list())

        assert result["total"] == 5
        assert len(result["data"]) == 5
        assert result["source"] == "akshare"

    def test_output_structure(self, adapter):
        """Each entry should have the required fields from COL-257."""
        df = _make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_list())

        entry = result["data"][0]
        assert "code" in entry
        assert "name" in entry
        assert "change_pct" in entry
        assert "stock_count" in entry
        assert "rise_count" in entry
        assert "fall_count" in entry
        assert "turnover_rate" in entry
        assert "amplitude" in entry
        assert "top_stocks" in entry

    def test_stock_count_derived(self, adapter):
        """stock_count should be rise_count + fall_count."""
        df = _make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_list())

        # 白酒: rise=25, fall=5 → stock_count=30
        baijiu = next(r for r in result["data"] if r["name"] == "白酒")
        assert baijiu["stock_count"] == 30
        assert baijiu["rise_count"] == 25
        assert baijiu["fall_count"] == 5

        # 半导体: rise=15, fall=35 → stock_count=50
        semi = next(r for r in result["data"] if r["name"] == "半导体")
        assert semi["stock_count"] == 50

    def test_top_stocks_structure(self, adapter):
        """top_stocks should be a list with name and change_pct."""
        df = _make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_list())

        baijiu = next(r for r in result["data"] if r["name"] == "白酒")
        assert len(baijiu["top_stocks"]) == 1
        assert baijiu["top_stocks"][0]["name"] == "贵州茅台"
        assert baijiu["top_stocks"][0]["change_pct"] == 3.2

    def test_code_usable_for_detail_query(self, adapter):
        """Board code should be a non-empty string like 'bk0477'."""
        df = _make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_list())

        for entry in result["data"]:
            assert entry["code"].startswith("bk")
            assert len(entry["code"]) > 2

    def test_no_sorting_applied(self, adapter):
        """Industry list should preserve original order (no ranking)."""
        df = _make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_list())

        names = [r["name"] for r in result["data"]]
        assert names == ["白酒", "半导体", "新能源车", "人工智能", "医药"]

    def test_empty_dataframe(self, adapter):
        """Should return empty result when no data."""
        async def mock_run(func, *args, **kwargs):
            return pd.DataFrame()

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_list())

        assert result["data"] == []
        assert result["total"] == 0

    def test_none_dataframe(self, adapter):
        """Should handle None return from data source."""
        async def mock_run(func, *args, **kwargs):
            return None

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_list())

        assert result["data"] == []
        assert result["total"] == 0

    def test_fetch_error(self, adapter):
        """Should return error info on exception."""
        async def mock_run(func, *args, **kwargs):
            raise RuntimeError("network error")

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_list())

        assert result["data"] == []
        assert "error" in result

    def test_caching(self, adapter, mock_cache):
        """Second call should use cached data."""
        df = _make_industry_df()
        call_count = 0

        async def mock_run(func, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            r1 = _run(adapter.get_industry_list())
            r2 = _run(adapter.get_industry_list())

        assert call_count == 1  # Only fetched once
        assert r1["total"] == r2["total"]

    def test_change_pct_rounded(self, adapter):
        """change_pct should be rounded to 2 decimal places."""
        df = _make_industry_df()

        async def mock_run(func, *args, **kwargs):
            return df

        with patch.object(adapter, "_run", AsyncMock(side_effect=mock_run)):
            result = _run(adapter.get_industry_list())

        for entry in result["data"]:
            val = entry["change_pct"]
            assert val == round(val, 2)


# ---- Gateway Registration Tests ----


class TestIndustryListGateway:
    """Verify get_industry_list is registered in _MARKET_METHODS."""

    def test_industry_list_in_market_methods(self):
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_industry_list" in _MARKET_METHODS

    def test_industry_ranking_still_registered(self):
        """Existing get_industry_ranking should still work."""
        from src.server.domain.market_gateway import _MARKET_METHODS
        assert "get_industry_ranking" in _MARKET_METHODS


# ---- REST Endpoint Tests ----


class TestIndustryListEndpoint:
    """Test GET /api/v1/sector/industry-list via TestClient."""

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from src.server.api.routes.sector import router

        app = FastAPI()
        app.include_router(router)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    @pytest.mark.asyncio
    async def test_endpoint_returns_200(self, client):
        """Endpoint should return 200 with mocked data."""
        mock_result = {
            "data": [{"code": "bk0477", "name": "白酒", "change_pct": 2.5}],
            "total": 1,
            "source": "akshare",
        }

        with patch(
            "src.server.api.routes.sector.Container"
        ) as mock_container:
            gw = AsyncMock()
            gw.get_industry_list = AsyncMock(return_value=mock_result)
            mock_container.market_gateway.return_value = gw

            resp = await client.get("/api/v1/sector/industry-list")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert "data" in body

    @pytest.mark.asyncio
    async def test_endpoint_error_handling(self, client):
        """Endpoint should return 500 on exception."""
        with patch(
            "src.server.api.routes.sector.Container"
        ) as mock_container:
            gw = AsyncMock()
            gw.get_industry_list = AsyncMock(side_effect=RuntimeError("fail"))
            mock_container.market_gateway.return_value = gw

            resp = await client.get("/api/v1/sector/industry-list")

        assert resp.status_code == 500
