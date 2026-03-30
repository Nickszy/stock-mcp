# tests/test_stock_comparison_tools.py
"""Tests for stock comparison MCP tools."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestCompareStocksHelpers:
    """Verify helper functions."""

    def test_safe_float(self):
        from src.server.mcp.tools.stock_comparison_tools import _safe_float
        assert _safe_float(3.14) == 3.14
        assert _safe_float("42") == 42.0
        assert _safe_float(None) is None
        assert _safe_float("abc") is None

    def test_fmt_basic(self):
        from src.server.mcp.tools.stock_comparison_tools import _fmt
        assert "亿" in _fmt(1e9)
        assert "万" in _fmt(5e4)
        assert "N/A" == _fmt(None)

    def test_fmt_pct(self):
        from src.server.mcp.tools.stock_comparison_tools import _fmt_pct
        assert "20.0%" in _fmt_pct(0.2)
        assert "N/A" == _fmt_pct(None)

    def test_pick_winner_higher_better(self):
        from src.server.mcp.tools.stock_comparison_tools import _pick_winner
        stocks = [
            {"symbol": "A", "pe": 10},
            {"symbol": "B", "pe": 20},
        ]
        assert _pick_winner(stocks, "pe", higher_is_better=True) == "B"
        assert _pick_winner(stocks, "pe", higher_is_better=False) == "A"

    def test_pick_winner_with_nones(self):
        from src.server.mcp.tools.stock_comparison_tools import _pick_winner
        stocks = [
            {"symbol": "A", "pe": None},
            {"symbol": "B", "pe": 20},
        ]
        assert _pick_winner(stocks, "pe", higher_is_better=True) == "B"

    def test_pick_winner_all_none(self):
        from src.server.mcp.tools.stock_comparison_tools import _pick_winner
        stocks = [
            {"symbol": "A"},
            {"symbol": "B"},
        ]
        assert _pick_winner(stocks, "pe", higher_is_better=True) is None


class TestCompareStocksTool:
    """Verify compare_stocks MCP tool."""

    @pytest.mark.asyncio
    async def test_rejects_single_symbol(self):
        """Must reject when only 1 symbol provided."""
        from src.server.mcp.tools.stock_comparison_tools import register_stock_comparison_tools

        mcp = MagicMock()
        registered_fn = None

        def capture_tool(**kwargs):
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn
            return decorator

        mcp.tool = capture_tool
        register_stock_comparison_tools(mcp)

        result = await registered_fn(symbols="SSE:600519")
        assert "至少需要2" in result["summary"]

    @pytest.mark.asyncio
    async def test_comparison_with_mock_data(self):
        """Comparison produces ranked output with mock data."""
        from src.server.mcp.tools.stock_comparison_tools import register_stock_comparison_tools

        mcp = MagicMock()
        registered_fn = None

        def capture_tool(**kwargs):
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn
            return decorator

        mcp.tool = capture_tool
        register_stock_comparison_tools(mcp)

        mock_metrics = [
            {
                "symbol": "SSE:600519",
                "name": "贵州茅台",
                "pe_ttm": 25.0,
                "pb": 8.0,
                "market_cap": 2.0e12,
                "roe": 0.30,
                "net_margin": 0.50,
                "revenue_yoy": 0.15,
                "debt_ratio": 0.25,
            },
            {
                "symbol": "SZSE:000858",
                "name": "五粮液",
                "pe_ttm": 20.0,
                "pb": 5.0,
                "market_cap": 6e11,
                "roe": 0.25,
                "net_margin": 0.38,
                "revenue_yoy": 0.10,
                "debt_ratio": 0.30,
            },
        ]

        with patch(
            "src.server.mcp.tools.stock_comparison_tools._fetch_stock_metrics",
            new_callable=AsyncMock,
            side_effect=mock_metrics,
        ):
            result = await registered_fn(symbols="SSE:600519,SZSE:000858")

        assert "多股对比" in result["summary"]
        content = result["artifact"]["content"]
        data = content["data"]
        assert "ranked" in data
        assert len(data["ranked"]) == 2
        # 茅台 should rank higher (more wins)
        assert data["ranked"][0]["symbol"] == "SSE:600519"

    @pytest.mark.asyncio
    async def test_comparison_truncates_to_5(self):
        """More than 5 symbols should be truncated."""
        from src.server.mcp.tools.stock_comparison_tools import register_stock_comparison_tools

        mcp = MagicMock()
        registered_fn = None

        def capture_tool(**kwargs):
            def decorator(fn):
                nonlocal registered_fn
                registered_fn = fn
                return fn
            return decorator

        mcp.tool = capture_tool
        register_stock_comparison_tools(mcp)

        mock_metrics = [{"symbol": f"S{i}", "name": f"Stock{i}"} for i in range(6)]

        with patch(
            "src.server.mcp.tools.stock_comparison_tools._fetch_stock_metrics",
            new_callable=AsyncMock,
            side_effect=mock_metrics[:5],
        ):
            result = await registered_fn(symbols="S0,S1,S2,S3,S4,S5")

        content = result["artifact"]["content"]
        data = content["data"]
        assert len(data["symbols"]) == 5

    def test_tool_group_registered(self):
        """Verify stock-comparison group is in TOOL_GROUPS."""
        from src.server.mcp.registry import TOOL_GROUPS
        names = [g.name for g in TOOL_GROUPS]
        assert "stock-comparison" in names
        group = [g for g in TOOL_GROUPS if g.name == "stock-comparison"][0]
        assert group.enabled
        assert group.count == 1
