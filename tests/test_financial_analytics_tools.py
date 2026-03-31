# tests/test_financial_analytics_tools.py
"""Tests for financial analytics MCP tools.

Covers:
  - Tool registration on FastMCP instance
  - Pure calculation helper functions (_calc_growth, _safe_float, _format_pct,
    _format_amount, _score_to_rating)
  - get_financial_growth_analysis: happy path, empty data, error path
  - get_financial_health_score: happy path, partial data, empty data, error path
  - Response structure (artifact envelope format)

Run: uv run pytest tests/test_financial_analytics_tools.py -v
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _get_tool_fn(mcp, tool_name: str):
    """Get a tool's underlying function by name."""
    tm = mcp._tool_manager
    assert tool_name in tm._tools, (
        f"Tool '{tool_name}' not found; available: {list(tm._tools.keys())}"
    )
    return tm._tools[tool_name].fn


async def _call_tool(mcp, tool_name: str, **kwargs):
    """Call a named tool on an MCP instance."""
    fn = _get_tool_fn(mcp, tool_name)
    return await fn(**kwargs)


def _assert_artifact_response(resp: Dict[str, Any]):
    """Verify standard artifact response shape."""
    assert "summary" in resp, "Response missing 'summary'"
    assert "artifact" in resp, "Response missing 'artifact'"
    assert isinstance(resp["summary"], str)
    art = resp["artifact"]
    assert "component_type" in art
    assert "name" in art
    assert "content" in art


def _make_financial_data(n_periods: int = 6) -> list:
    """Build a list of mock financial data records (quarterly)."""
    records = []
    for i in range(n_periods):
        quarter = n_periods - i
        year = 2025
        if quarter <= 0:
            quarter += 4
            year -= 1
        period = f"{year}-Q{quarter}"
        records.append({
            "report_period": period,
            "data": {
                "revenue": 10_000_000_000 + i * 500_000_000,
                "net_income": 2_000_000_000 + i * 100_000_000,
                "eps": 15.0 + i * 0.5,
                "total_assets": 50_000_000_000 + i * 1_000_000_000,
                "total_liabilities": 20_000_000_000 + i * 500_000_000,
                "operating_cash_flow": 2_500_000_000 + i * 200_000_000,
                "current_assets": 15_000_000_000 + i * 300_000_000,
                "current_liabilities": 8_000_000_000 + i * 200_000_000,
            },
            "source_type": "canonical",
        })
    return records


# =====================================================================
# Tool Registration
# =====================================================================


class TestRegistration:
    """Verify financial analytics tools register on a FastMCP instance."""

    @pytest.fixture
    def mcp(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.financial_analytics_tools import (
            register_financial_analytics_tools,
        )
        mcp = FastMCP("test")
        register_financial_analytics_tools(mcp)
        return mcp

    def test_both_tools_registered(self, mcp):
        tools = list(mcp._tool_manager._tools.keys())
        assert "get_financial_growth_analysis" in tools, (
            f"get_financial_growth_analysis not in {tools}"
        )
        assert "get_financial_health_score" in tools, (
            f"get_financial_health_score not in {tools}"
        )

    def test_tool_tags(self, mcp):
        for name in ["get_financial_growth_analysis", "get_financial_health_score"]:
            tool = mcp._tool_manager._tools[name]
            tags = tool.tags or set()
            assert "analytics" in tags, f"{name} missing 'analytics' tag"
            assert "fundamental" in tags, f"{name} missing 'fundamental' tag"


# =====================================================================
# Pure Calculation Helpers
# =====================================================================


class TestSafeFloat:
    """Test _safe_float conversion helper."""

    def test_none(self):
        from src.server.mcp.tools.financial_analytics_tools import _safe_float
        assert _safe_float(None) is None

    def test_int(self):
        from src.server.mcp.tools.financial_analytics_tools import _safe_float
        assert _safe_float(42) == 42.0

    def test_str_valid(self):
        from src.server.mcp.tools.financial_analytics_tools import _safe_float
        assert _safe_float("3.14") == 3.14

    def test_str_invalid(self):
        from src.server.mcp.tools.financial_analytics_tools import _safe_float
        assert _safe_float("abc") is None

    def test_float_passthrough(self):
        from src.server.mcp.tools.financial_analytics_tools import _safe_float
        assert _safe_float(1.5) == 1.5


class TestCalcGrowth:
    """Test _calc_growth rate calculation."""

    def test_basic_positive_growth(self):
        from src.server.mcp.tools.financial_analytics_tools import _calc_growth
        result = _calc_growth(120.0, 100.0)
        assert abs(result - 0.20) < 1e-9

    def test_negative_growth(self):
        from src.server.mcp.tools.financial_analytics_tools import _calc_growth
        result = _calc_growth(80.0, 100.0)
        assert abs(result - (-0.20)) < 1e-9

    def test_none_current(self):
        from src.server.mcp.tools.financial_analytics_tools import _calc_growth
        assert _calc_growth(None, 100.0) is None

    def test_none_previous(self):
        from src.server.mcp.tools.financial_analytics_tools import _calc_growth
        assert _calc_growth(100.0, None) is None

    def test_zero_previous(self):
        from src.server.mcp.tools.financial_analytics_tools import _calc_growth
        assert _calc_growth(100.0, 0) is None

    def test_both_zero(self):
        from src.server.mcp.tools.financial_analytics_tools import _calc_growth
        assert _calc_growth(0, 0) is None

    def test_negative_previous(self):
        from src.server.mcp.tools.financial_analytics_tools import _calc_growth
        # Growth from -100 to +50 should be calculated
        result = _calc_growth(50.0, -100.0)
        assert abs(result - 1.5) < 1e-9


class TestFormatPct:
    """Test _format_pct percentage formatter."""

    def test_none(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_pct
        assert _format_pct(None) == "N/A"

    def test_positive(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_pct
        result = _format_pct(0.156)
        assert result == "+15.6%"

    def test_zero(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_pct
        result = _format_pct(0.0)
        assert result == "+0.0%"

    def test_negative(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_pct
        result = _format_pct(-0.083)
        assert result == "-8.3%"


class TestFormatAmount:
    """Test _format_amount large number formatter."""

    def test_none(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_amount
        assert _format_amount(None) == "N/A"

    def test_yi(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_amount
        # 1.5e8 -> 1.50亿
        result = _format_amount(1.5e8)
        assert result == "1.50亿"

    def test_wan(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_amount
        # 50000 -> 5.00万
        result = _format_amount(50000)
        assert result == "5.00万"

    def test_small(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_amount
        result = _format_amount(42.5)
        assert result == "42.50"

    def test_negative_yi(self):
        from src.server.mcp.tools.financial_analytics_tools import _format_amount
        result = _format_amount(-2.3e8)
        assert result == "-2.30亿"


class TestScoreToRating:
    """Test _score_to_rating conversion."""

    def test_excellent(self):
        from src.server.mcp.tools.financial_analytics_tools import _score_to_rating
        assert _score_to_rating(85) == "优秀"
        assert _score_to_rating(80) == "优秀"

    def test_good(self):
        from src.server.mcp.tools.financial_analytics_tools import _score_to_rating
        assert _score_to_rating(60) == "良好"
        assert _score_to_rating(79) == "良好"

    def test_average(self):
        from src.server.mcp.tools.financial_analytics_tools import _score_to_rating
        assert _score_to_rating(40) == "一般"
        assert _score_to_rating(59) == "一般"

    def test_weak(self):
        from src.server.mcp.tools.financial_analytics_tools import _score_to_rating
        assert _score_to_rating(20) == "较弱"
        assert _score_to_rating(39) == "较弱"

    def test_risk(self):
        from src.server.mcp.tools.financial_analytics_tools import _score_to_rating
        assert _score_to_rating(0) == "风险"
        assert _score_to_rating(19) == "风险"


# =====================================================================
# get_financial_growth_analysis Tool
# =====================================================================


class TestGetFinancialGrowthAnalysis:
    """Test get_financial_growth_analysis MCP tool."""

    @pytest.fixture
    def mcp(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.financial_analytics_tools import (
            register_financial_analytics_tools,
        )
        mcp = FastMCP("test")
        register_financial_analytics_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_happy_path(self, mcp):
        """Test growth analysis with sufficient data for YoY calculation."""
        mock_data = _make_financial_data(n_periods=6)
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=mock_data),
        ):
            resp = await _call_tool(
                mcp, "get_financial_growth_analysis", symbol="SSE:600519"
            )

        _assert_artifact_response(resp)
        assert "600519" in resp["summary"]
        art = resp["artifact"]
        content = art["content"]
        assert "data" in content
        data = content["data"]
        assert data["symbol"] == "SSE:600519"
        assert "periods" in data
        assert data["period_count"] > 0

    @pytest.mark.asyncio
    async def test_empty_data(self, mcp):
        """Test growth analysis when no data is available."""
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=[]),
        ):
            resp = await _call_tool(
                mcp, "get_financial_growth_analysis", symbol="SSE:000000"
            )

        _assert_artifact_response(resp)
        assert "无财报数据" in resp["summary"]
        art = resp["artifact"]
        assert art["content"]["data"]["error"] == "No data available"

    @pytest.mark.asyncio
    async def test_error_path(self, mcp):
        """Test growth analysis when data fetch raises an exception."""
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(side_effect=RuntimeError("connection refused")),
        ):
            resp = await _call_tool(
                mcp, "get_financial_growth_analysis", symbol="SSE:600519"
            )

        _assert_artifact_response(resp)
        assert "失败" in resp["summary"]

    @pytest.mark.asyncio
    async def test_response_has_markdown(self, mcp):
        """Test that response includes markdown rendering."""
        mock_data = _make_financial_data(n_periods=6)
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=mock_data),
        ):
            resp = await _call_tool(
                mcp, "get_financial_growth_analysis", symbol="SSE:600519"
            )

        art = resp["artifact"]
        content = art["content"]
        assert "markdown" in content
        assert "增长率分析" in content["markdown"]

    @pytest.mark.asyncio
    async def test_custom_limit(self, mcp):
        """Test growth analysis with custom limit parameter."""
        mock_data = _make_financial_data(n_periods=4)
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=mock_data),
        ):
            resp = await _call_tool(
                mcp,
                "get_financial_growth_analysis",
                symbol="SSE:600519",
                limit=4,
            )

        _assert_artifact_response(resp)
        data = resp["artifact"]["content"]["data"]
        assert data["period_count"] == 4

    @pytest.mark.asyncio
    async def test_source_type_propagated(self, mcp):
        """Test that source_type from data is included in response."""
        mock_data = _make_financial_data(n_periods=2)
        mock_data[0]["source_type"] = "live"
        mock_data[1]["source_type"] = "live"
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=mock_data),
        ):
            resp = await _call_tool(
                mcp, "get_financial_growth_analysis", symbol="SSE:600519"
            )

        data = resp["artifact"]["content"]["data"]
        assert data["source_type"] == "live"


# =====================================================================
# get_financial_health_score Tool
# =====================================================================


class TestGetFinancialHealthScore:
    """Test get_financial_health_score MCP tool."""

    @pytest.fixture
    def mcp(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.financial_analytics_tools import (
            register_financial_analytics_tools,
        )
        mcp = FastMCP("test")
        register_financial_analytics_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_happy_path(self, mcp):
        """Test health score with full financial data."""
        mock_data = _make_financial_data(n_periods=3)
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=mock_data),
        ):
            resp = await _call_tool(
                mcp, "get_financial_health_score", symbol="SSE:600519"
            )

        _assert_artifact_response(resp)
        assert "600519" in resp["summary"]
        art = resp["artifact"]
        content = art["content"]
        data = content["data"]
        assert data["symbol"] == "SSE:600519"
        assert "total_score" in data
        assert isinstance(data["total_score"], (int, float))
        assert 0 <= data["total_score"] <= 100
        assert "rating" in data
        assert "dimensions" in data
        assert "risks" in data

    @pytest.mark.asyncio
    async def test_dimension_structure(self, mcp):
        """Test that all 5 dimensions are present with scores."""
        mock_data = _make_financial_data(n_periods=3)
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=mock_data),
        ):
            resp = await _call_tool(
                mcp, "get_financial_health_score", symbol="SSE:600519"
            )

        dims = resp["artifact"]["content"]["data"]["dimensions"]
        expected_dims = [
            "profitability",
            "solvency",
            "growth",
            "cashflow",
            "efficiency",
        ]
        for dim_name in expected_dims:
            assert dim_name in dims, f"Missing dimension: {dim_name}"
            assert "score" in dims[dim_name]
            assert isinstance(dims[dim_name]["score"], (int, float))

    @pytest.mark.asyncio
    async def test_empty_data(self, mcp):
        """Test health score when no data is available."""
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=[]),
        ):
            resp = await _call_tool(
                mcp, "get_financial_health_score", symbol="SSE:000000"
            )

        _assert_artifact_response(resp)
        assert "无财报数据" in resp["summary"]

    @pytest.mark.asyncio
    async def test_error_path(self, mcp):
        """Test health score when data fetch raises."""
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(side_effect=RuntimeError("timeout")),
        ):
            resp = await _call_tool(
                mcp, "get_financial_health_score", symbol="SSE:600519"
            )

        _assert_artifact_response(resp)
        assert "失败" in resp["summary"]

    @pytest.mark.asyncio
    async def test_rating_matches_score(self, mcp):
        """Test that the rating string is consistent with the score."""
        mock_data = _make_financial_data(n_periods=3)
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=mock_data),
        ):
            resp = await _call_tool(
                mcp, "get_financial_health_score", symbol="SSE:600519"
            )

        data = resp["artifact"]["content"]["data"]
        score = data["total_score"]
        rating = data["rating"]
        if score >= 80:
            assert rating == "优秀"
        elif score >= 60:
            assert rating == "良好"
        elif score >= 40:
            assert rating == "一般"
        elif score >= 20:
            assert rating == "较弱"
        else:
            assert rating == "风险"

    @pytest.mark.asyncio
    async def test_partial_data_still_scores(self, mcp):
        """Test health score with minimal data (only revenue + net_income)."""
        mock_data = [
            {
                "report_period": "2025-Q1",
                "data": {
                    "revenue": 10_000_000_000,
                    "net_income": 2_000_000_000,
                },
                "source_type": "canonical",
            },
            {
                "report_period": "2024-Q4",
                "data": {
                    "revenue": 9_000_000_000,
                    "net_income": 1_800_000_000,
                },
                "source_type": "canonical",
            },
        ]
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=mock_data),
        ):
            resp = await _call_tool(
                mcp, "get_financial_health_score", symbol="SSE:600519"
            )

        _assert_artifact_response(resp)
        data = resp["artifact"]["content"]["data"]
        # Should still compute a score even without full data
        assert isinstance(data["total_score"], (int, float))

    @pytest.mark.asyncio
    async def test_response_has_markdown(self, mcp):
        """Test that health score response includes markdown."""
        mock_data = _make_financial_data(n_periods=3)
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=mock_data),
        ):
            resp = await _call_tool(
                mcp, "get_financial_health_score", symbol="SSE:600519"
            )

        content = resp["artifact"]["content"]
        assert "markdown" in content
        assert "财务健康评分" in content["markdown"]

    @pytest.mark.asyncio
    async def test_risk_flags_high_debt(self, mcp):
        """Test that high debt ratio triggers a risk flag."""
        mock_data = [
            {
                "report_period": "2025-Q1",
                "data": {
                    "revenue": 10_000_000_000,
                    "net_income": 500_000_000,
                    "total_assets": 10_000_000_000,
                    "total_liabilities": 9_000_000_000,
                    "operating_cash_flow": 600_000_000,
                    "current_assets": 2_000_000_000,
                    "current_liabilities": 7_000_000_000,
                },
                "source_type": "canonical",
            },
            {
                "report_period": "2024-Q4",
                "data": {
                    "revenue": 9_000_000_000,
                    "net_income": 400_000_000,
                },
                "source_type": "canonical",
            },
        ]
        with patch(
            "src.server.mcp.tools.financial_analytics_tools._fetch_financial_data",
            AsyncMock(return_value=mock_data),
        ):
            resp = await _call_tool(
                mcp, "get_financial_health_score", symbol="SSE:600519"
            )

        data = resp["artifact"]["content"]["data"]
        # debt_ratio = 9e9 / 10e9 = 0.9, which is > 0.70
        assert any("资产负债率偏高" in r for r in data["risks"]), (
            f"Expected high debt risk flag, got: {data['risks']}"
        )


# =====================================================================
# _fetch_financial_data Helper
# =====================================================================


class TestFetchFinancialData:
    """Test _fetch_financial_data fallback logic."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_fail(self):
        """Both canonical and gateway fail -> returns empty list."""
        from src.server.mcp.tools.financial_analytics_tools import (
            _fetch_financial_data,
        )

        # Patch the lazy imports inside _fetch_financial_data to force both
        # canonical and gateway paths to fail, returning empty list.
        with patch.dict("sys.modules", {
            "src.server.domain.structured_data.canonical_reader": None,
        }):
            with patch(
                "src.server.core.dependencies.Container.market_gateway",
                side_effect=RuntimeError("no gateway"),
            ):
                result = await _fetch_financial_data("SSE:600519", limit=4)

        assert result == []

    def test_symbol_splitting_with_colon(self):
        """Verify symbol with colon is split into exchange + ticker."""
        symbol = "SSE:600519"
        exchange, ticker = symbol.split(":") if ":" in symbol else ("", symbol)
        assert exchange == "SSE"
        assert ticker == "600519"

    def test_symbol_splitting_without_colon(self):
        """Verify symbol without colon gets empty exchange."""
        symbol = "600519"
        exchange, ticker = symbol.split(":") if ":" in symbol else ("", symbol)
        assert exchange == ""
        assert ticker == "600519"
