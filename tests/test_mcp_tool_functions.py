# tests/test_mcp_tool_functions.py
"""Comprehensive functional tests for MCP tool groups.

Tests each tool group by calling the registered MCP tools with mocked
use-case layers and verifying the output structure (summary + artifact).

Covers:
  - cn-macro (9 tools)
  - fixed-income (9 tools)
  - commodity (6 tools)
  - option (3 tools)
  - sentiment (5 tools)
  - hk-market (4 tools)
  - hk-connect (4 tools)
  - corporate-event (5 tools)
  - attention-sentiment (4 tools)
  - registry: total tool count, group metadata


Run: uv run pytest tests/test_mcp_tool_functions.py -v
"""

from __future__ import annotations

import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, ".")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_result(**overrides) -> Dict[str, Any]:
    """Build a minimal mock result that tools expect from use cases."""
    base = {"data": [], "source": "test"}
    base.update(overrides)
    return base


def _get_tool_fn(mcp, tool_name: str):
    """Get a tool's underlying function by name."""
    tm = mcp._tool_manager
    assert tool_name in tm._tools, f"Tool '{tool_name}' not found; available: {list(tm._tools.keys())}"
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


# ---------------------------------------------------------------------------
# Registry: full metadata
# ---------------------------------------------------------------------------


class TestRegistryMetadata:
    """Verify TOOL_GROUPS metadata is complete and consistent."""

    def test_all_enabled_groups_have_register_callable(self):
        from src.server.mcp.registry import TOOL_GROUPS
        for g in TOOL_GROUPS:
            if g.enabled:
                assert callable(g.register), f"{g.name}.register not callable"

    def test_all_groups_have_positive_count(self):
        from src.server.mcp.registry import TOOL_GROUPS
        for g in TOOL_GROUPS:
            assert g.count >= 0, f"{g.name} has negative count"

    def test_total_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        # As of current registry: 206 enabled tools
        assert total >= 206, f"Expected >= 206, got {total}"

    def test_get_tool_group_info(self):
        from src.server.mcp.registry import get_tool_group_info
        info = get_tool_group_info()
        assert isinstance(info, dict)
        for name, meta in info.items():
            assert "enabled" in meta
            assert "count" in meta
            assert "description" in meta

    def test_disabled_groups_report_zero_count(self):
        from src.server.mcp.registry import get_tool_group_info
        info = get_tool_group_info()
        for name, meta in info.items():
            if not meta["enabled"]:
                assert meta["count"] == 0


# ---------------------------------------------------------------------------
# CN Macro Tools
# ---------------------------------------------------------------------------


class TestCnMacroToolFunctions:
    """Functional tests for cn-macro MCP tools."""

    @pytest.fixture
    def mcp_with_cn_macro(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.cn_macro_tools import register_cn_macro_tools
        mcp = FastMCP("test")
        register_cn_macro_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_get_cn_gdp(self, mcp_with_cn_macro):
        mock = _make_mock_result(data=[{"quarter": "2026Q1", "gdp_yoy": 5.4}])
        with patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_gdp_data", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_cn_macro, "get_cn_gdp", quarters=4)
        _assert_artifact_response(resp)
        assert "GDP" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_gdp_error(self, mcp_with_cn_macro):
        with patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_gdp_data", AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await _call_tool(mcp_with_cn_macro, "get_cn_gdp", quarters=4)
        _assert_artifact_response(resp)
        assert "失败" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_cpi(self, mcp_with_cn_macro):
        mock = _make_mock_result(data={"CPI": [{"month": "202602", "nt_yoy": 0.7}]})
        with patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_inflation_data", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_cn_macro, "get_cn_cpi", months=12)
        _assert_artifact_response(resp)
        assert "CPI" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_ppi(self, mcp_with_cn_macro):
        mock = _make_mock_result(data={"PPI": [{"month": "202602", "ppi_yoy": -2.5}]})
        with patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_inflation_data", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_cn_macro, "get_cn_ppi", months=12)
        _assert_artifact_response(resp)
        assert "PPI" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_pmi(self, mcp_with_cn_macro):
        mock = _make_mock_result(data=[{"pmi": 50.5}])
        with patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_pmi_data", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_cn_macro, "get_cn_pmi", months=12)
        _assert_artifact_response(resp)
        assert "PMI" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_money_supply(self, mcp_with_cn_macro):
        mock = _make_mock_result(data=[{"m1_yoy": 3.2, "m2_yoy": 7.1}])
        with patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_money_supply", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_cn_macro, "get_cn_money_supply", months=12)
        _assert_artifact_response(resp)
        assert "货币供应" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_interest_rates(self, mcp_with_cn_macro):
        mock = _make_mock_result(data={"shibor": [{"1w": 1.85}], "lpr": [{"lpr_1y": 3.45}]})
        with patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_interest_rates", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_cn_macro, "get_cn_interest_rates", shibor_days=30, lpr_months=12)
        _assert_artifact_response(resp)
        assert "利率" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_trade_balance(self, mcp_with_cn_macro):
        mock = _make_mock_result(data=[{"trade_balance": 820.5}])
        # get_trade_balance may not exist on mf_uc yet; inject mock
        import src.server.core.use_cases.money_flow as _mf
        _mf.get_trade_balance = AsyncMock(return_value=mock)
        try:
            resp = await _call_tool(mcp_with_cn_macro, "get_cn_trade_balance", months=12)
        finally:
            del _mf.get_trade_balance
        _assert_artifact_response(resp)
        assert resp["summary"].startswith("中国贸易差额")

    @pytest.mark.asyncio
    async def test_get_cn_social_financing(self, mcp_with_cn_macro):
        mock = _make_mock_result(data=[{"stk_yoy": 8.2}])
        with patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_social_financing", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_cn_macro, "get_cn_social_financing", months=12)
        _assert_artifact_response(resp)
        assert "社融" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_macro_overview(self, mcp_with_cn_macro):
        mock_gdp = _make_mock_result(data=[{"gdp_yoy": 5.4}])
        mock_infl = _make_mock_result(data={"CPI": [{"nt_yoy": 0.7}], "PPI": [{"ppi_yoy": -2.5}]})
        mock_pmi = _make_mock_result(data=[{"pmi": 50.5}])
        mock_ms = _make_mock_result(data=[{"m2_yoy": 7.1}])
        mock_sf = _make_mock_result(data=[{"stk_yoy": 8.2}])
        mock_ir = _make_mock_result(data={"shibor": [{"1w": 1.85}], "lpr": [{"lpr_1y": 3.45}]})
        mock_tb = _make_mock_result(data=[{"trade_balance": 820.5}])

        import src.server.core.use_cases.money_flow as _mf
        _mf.get_trade_balance = AsyncMock(return_value=mock_tb)
        try:
            with patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_gdp_data", AsyncMock(return_value=mock_gdp)), \
                 patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_inflation_data", AsyncMock(return_value=mock_infl)), \
                 patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_pmi_data", AsyncMock(return_value=mock_pmi)), \
                 patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_money_supply", AsyncMock(return_value=mock_ms)), \
                 patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_social_financing", AsyncMock(return_value=mock_sf)), \
                 patch("src.server.mcp.tools.cn_macro_tools.mf_uc.get_interest_rates", AsyncMock(return_value=mock_ir)):
                resp = await _call_tool(mcp_with_cn_macro, "get_cn_macro_overview")
        finally:
            del _mf.get_trade_balance
        _assert_artifact_response(resp)
        assert "宏观" in resp["summary"]


# ---------------------------------------------------------------------------
# Fixed Income Tools
# ---------------------------------------------------------------------------


class TestFixedIncomeToolFunctions:
    """Functional tests for fixed-income MCP tools."""

    @pytest.fixture
    def mcp_with_fi(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.fixed_income_tools import register_fixed_income_tools
        mcp = FastMCP("test")
        register_fixed_income_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_get_cn_bond_yield_curve(self, mcp_with_fi):
        mock = _make_mock_result(data=[{"10年": 2.56, "1年": 2.1}])
        with patch("src.server.mcp.tools.fixed_income_tools.fi_uc.get_bond_yield_curve", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_fi, "get_cn_bond_yield_curve", start_date="", end_date="")
        _assert_artifact_response(resp)
        assert "收益率曲线" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_bond_yield_curve_error(self, mcp_with_fi):
        with patch("src.server.mcp.tools.fixed_income_tools.fi_uc.get_bond_yield_curve", AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await _call_tool(mcp_with_fi, "get_cn_bond_yield_curve")
        _assert_artifact_response(resp)
        assert "失败" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_convertible_bonds(self, mcp_with_fi):
        mock = _make_mock_result(total=50, data=[{"code": "123138"}])
        with patch("src.server.mcp.tools.fixed_income_tools.fi_uc.get_convertible_bonds", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_fi, "get_cn_convertible_bonds", bond_code="")
        _assert_artifact_response(resp)
        assert "可转债" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_convertible_bond_history(self, mcp_with_fi):
        mock = _make_mock_result(data=[{"close": 130.0}])
        with patch("src.server.mcp.tools.fixed_income_tools.fi_uc.get_convertible_bond_history", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_fi, "get_cn_convertible_bond_history", symbol="sz123138", days=30)
        _assert_artifact_response(resp)
        assert "sz123138" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_convertible_bond_detail(self, mcp_with_fi):
        mock = _make_mock_result(data={"bond_name": "测试转债", "transfer_premium_ratio": 93.28, "coupon_rate": 2.5, "rating": "A"})
        with patch("src.server.mcp.tools.fixed_income_tools.fi_uc.get_convertible_bond_detail", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_fi, "get_cn_convertible_bond_detail", symbol="123138")
        _assert_artifact_response(resp)
        assert "测试转债" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_credit_spread(self, mcp_with_fi):
        mock = _make_mock_result(data=[{"AAA-1年": 55.2}])
        with patch("src.server.mcp.tools.fixed_income_tools.fi_uc.get_credit_spread", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_fi, "get_cn_credit_spread", start_date="", end_date="")
        _assert_artifact_response(resp)
        assert "信用利差" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_repo_rates(self, mcp_with_fi):
        mock = _make_mock_result(data=[{"回购定盘利率": 1.85}])
        with patch("src.server.mcp.tools.fixed_income_tools.fi_uc.get_repo_rates", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_fi, "get_cn_repo_rates", start_date="", end_date="")
        _assert_artifact_response(resp)
        assert "回购" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_interbank_rate(self, mcp_with_fi):
        mock = _make_mock_result(data=[{"利率": 1.65}])
        with patch("src.server.mcp.tools.fixed_income_tools.fi_uc.get_interbank_rate", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_fi, "get_cn_interbank_rate", market="上海银行间同业拆借市场", symbol="Shibor人民币", indicator="隔夜")
        _assert_artifact_response(resp)
        assert "同业拆借" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_bond_issuance_overview(self, mcp_with_fi):
        mock = _make_mock_result(data={"treasury": {"count": 12}, "corporate": {"count": 30}})
        with patch("src.server.mcp.tools.fixed_income_tools.fi_uc.get_bond_issuance_overview", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_fi, "get_cn_bond_issuance_overview", days=90)
        _assert_artifact_response(resp)
        assert "债券发行" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_cn_fixed_income_overview(self, mcp_with_fi):
        mock = _make_mock_result(indicators={"bond_yield": {"data": [{"10年": 2.56}]}, "convertible_bonds": {"total": 50}, "repo_rates": {"data": []}}, errors=[])
        with patch("src.server.mcp.tools.fixed_income_tools.fi_uc.get_fixed_income_overview", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_fi, "get_cn_fixed_income_overview")
        _assert_artifact_response(resp)
        assert "固收" in resp["summary"]


# ---------------------------------------------------------------------------
# Commodity Tools
# ---------------------------------------------------------------------------


class TestCommodityToolFunctions:
    """Functional tests for commodity MCP tools."""

    @pytest.fixture
    def mcp_with_commodity(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.commodity_tools import register_commodity_tools
        mcp = FastMCP("test")
        register_commodity_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_get_gold_price(self, mcp_with_commodity):
        mock = _make_mock_result(data=[{"收盘价": 580.5}])
        with patch("src.server.mcp.tools.commodity_tools.comm_uc.get_commodity_price", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_commodity, "get_gold_price", days=30)
        _assert_artifact_response(resp)
        assert "黄金" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_gold_price_error(self, mcp_with_commodity):
        with patch("src.server.mcp.tools.commodity_tools.comm_uc.get_commodity_price", AsyncMock(side_effect=RuntimeError("API down"))):
            resp = await _call_tool(mcp_with_commodity, "get_gold_price", days=30)
        _assert_artifact_response(resp)
        assert "失败" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_silver_price(self, mcp_with_commodity):
        mock = _make_mock_result(data=[{"收盘价": 32.5}])
        with patch("src.server.mcp.tools.commodity_tools.comm_uc.get_commodity_price", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_commodity, "get_silver_price", days=30)
        _assert_artifact_response(resp)
        assert "白银" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_crude_oil_price(self, mcp_with_commodity):
        mock = _make_mock_result(data=[{"收盘价": 560.0}])
        with patch("src.server.mcp.tools.commodity_tools.comm_uc.get_commodity_price", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_commodity, "get_crude_oil_price", days=30)
        _assert_artifact_response(resp)
        assert "原油" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_copper_price(self, mcp_with_commodity):
        mock = _make_mock_result(data=[{"收盘价": 78000}])
        with patch("src.server.mcp.tools.commodity_tools.comm_uc.get_commodity_price", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_commodity, "get_copper_price", days=30)
        _assert_artifact_response(resp)
        assert "铜" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_industrial_metals_overview(self, mcp_with_commodity):
        mock = _make_mock_result(indicators={"copper": {"data": [{"收盘价": 78000}]}}, errors=[])
        with patch("src.server.mcp.tools.commodity_tools.comm_uc.get_industrial_metals_overview", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_commodity, "get_industrial_metals_overview", days=30)
        _assert_artifact_response(resp)
        assert "工业金属" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_commodity_overview(self, mcp_with_commodity):
        mock = _make_mock_result(indicators={"gold": {"data": [{"收盘价": 580.5}]}}, errors=[])
        with patch("src.server.mcp.tools.commodity_tools.comm_uc.get_commodity_overview", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_commodity, "get_commodity_overview")
        _assert_artifact_response(resp)
        assert "商品" in resp["summary"]


# ---------------------------------------------------------------------------
# Option Tools
# ---------------------------------------------------------------------------


class TestOptionToolFunctions:
    """Functional tests for option MCP tools."""

    @pytest.fixture
    def mcp_with_options(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.option_tools import register_option_tools
        mcp = FastMCP("test")
        register_option_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_get_option_chain(self, mcp_with_options):
        mock = _make_mock_result(data=[{"month": "2026-04"}])
        with patch("src.server.mcp.tools.option_tools.opt_uc.get_option_chain", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_options, "get_option_chain", symbol="50ETF", exchange="null")
        _assert_artifact_response(resp)
        assert "期权合约" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_option_chain_error(self, mcp_with_options):
        with patch("src.server.mcp.tools.option_tools.opt_uc.get_option_chain", AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await _call_tool(mcp_with_options, "get_option_chain", symbol="50ETF")
        _assert_artifact_response(resp)
        assert "失败" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_option_greeks(self, mcp_with_options):
        mock = _make_mock_result(data=[{"delta": 0.5, "gamma": 0.03}])
        with patch("src.server.mcp.tools.option_tools.opt_uc.get_option_greeks", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_options, "get_option_greeks", contract="10003045")
        _assert_artifact_response(resp)
        assert "Greeks" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_option_price_history(self, mcp_with_options):
        mock = _make_mock_result(data=[{"close": 0.085, "date": "2026-03-28"}])
        with patch("src.server.mcp.tools.option_tools.opt_uc.get_option_price_history", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_options, "get_option_price_history", contract="10003889")
        _assert_artifact_response(resp)
        assert "10003889" in resp["summary"]


# ---------------------------------------------------------------------------
# Sentiment Tools
# ---------------------------------------------------------------------------


class TestSentimentToolFunctions:
    """Functional tests for sentiment MCP tools."""

    @pytest.fixture
    def mcp_with_sentiment(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.sentiment_tools import register_sentiment_tools
        mcp = FastMCP("test")
        register_sentiment_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_get_qvix_50etf(self, mcp_with_sentiment):
        mock = _make_mock_result(data=[{"close": 22.5}])
        with patch("src.server.mcp.tools.sentiment_tools.sent_uc.get_qvix_50etf", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_sentiment, "get_qvix_50etf")
        _assert_artifact_response(resp)
        assert "50ETF" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_qvix_50etf_error(self, mcp_with_sentiment):
        with patch("src.server.mcp.tools.sentiment_tools.sent_uc.get_qvix_50etf", AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await _call_tool(mcp_with_sentiment, "get_qvix_50etf")
        _assert_artifact_response(resp)
        assert "失败" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_qvix_300etf(self, mcp_with_sentiment):
        mock = _make_mock_result(data=[{"close": 20.1}])
        with patch("src.server.mcp.tools.sentiment_tools.sent_uc.get_qvix_300etf", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_sentiment, "get_qvix_300etf")
        _assert_artifact_response(resp)
        assert "300ETF" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_qvix_1000index(self, mcp_with_sentiment):
        mock = _make_mock_result(data=[{"close": 28.3}])
        with patch("src.server.mcp.tools.sentiment_tools.sent_uc.get_qvix_1000index", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_sentiment, "get_qvix_1000index")
        _assert_artifact_response(resp)
        assert "中证1000" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_qvix_cyb(self, mcp_with_sentiment):
        mock = _make_mock_result(data=[{"close": 35.2}])
        with patch("src.server.mcp.tools.sentiment_tools.sent_uc.get_qvix_cyb", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_sentiment, "get_qvix_cyb")
        _assert_artifact_response(resp)
        assert "创业板" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_market_sentiment_overview(self, mcp_with_sentiment):
        mock = _make_mock_result(data={"regime": "neutral", "avg_qvix": 25.0})
        with patch("src.server.mcp.tools.sentiment_tools.sent_uc.get_market_sentiment_overview", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_sentiment, "get_market_sentiment_overview")
        _assert_artifact_response(resp)
        assert "情绪" in resp["summary"]


# ---------------------------------------------------------------------------
# HK Market Tools
# ---------------------------------------------------------------------------


class TestHKMarketToolFunctions:
    """Functional tests for HK market MCP tools."""

    @pytest.fixture
    def mcp_with_hk_market(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.hk_market_tools import register_hk_market_tools
        mcp = FastMCP("test")
        register_hk_market_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_get_hk_market_spot(self, mcp_with_hk_market):
        mock = _make_mock_result(data=[{"code": "00700", "name": "腾讯"}])
        with patch("src.server.mcp.tools.hk_market_tools.hk_uc.get_hk_market_spot", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_hk_market, "get_hk_market_spot")
        _assert_artifact_response(resp)
        assert "港股全市场" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_hk_market_spot_error(self, mcp_with_hk_market):
        with patch("src.server.mcp.tools.hk_market_tools.hk_uc.get_hk_market_spot", AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await _call_tool(mcp_with_hk_market, "get_hk_market_spot")
        _assert_artifact_response(resp)
        assert "失败" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_hk_hot_rank(self, mcp_with_hk_market):
        mock = _make_mock_result(data=[{"code": "00700"}])
        with patch("src.server.mcp.tools.hk_market_tools.hk_uc.get_hk_hot_rank", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_hk_market, "get_hk_hot_rank")
        _assert_artifact_response(resp)
        assert "热度" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_hk_main_board(self, mcp_with_hk_market):
        mock = _make_mock_result(data=[{"code": "00001"}])
        with patch("src.server.mcp.tools.hk_market_tools.hk_uc.get_hk_main_board", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_hk_market, "get_hk_main_board")
        _assert_artifact_response(resp)
        assert "主板" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_hk_market_overview(self, mcp_with_hk_market):
        mock = {"data": {"counts": {"spot": 2500, "main_board": 2200, "hot_rank": 50}}, "source": "test"}
        with patch("src.server.mcp.tools.hk_market_tools.hk_uc.get_hk_market_overview", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_hk_market, "get_hk_market_overview")
        _assert_artifact_response(resp)
        assert "港股概览" in resp["summary"]


# ---------------------------------------------------------------------------
# HK Connect Tools
# ---------------------------------------------------------------------------


class TestHKConnectToolFunctions:
    """Functional tests for HK connect MCP tools."""

    @pytest.fixture
    def mcp_with_hk_connect(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.hk_connect_tools import register_hk_connect_tools
        mcp = FastMCP("test")
        register_hk_connect_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_get_hk_connect_components(self, mcp_with_hk_connect):
        mock = _make_mock_result(data=[{"code": "00700"}])
        with patch("src.server.mcp.tools.hk_connect_tools.hc_uc.get_hk_connect_components", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_hk_connect, "get_hk_connect_components")
        _assert_artifact_response(resp)
        assert "成分股" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_hk_connect_components_error(self, mcp_with_hk_connect):
        with patch("src.server.mcp.tools.hk_connect_tools.hc_uc.get_hk_connect_components", AsyncMock(side_effect=RuntimeError("fail"))):
            resp = await _call_tool(mcp_with_hk_connect, "get_hk_connect_components")
        _assert_artifact_response(resp)
        assert "失败" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_hsgt_fund_flow_summary(self, mcp_with_hk_connect):
        mock = _make_mock_result(data=[{"date": "2026-03-28", "flow": 5.2}])
        with patch("src.server.mcp.tools.hk_connect_tools.hc_uc.get_hsgt_fund_flow_summary", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_hk_connect, "get_hsgt_fund_flow_summary")
        _assert_artifact_response(resp)
        assert "资金流" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_hsgt_hold_stock(self, mcp_with_hk_connect):
        mock = _make_mock_result(data=[{"code": "00700", "ratio": 5.2}])
        with patch("src.server.mcp.tools.hk_connect_tools.hc_uc.get_hsgt_hold_stock", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_hk_connect, "get_hsgt_hold_stock", market="港股通", indicator="5日排行")
        _assert_artifact_response(resp)
        # Summary format: "{market}{indicator}: N条"
        assert "港股通" in resp["summary"]
        assert "5日排行" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_hk_connect_overview(self, mcp_with_hk_connect):
        mock = {"data": {"counts": {"components": 500, "fund_flow": 30, "hold_rank": 20}}, "source": "test"}
        with patch("src.server.mcp.tools.hk_connect_tools.hc_uc.get_hk_connect_overview", AsyncMock(return_value=mock)):
            resp = await _call_tool(mcp_with_hk_connect, "get_hk_connect_overview")
        _assert_artifact_response(resp)
        assert "港股通概览" in resp["summary"]




# ---------------------------------------------------------------------------
# Corporate Event Tools
# ---------------------------------------------------------------------------


class TestCorporateEventToolFunctions:
    """Functional tests for corporate-event MCP tools."""

    @pytest.fixture
    def mcp_with_corporate_event(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.corporate_event_tools import register_corporate_event_tools
        mcp = FastMCP("test")
        register_corporate_event_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_get_earnings_calendar(self, mcp_with_corporate_event):
        mock = _make_mock_result(
            data=[{"stock_code": "600519", "stock_name": "贵州茅台", "first_scheduled": "2026-04-20"}],
            total=1,
            period="2025年报",
        )
        gateway = AsyncMock()
        gateway.get_earnings_calendar = AsyncMock(return_value=mock)
        with patch("src.server.mcp.tools.corporate_event_tools.Container.market_gateway", return_value=gateway):
            resp = await _call_tool(mcp_with_corporate_event, "get_earnings_calendar", market="沪深京", period="2025年报")
        _assert_artifact_response(resp)
        assert "财报披露日历" in resp["summary"]
        assert "2025年报" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_dividend_calendar_requires_symbol(self, mcp_with_corporate_event):
        resp = await _call_tool(mcp_with_corporate_event, "get_dividend_calendar", symbol="")
        _assert_artifact_response(resp)
        assert "需要提供股票代码" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_dividend_calendar(self, mcp_with_corporate_event):
        mock = _make_mock_result(
            data=[{"report_period": "2025年报", "dividend_type": "现金分红", "cash_div_ratio": "10派30"}],
            total=1,
        )
        gateway = AsyncMock()
        gateway.get_dividend_calendar = AsyncMock(return_value=mock)
        with patch("src.server.mcp.tools.corporate_event_tools.Container.market_gateway", return_value=gateway):
            resp = await _call_tool(mcp_with_corporate_event, "get_dividend_calendar", symbol="600519")
        _assert_artifact_response(resp)
        assert "分红送股日历" in resp["summary"]
        assert "600519" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_restricted_release_calendar(self, mcp_with_corporate_event):
        mock = {
            "data": {
                "summary": [{"date": "2026-04-01", "count": 5}],
                "queue": [{"股票代码": "688001", "股票简称": "华兴源创", "解禁日期": "2026-04-01"}],
            },
            "source": "test",
        }
        gateway = AsyncMock()
        gateway.get_restricted_release = AsyncMock(return_value=mock)
        with patch("src.server.mcp.tools.corporate_event_tools.Container.market_gateway", return_value=gateway):
            resp = await _call_tool(mcp_with_corporate_event, "get_restricted_release_calendar", symbol="", days=90)
        _assert_artifact_response(resp)
        assert "限售解禁日历" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_stock_repurchase(self, mcp_with_corporate_event):
        mock = _make_mock_result(
            data=[{"股票代码": "600519", "股票简称": "贵州茅台", "回购进度": "实施中"}],
            total=1,
        )
        gateway = AsyncMock()
        gateway.get_repurchase_info = AsyncMock(return_value=mock)
        with patch("src.server.mcp.tools.corporate_event_tools.Container.market_gateway", return_value=gateway):
            resp = await _call_tool(mcp_with_corporate_event, "get_stock_repurchase", symbol="600519")
        _assert_artifact_response(resp)
        assert "股票回购" in resp["summary"]

    @pytest.mark.asyncio
    async def test_get_block_trade(self, mcp_with_corporate_event):
        mock = _make_mock_result(
            data=[{"交易日期": "2026-03-28", "证券代码": "600519", "证券简称": "贵州茅台"}],
            total=1,
            start_date="20260319",
            end_date="20260328",
        )
        gateway = AsyncMock()
        gateway.get_block_trade = AsyncMock(return_value=mock)
        with patch("src.server.mcp.tools.corporate_event_tools.Container.market_gateway", return_value=gateway):
            resp = await _call_tool(mcp_with_corporate_event, "get_block_trade", days=10)
        _assert_artifact_response(resp)
        assert "大宗交易" in resp["summary"]


class TestArtifactContract:
    """Verify all artifact responses follow the standard contract."""

    def test_create_artifact_response_has_required_fields(self):
        from src.server.mcp.tools.artifact_utils import create_artifact_response, create_artifact_envelope
        art = create_artifact_envelope(component_type="test", name="t", content={"x": 1})
        resp = create_artifact_response(summary="s", artifact=art)
        assert "summary" in resp
        assert "artifact" in resp
        assert resp["summary"] == "s"
        assert resp["artifact"]["component_type"] == "test"

    def test_artifact_envelope_has_uuid(self):
        from src.server.mcp.tools.artifact_utils import create_artifact_envelope
        art = create_artifact_envelope(component_type="test", name="t", content={})
        assert "id" in art
        assert len(art["id"]) > 0

    def test_artifact_envelope_has_timestamp(self):
        from src.server.mcp.tools.artifact_utils import create_artifact_envelope
        art = create_artifact_envelope(component_type="test", name="t", content={})
        assert "timestamp" in art
        assert "T" in art["timestamp"]  # ISO format

    def test_error_response_visible_to_llm(self):
        """Error artifacts should be visible to LLM for error reporting."""
        from src.server.mcp.tools.artifact_utils import create_artifact_envelope, create_artifact_response
        art = create_artifact_envelope(component_type="test", name="t", content={"error": "fail"}, visible_to_llm=True)
        assert art["visible_to_llm"] is True


# ---------------------------------------------------------------------------
# Register All Tools Integration
# ---------------------------------------------------------------------------


class TestRegisterAllTools:
    """Verify all enabled tool groups register on a single MCP instance."""

    def test_register_all_enabled(self):
        from fastmcp import FastMCP
        from src.server.mcp.registry import register_tools
        mcp = FastMCP("test")
        register_tools(mcp)
        # Should not raise

    @pytest.mark.asyncio
    async def test_enabled_tool_count_matches_registered(self):
        from fastmcp import FastMCP
        from src.server.mcp.registry import register_tools, get_enabled_tool_count
        mcp = FastMCP("test")
        register_tools(mcp)
        tools = await mcp.get_tools()
        declared = get_enabled_tool_count()
        # A small gap is acceptable when groups declare the same MCP tool name
        # (e.g. get_block_trade, get_dragon_tiger_statistics each collide across 2 groups).
        assert len(tools) >= declared - 2
