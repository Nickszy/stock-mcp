# tests/test_fact_pack.py
"""Tests for COL-148: Stock Fact Pack system.

Verify get_stock_fact_pack aggregates data from fact categories
and produces the correct contract structure.

Adapter returns:
  entity: {"symbol": str, "type": "stock"}
  facts: dict of category → data
  source_trace: dict of category → {provider, ...}
  coverage: dict of category → status string
  missing_fields: list of str
  categories_fetched: int
  categories_total: 8

Run: uv run pytest tests/test_fact_pack.py -v
"""

from __future__ import annotations

import asyncio
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


def _mock_asset_info(name: str, symbol: str, exchange: str = "SSE"):
    """Create a mock Asset object with to_dict()."""
    obj = MagicMock()
    obj.to_dict.return_value = {
        "symbol": symbol,
        "name": name,
        "exchange": exchange,
        "asset_type": "stock",
    }
    return obj


# =====================================================================
# Adapter Method Tests
# =====================================================================


class TestFactPackAdapter:
    """Verify get_stock_fact_pack adapter method."""

    def test_returns_correct_structure(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter

        adapter = AkshareAdapter(mock_cache)

        with patch.object(adapter, "get_asset_info", new_callable=AsyncMock) as m_info, \
             patch.object(adapter, "get_financials", new_callable=AsyncMock) as m_fin, \
             patch.object(adapter, "_get_valuation_raw", new_callable=AsyncMock) as m_val, \
             patch.object(adapter, "get_money_flow", new_callable=AsyncMock) as m_mf, \
             patch.object(adapter, "get_stock_top10_shareholders", new_callable=AsyncMock) as m_top10, \
             patch.object(adapter, "get_stock_shareholder_changes", new_callable=AsyncMock) as m_chg, \
             patch.object(adapter, "get_dividend_info", new_callable=AsyncMock) as m_div, \
             patch.object(adapter, "get_repurchase_info", new_callable=AsyncMock) as m_rep, \
             patch.object(adapter, "get_restricted_release", new_callable=AsyncMock) as m_rst, \
             patch.object(adapter, "get_mainbz_info", new_callable=AsyncMock) as m_biz:

            m_info.return_value = _mock_asset_info("贵州茅台", "600519")
            m_fin.return_value = {"revenue": 100}
            m_val.return_value = {"pe": 30.5}
            m_mf.return_value = {"net_inflow": 1e8}
            m_top10.return_value = {"data": [{"holder_name": "A", "hold_qty": 100}]}
            m_chg.return_value = {"data": [{"total": 150000}]}
            m_div.return_value = {"dividend_yield": 0.02}
            m_rep.return_value = {"data": [{"symbol": "600519", "progress": "实施中", "amount": 10e8}]}
            m_rst.return_value = {"data": [{"symbol": "600519", "release_date": "2025-06-01", "release_volume": 1000}]}
            m_biz.return_value = [{"biz": "白酒"}]

            result = _run(adapter.get_stock_fact_pack(symbol="600519"))

        # Top-level structure
        assert "entity" in result
        assert "facts" in result
        assert "source_trace" in result
        assert "coverage" in result
        assert "missing_fields" in result
        assert "categories_fetched" in result
        assert "categories_total" in result
        assert "elapsed_seconds" in result

        # Entity has symbol and type
        assert result["entity"]["symbol"] == "600519"
        assert result["entity"]["type"] == "stock"

        # Facts categories populated
        facts = result["facts"]
        assert "security_master" in facts
        assert facts["security_master"]["name"] == "贵州茅台"

        # Coverage is a dict
        assert isinstance(result["coverage"], dict)

        # categories_total is 11 (added earnings_estimates)
        assert result["categories_total"] == 11

    def test_handles_sub_method_failure_gracefully(self, mock_cache):
        """When a sub-method fails, fact pack should still return partial data."""
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter

        adapter = AkshareAdapter(mock_cache)

        with patch.object(adapter, "get_asset_info", new_callable=AsyncMock) as m_info, \
             patch.object(adapter, "get_financials", new_callable=AsyncMock, side_effect=Exception("API error")), \
             patch.object(adapter, "_get_valuation_raw", new_callable=AsyncMock) as m_val, \
             patch.object(adapter, "get_money_flow", new_callable=AsyncMock) as m_mf, \
             patch.object(adapter, "get_stock_top10_shareholders", new_callable=AsyncMock) as m_top10, \
             patch.object(adapter, "get_dividend_info", new_callable=AsyncMock) as m_div, \
             patch.object(adapter, "get_repurchase_info", new_callable=AsyncMock) as m_rep, \
             patch.object(adapter, "get_restricted_release", new_callable=AsyncMock) as m_rst, \
             patch.object(adapter, "get_profit_forecast", new_callable=AsyncMock) as m_forecast, \
             patch.object(adapter, "get_mainbz_info", new_callable=AsyncMock) as m_biz:

            m_info.return_value = _mock_asset_info("贵州茅台", "600519")
            m_val.return_value = {"pe": 30.5}
            m_mf.return_value = {}
            m_top10.return_value = {"data": []}
            m_div.return_value = {}
            m_rep.return_value = None
            m_rst.return_value = None
            m_forecast.return_value = {"rows": [], "source": "akshare"}
            m_biz.return_value = [{"biz": "白酒"}]

            # Mock _run for company_master and peers (new categories)
            original_run = adapter._run
            async def _mock_run(func, **kwargs):
                func_name = getattr(func, "__name__", "")
                if "stock_individual_info_em" in func_name:
                    import pandas as pd
                    return pd.DataFrame({"item": ["股票简称"], "value": ["测试"]})
                if "stock_board_industry_cons_em" in func_name:
                    import pandas as pd
                    return pd.DataFrame()
                return await original_run(func, **kwargs)

            with patch.object(adapter, "_run", side_effect=_mock_run):
                result = _run(adapter.get_stock_fact_pack(symbol="600519"))

        # Should still succeed with partial data
        assert "facts" in result
        # financial coverage should show error
        assert result["coverage"].get("financial", "").startswith("error")

    def test_coverage_dict_has_categories(self, mock_cache):
        """Coverage dict should have entries for all categories."""
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter

        adapter = AkshareAdapter(mock_cache)

        with patch.object(adapter, "get_asset_info", new_callable=AsyncMock) as m_info, \
             patch.object(adapter, "get_financials", new_callable=AsyncMock) as m_fin, \
             patch.object(adapter, "_get_valuation_raw", new_callable=AsyncMock) as m_val, \
             patch.object(adapter, "get_money_flow", new_callable=AsyncMock) as m_mf, \
             patch.object(adapter, "get_stock_top10_shareholders", new_callable=AsyncMock) as m_top10, \
             patch.object(adapter, "get_stock_shareholder_changes", new_callable=AsyncMock) as m_chg, \
             patch.object(adapter, "get_dividend_info", new_callable=AsyncMock) as m_div, \
             patch.object(adapter, "get_repurchase_info", new_callable=AsyncMock) as m_rep, \
             patch.object(adapter, "get_restricted_release", new_callable=AsyncMock) as m_rst, \
             patch.object(adapter, "get_mainbz_info", new_callable=AsyncMock) as m_biz:

            for m in [m_info, m_fin, m_val, m_mf, m_top10, m_chg, m_div, m_rep, m_rst, m_biz]:
                m.return_value = {}

            m_info.return_value = _mock_asset_info("测试", "600000")

            # Mock _run for company_master and peers (new categories)
            original_run = adapter._run
            async def _mock_run_coverage(func, **kwargs):
                func_name = getattr(func, "__name__", "")
                if "stock_individual_info_em" in func_name:
                    import pandas as pd
                    return pd.DataFrame()
                if "stock_board_industry_cons_em" in func_name:
                    import pandas as pd
                    return pd.DataFrame()
                return await original_run(func, **kwargs)

            with patch.object(adapter, "_run", side_effect=_mock_run_coverage):
                result = _run(adapter.get_stock_fact_pack(symbol="600000"))

        coverage = result["coverage"]
        # Should have all 8 categories
        expected_cats = {
            "security_master", "financial", "market", "governance",
            "events", "business_structure", "company_master", "peers",
        }
        assert expected_cats.issubset(set(coverage.keys()))


# =====================================================================
# MCP Tool Contract Tests
# =====================================================================


class TestFactPackMCPTool:
    """Verify fact pack MCP tool produces unified contract."""

    def test_tool_contract_structure(self, mock_cache):
        """Verify the MCP tool returns correct artifact contract."""
        from src.server.mcp.tools.fact_pack_tools import register_fact_pack_tools
        from src.server.core.dependencies import Container

        mock_pack = {
            "source": "akshare",
            "entity": {"symbol": "600519", "type": "stock"},
            "facts": {
                "security_master": {"code": "600519", "name": "贵州茅台"},
                "financial": {"revenue": 100},
                "market": {"pe": 30.5},
                "governance": {},
                "events": {},
                "business_structure": [],
            },
            "source_trace": {"valuation": {"provider": "akshare"}},
            "coverage": {
                "security_master": "complete",
                "financial": "complete",
                "market": "partial",
                "governance": "missing",
                "events": "missing",
                "business_structure": "missing",
                "company_master": "not_implemented",
                "peers": "not_implemented",
            },
            "missing_fields": ["governance", "events", "business_structure", "company_master", "peers"],
            "categories_fetched": 3,
            "categories_total": 8,
            "elapsed_seconds": 1.2,
        }

        mock_gw = MagicMock()
        mock_gw.get_stock_fact_pack = AsyncMock(return_value=mock_pack)

        with patch.object(Container, "market_gateway", return_value=mock_gw):
            # Create a mock MCP to capture the tool
            captured = {}

            class MockMCP:
                def tool(self, **kwargs):
                    def decorator(fn):
                        key = frozenset(kwargs.get("tags", set()))
                        captured[key] = fn
                        return fn
                    return decorator

            register_fact_pack_tools(MockMCP())

            tool_fn = list(captured.values())[0]
            result = _run(tool_fn(symbol="600519"))

        # Verify unified contract
        assert "summary" in result
        assert "artifact" in result
        content = result["artifact"]["content"]
        assert content["symbol"] == "600519"
        assert content["source"]["provider"] == "akshare"
        assert "data" in content
        assert content["data"]["entity"]["symbol"] == "600519"
        assert "markdown" in content
        # Name should come from security_master
        assert "贵州茅台" in content["data"]["facts"]["security_master"]["name"]


# =====================================================================
# REST Route Contract Tests
# =====================================================================


class TestFactPackRestRoute:
    """Verify stock fact-pack REST route exposes stable web-friendly fields."""

    def test_stock_fact_pack_rest_includes_web_facts(self):
        from src.server.api.routes.fact_pack import get_stock_fact_pack
        from src.server.core.dependencies import Container

        mock_pack = {
            "source": "akshare",
            "entity": {"symbol": "600519", "type": "stock"},
            "facts": {
                "security_master": {"code": "600519", "name": "贵州茅台"},
                "market": {
                    "valuation": {"pe": 30.5, "pb": 10.2, "total_mv": 123456789},
                },
                "financial": {
                    "financial_indicators": [{"净资产收益率(%)": 31.0, "销售毛利率(%)": 92.0}],
                    "balance_sheet": [{"资产总计": 1e12}],
                    "cash_flow": [],
                },
                "governance": {
                    "top10_shareholders": [{"holder_name": "A", "hold_qty": 100}],
                },
                "events": {
                    "dividends": {"dividend_yield": 0.02},
                },
                "business_structure": {
                    "rows": [
                        {"分类类型": "按产品分类", "主营构成": "白酒", "主营收入占比": 95.0},
                    ],
                },
            },
            "coverage": {"market": "complete", "financial": "complete"},
            "source_trace": {"valuation": {"provider": "akshare"}},
            "missing_fields": [],
            "categories_fetched": 5,
            "categories_total": 11,
        }

        mock_gw = MagicMock()
        mock_gw.get_stock_fact_pack = AsyncMock(return_value=mock_pack)
        mock_gw.get_asset_price = AsyncMock(return_value=None)
        mock_gw.calculate_technical_indicators = AsyncMock(return_value={"data": {}})

        with patch.object(Container, "market_gateway", return_value=mock_gw):
            result = _run(
                get_stock_fact_pack(
                    symbol="600519",
                    format="json",
                    accept="application/json",
                )
            )

        assert result["code"] == 0
        payload = result["data"]
        # rest_response flattens: {symbol, source, entity, facts, ...}
        assert payload["symbol"] == "600519"
        assert "entity" in payload
        assert payload["entity"]["symbol"] == "600519"
        assert "facts" in payload
        facts = payload["facts"]
        assert "valuation" in facts
        assert facts["valuation"]["pe_ttm"] == 30.5
        assert "profitability" in facts
        assert facts["profitability"]["roe"] == 31.0
        assert "dividend" in facts
        assert "shareholder" in facts
        assert "revenue_breakdown" in facts
        assert "technical" in facts
        assert "price" in facts


# =====================================================================
# Registry Tests
# =====================================================================


class TestFactPackRegistry:
    """Verify registry is consistent after COL-148."""

    def test_total_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total == 173, f"Expected 173, got {total}"

    def test_fact_pack_group_present(self):
        from src.server.mcp.registry import TOOL_GROUPS
        names = {g.name for g in TOOL_GROUPS}
        assert "fact-pack" in names

    def test_fact_pack_group_count(self):
        from src.server.mcp.registry import TOOL_GROUPS
        fp = [g for g in TOOL_GROUPS if g.name == "fact-pack"]
        assert len(fp) == 1
        assert fp[0].count == 7  # stock + fund + market + us_stock + etf + index + sector
        assert fp[0].enabled is True


# =====================================================================
# Fund Fact Pack Tests (COL-150)
# =====================================================================


class TestFundFactPackAdapter:
    """Verify get_fund_fact_pack adapter method."""

    def test_returns_correct_structure(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter

        adapter = AkshareAdapter(mock_cache)

        with patch.object(adapter, "get_fund_detail", new_callable=AsyncMock) as m_detail, \
             patch.object(adapter, "get_fund_nav", new_callable=AsyncMock) as m_nav, \
             patch.object(adapter, "get_fund_performance", new_callable=AsyncMock) as m_perf, \
             patch.object(adapter, "get_fund_valuation", new_callable=AsyncMock) as m_val, \
             patch.object(adapter, "get_fund_holdings", new_callable=AsyncMock) as m_hold, \
             patch.object(adapter, "get_fund_manager", new_callable=AsyncMock) as m_mgr, \
             patch.object(adapter, "get_fund_scale", new_callable=AsyncMock) as m_scale, \
             patch.object(adapter, "get_fund_manager_changes", new_callable=AsyncMock) as m_mc:

            m_detail.return_value = {
                "fund_code": "110011", "source": "akshare",
                "基金简称": "易方达中小盘混合",
                "基金类型": "混合型",
                "asset_allocation": [{"type": "股票", "ratio": "85%"}],
            }
            m_nav.return_value = {"data": [{"date": "2025-01-01", "nav": 3.5}]}
            m_perf.return_value = {"achievement": [{"period": "1年", "return": 0.15}]}
            m_val.return_value = {"估值": 3.6}
            m_hold.return_value = {"data": [{"股票代码": "600519", "股票名称": "贵州茅台"}], "total": 10}
            m_mgr.return_value = {"data": [{"姓名": "张坤", "基金代码": "110011"}]}
            m_scale.return_value = {"基金家数": 10000}
            m_mc.return_value = {"changes": [{"date": "2024-01-01", "title": "关于增聘的公告", "change_type": "appoint"}], "total": 1}

            result = _run(adapter.get_fund_fact_pack(fund_code="110011"))

        # Top-level structure
        assert "entity" in result
        assert "facts" in result
        assert "source_trace" in result
        assert "coverage" in result
        assert "missing_fields" in result
        assert "categories_fetched" in result
        assert "categories_total" in result

        # Entity
        assert result["entity"]["fund_code"] == "110011"
        assert result["entity"]["type"] == "fund"

        # Facts categories
        facts = result["facts"]
        assert "master" in facts
        assert "nav" in facts
        assert "holdings" in facts
        assert "manager" in facts
        assert "allocation" in facts

        # Master has name
        assert facts["master"]["基金简称"] == "易方达中小盘混合"

        # Coverage is a dict
        assert isinstance(result["coverage"], dict)
        assert result["categories_total"] == 8

        # Manager has changes sub-field (COL-161)
        assert isinstance(facts["manager"], dict)
        assert "current" in facts["manager"]
        assert "changes" in facts["manager"]
        assert facts["manager"]["changes"][0]["change_type"] == "appoint"

        # fees has no fee fields in mock detail → missing
        assert result["coverage"]["fees"] in ("missing", "complete")
        # peer needs get_fund_ranking which is not mocked → error or missing
        assert "peer" in result["coverage"]

    def test_handles_sub_method_failure(self, mock_cache):
        """When a sub-method fails, fund fact pack returns partial data."""
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter

        adapter = AkshareAdapter(mock_cache)

        with patch.object(adapter, "get_fund_detail", new_callable=AsyncMock, side_effect=Exception("API error")), \
             patch.object(adapter, "get_fund_nav", new_callable=AsyncMock) as m_nav, \
             patch.object(adapter, "get_fund_performance", new_callable=AsyncMock) as m_perf, \
             patch.object(adapter, "get_fund_valuation", new_callable=AsyncMock) as m_val, \
             patch.object(adapter, "get_fund_holdings", new_callable=AsyncMock) as m_hold, \
             patch.object(adapter, "get_fund_manager", new_callable=AsyncMock) as m_mgr, \
             patch.object(adapter, "get_fund_scale", new_callable=AsyncMock) as m_scale, \
             patch.object(adapter, "get_fund_manager_changes", new_callable=AsyncMock) as m_mc:

            m_nav.return_value = {"data": []}
            m_perf.return_value = {"fund_code": "110011"}
            m_val.return_value = {}
            m_hold.return_value = {"data": [], "total": 0}
            m_mgr.return_value = {"data": []}
            m_scale.return_value = {"基金家数": 10000}
            m_mc.return_value = {"changes": [], "total": 0}

            result = _run(adapter.get_fund_fact_pack(fund_code="110011"))

        # Should still succeed with partial data
        assert "facts" in result
        # master should have error in coverage
        assert "error" in result["coverage"].get("master", "")
        # fees may be in missing_fields since detail failed
        assert "fees" in result["missing_fields"]
        # peer also likely missing (no master data → no fund type)
        assert "peer" in result["missing_fields"]


class TestFundFactPackMCPTool:
    """Verify fund fact pack MCP tool produces unified contract."""

    def test_tool_contract_structure(self, mock_cache):
        from src.server.mcp.tools.fact_pack_tools import register_fact_pack_tools
        from src.server.core.dependencies import Container

        mock_pack = {
            "source": "akshare",
            "entity": {"fund_code": "110011", "type": "fund"},
            "facts": {
                "master": {"基金简称": "易方达中小盘混合", "基金类型": "混合型"},
                "nav": {"nav_history": [{"date": "2025-01-01", "nav": 3.5}]},
                "holdings": {"data": [{"股票代码": "600519"}], "total": 10},
                "manager": [{"姓名": "张坤"}],
                "scale": {"基金家数": 10000},
                "allocation": [{"type": "股票", "ratio": "85%"}],
            },
            "source_trace": {"nav": {"provider": "akshare"}},
            "coverage": {
                "master": "complete",
                "nav": "complete",
                "holdings": "complete",
                "manager": "complete",
                "scale": "partial",
                "allocation": "complete",
                "fees": "missing",
                "peer": "missing",
            },
            "missing_fields": ["fees", "peer"],
            "categories_fetched": 6,
            "categories_total": 8,
            "elapsed_seconds": 0.8,
        }

        mock_gw = MagicMock()
        mock_gw.get_fund_fact_pack = AsyncMock(return_value=mock_pack)

        with patch.object(Container, "market_gateway", return_value=mock_gw):
            captured = {}

            class MockMCP:
                def tool(self, **kwargs):
                    def decorator(fn):
                        key = frozenset(kwargs.get("tags", set()))
                        captured[key] = fn
                        return fn
                    return decorator

            register_fact_pack_tools(MockMCP())

            # Find the fund fact pack tool (tagged with "fund")
            tool_fn = None
            for key, fn in captured.items():
                if "fund" in key:
                    tool_fn = fn
                    break
            assert tool_fn is not None, "Fund fact pack tool not registered"

            result = _run(tool_fn(fund_code="110011"))

        # Verify unified contract
        assert "summary" in result
        assert "artifact" in result
        content = result["artifact"]["content"]
        assert content["source"]["provider"] == "akshare"
        assert content["data"]["entity"]["fund_code"] == "110011"
        assert "markdown" in content
        assert "易方达" in result["summary"]


# =====================================================================
# Market Fact Pack Tests (COL-152)
# =====================================================================


class TestMarketFactPackAdapter:
    """Verify get_market_fact_pack adapter method."""

    def test_returns_correct_structure(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter

        adapter = AkshareAdapter(mock_cache)

        with patch.object(adapter, "_get_valuation_raw", new_callable=AsyncMock) as m_val, \
             patch.object(adapter, "calculate_technical_indicators", new_callable=AsyncMock) as m_tech, \
             patch.object(adapter, "get_stock_factors", new_callable=AsyncMock) as m_fac, \
             patch.object(adapter, "get_money_flow", new_callable=AsyncMock) as m_flow, \
             patch.object(adapter, "get_market_breadth", new_callable=AsyncMock) as m_br, \
             patch.object(adapter, "get_sector_trend", new_callable=AsyncMock) as m_sec, \
             patch.object(adapter, "get_futures_basis", new_callable=AsyncMock) as m_basis, \
             patch.object(adapter, "get_relative_strength", new_callable=AsyncMock) as m_rs, \
             patch.object(adapter, "get_north_bound_flow", new_callable=AsyncMock) as m_nb, \
             patch.object(adapter, "get_margin_trading", new_callable=AsyncMock) as m_mg:

            m_val.return_value = {"pe": 30.5, "pb": 10.2}
            m_tech.return_value = {"MA": [{"date": "2025-01-01", "ma5": 100}], "RSI": [{"date": "2025-01-01", "rsi": 55}]}
            m_fac.return_value = {"factors": {"momentum_1m": 0.05}, "symbol": "600519"}
            m_flow.return_value = {"net_inflow": 1e8, "data": []}
            m_br.return_value = {"up_count": 2000, "down_count": 1500, "advance_decline_ratio": 1.33}
            m_sec.return_value = {"sector": "白酒", "trend": "up"}
            m_basis.return_value = {"basis": -10.5, "index_code": "IF0"}
            m_rs.return_value = {"rs_pct": 0.03, "benchmark": "000300"}
            m_nb.return_value = {"data": [{"date": "2025-01-01", "north_net_inflow": 50e8}], "source": "akshare"}
            m_mg.return_value = {"data": [{"融资余额": 100e8}], "summary": {"latest_margin_balance": 100e8, "latest_short_balance": 10e8}, "exchange": "SSE", "source": "akshare"}

            result = _run(adapter.get_market_fact_pack(symbol="600519"))

        # Top-level structure
        assert "entity" in result
        assert "facts" in result
        assert "source_trace" in result
        assert "coverage" in result
        assert "missing_fields" in result
        assert "categories_fetched" in result
        assert "categories_total" in result

        # Entity
        assert result["entity"]["symbol"] == "600519"
        assert result["entity"]["type"] == "market"

        # Facts
        facts = result["facts"]
        assert "master" in facts
        assert "snapshot" in facts
        assert "kline" in facts
        assert "money_flow" in facts
        assert "breadth" in facts
        assert "index" in facts
        assert "derivative" in facts
        assert "relative" in facts
        assert "north_bound" in facts
        assert "margin" in facts

        # All 10 categories should be fetched
        assert result["categories_fetched"] == 10
        assert result["categories_total"] == 10

    def test_handles_sub_method_failure(self, mock_cache):
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter

        adapter = AkshareAdapter(mock_cache)

        with patch.object(adapter, "_get_valuation_raw", new_callable=AsyncMock, side_effect=Exception("API error")), \
             patch.object(adapter, "calculate_technical_indicators", new_callable=AsyncMock) as m_tech, \
             patch.object(adapter, "get_stock_factors", new_callable=AsyncMock) as m_fac, \
             patch.object(adapter, "get_money_flow", new_callable=AsyncMock) as m_flow, \
             patch.object(adapter, "get_market_breadth", new_callable=AsyncMock) as m_br, \
             patch.object(adapter, "get_sector_trend", new_callable=AsyncMock) as m_sec, \
             patch.object(adapter, "get_futures_basis", new_callable=AsyncMock) as m_basis, \
             patch.object(adapter, "get_relative_strength", new_callable=AsyncMock) as m_rs:

            m_tech.return_value = {"MA": []}
            m_fac.return_value = {"factors": {}, "symbol": "600519"}
            m_flow.return_value = {"error": "no data"}
            m_br.return_value = {"up_count": 100}
            m_sec.return_value = {"sector": "白酒"}
            m_basis.return_value = {"basis": -10}
            m_rs.return_value = {"rs_pct": 0.01}

            result = _run(adapter.get_market_fact_pack(symbol="600519"))

        # Should still succeed with partial data
        assert "facts" in result
        assert "error" in result["coverage"].get("master", "")
        assert result["categories_fetched"] < 8


class TestMarketFactPackMCPTool:
    """Verify market fact pack MCP tool produces unified contract."""

    def test_tool_contract_structure(self, mock_cache):
        from src.server.mcp.tools.fact_pack_tools import register_fact_pack_tools
        from src.server.core.dependencies import Container

        mock_pack = {
            "source": "akshare",
            "entity": {"symbol": "600519", "type": "market"},
            "facts": {
                "master": {"pe": 30.5, "pb": 10.2},
                "snapshot": {"MA": [{"ma5": 100}], "RSI": [{"rsi": 55}]},
                "kline": {"factors": {"momentum_1m": 0.05}},
                "money_flow": {"net_inflow": 1e8},
                "breadth": {"up_count": 2000, "down_count": 1500},
                "index": {"sector": "白酒"},
                "derivative": {"basis": -10.5},
                "relative": {"rs_pct": 0.03},
            },
            "source_trace": {"master": {"provider": "akshare"}},
            "coverage": {
                "master": "complete", "snapshot": "complete",
                "kline": "complete", "money_flow": "complete",
                "breadth": "complete", "index": "partial",
                "derivative": "partial", "relative": "complete",
            },
            "missing_fields": [],
            "categories_fetched": 8,
            "categories_total": 8,
            "elapsed_seconds": 0.5,
        }

        mock_gw = MagicMock()
        mock_gw.get_market_fact_pack = AsyncMock(return_value=mock_pack)

        with patch.object(Container, "market_gateway", return_value=mock_gw):
            captured = {}

            class MockMCP:
                def tool(self, **kwargs):
                    def decorator(fn):
                        key = frozenset(kwargs.get("tags", set()))
                        captured[key] = fn
                        return fn
                    return decorator

            register_fact_pack_tools(MockMCP())

            # Find the market fact pack tool (tagged with "market")
            tool_fn = None
            for key, fn in captured.items():
                if "market" in key:
                    tool_fn = fn
                    break
            assert tool_fn is not None, "Market fact pack tool not registered"

            result = _run(tool_fn(symbol="600519"))

        # Verify unified contract
        assert "summary" in result
        assert "artifact" in result
        content = result["artifact"]["content"]
        assert content["source"]["provider"] == "akshare"
        assert content["data"]["entity"]["symbol"] == "600519"
        assert "markdown" in content
        assert "600519" in result["summary"]


# =====================================================================
# fact_markdown Contract Tests (COL-181)
# =====================================================================


class TestFactMarkdownContract:
    """Verify fact_markdown is part of the unified fact-pack contract."""

    def test_stock_adapter_includes_fact_markdown(self, mock_cache):
        """Adapter get_stock_fact_pack should return fact_markdown field."""
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter

        adapter = AkshareAdapter(mock_cache)

        with patch.object(adapter, "get_asset_info", new_callable=AsyncMock) as m_info, \
             patch.object(adapter, "get_financials", new_callable=AsyncMock) as m_fin, \
             patch.object(adapter, "_get_valuation_raw", new_callable=AsyncMock) as m_val, \
             patch.object(adapter, "get_money_flow", new_callable=AsyncMock) as m_mf, \
             patch.object(adapter, "get_stock_top10_shareholders", new_callable=AsyncMock) as m_top10, \
             patch.object(adapter, "get_stock_shareholder_changes", new_callable=AsyncMock) as m_chg, \
             patch.object(adapter, "get_dividend_info", new_callable=AsyncMock) as m_div, \
             patch.object(adapter, "get_repurchase_info", new_callable=AsyncMock) as m_rep, \
             patch.object(adapter, "get_restricted_release", new_callable=AsyncMock) as m_rst, \
             patch.object(adapter, "get_mainbz_info", new_callable=AsyncMock) as m_biz:

            m_info.return_value = _mock_asset_info("贵州茅台", "600519")
            m_fin.return_value = {"revenue": 100}
            m_val.return_value = {"pe": 30.5}
            m_mf.return_value = {"net_inflow": 1e8}
            m_top10.return_value = {"data": [{"holder_name": "A", "hold_qty": 100}]}
            m_chg.return_value = {"data": [{"total": 150000}]}
            m_div.return_value = {"dividend_yield": 0.02}
            m_rep.return_value = {"data": [{"symbol": "600519", "progress": "实施中", "amount": 10e8}]}
            m_rst.return_value = {"data": [{"symbol": "600519", "release_date": "2025-06-01", "release_volume": 1000}]}
            m_biz.return_value = [{"biz": "白酒"}]

            result = _run(adapter.get_stock_fact_pack(symbol="600519"))

        # COL-181: fact_markdown must be a contract field
        assert "fact_markdown" in result, "fact_markdown missing from stock fact pack contract"
        assert isinstance(result["fact_markdown"], str)
        assert len(result["fact_markdown"]) > 0
        # Markdown should contain the entity name
        assert "贵州茅台" in result["fact_markdown"] or "600519" in result["fact_markdown"]

    def test_mcp_tool_uses_adapter_fact_markdown(self, mock_cache):
        """MCP tool should use adapter's fact_markdown instead of rebuilding."""
        from src.server.mcp.tools.fact_pack_tools import register_fact_pack_tools
        from src.server.core.dependencies import Container

        mock_pack = {
            "source": "akshare",
            "entity": {"symbol": "600519", "type": "stock"},
            "facts": {
                "security_master": {"code": "600519", "name": "贵州茅台"},
                "financial": {"revenue": 100},
                "market": {"pe": 30.5},
            },
            "source_trace": {},
            "coverage": {
                "security_master": "complete",
                "financial": "complete",
                "market": "complete",
            },
            "missing_fields": [],
            "categories_fetched": 3,
            "categories_total": 8,
            "fact_markdown": "# 股票事实包: 贵州茅台(600519)\n\n## 证券主数据\n\n- **name**: 贵州茅台\n",
        }

        mock_gw = MagicMock()
        mock_gw.get_stock_fact_pack = AsyncMock(return_value=mock_pack)

        with patch.object(Container, "market_gateway", return_value=mock_gw):
            captured = {}

            class MockMCP:
                def tool(self, **kwargs):
                    def decorator(fn):
                        key = frozenset(kwargs.get("tags", set()))
                        captured[key] = fn
                        return fn
                    return decorator

            register_fact_pack_tools(MockMCP())
            tool_fn = list(captured.values())[0]
            result = _run(tool_fn(symbol="600519"))

        content = result["artifact"]["content"]
        md = content.get("markdown", "")
        # The adapter's fact_markdown content should be preserved
        assert "贵州茅台" in md
        assert "证券主数据" in md

    def test_all_contract_fields_present(self, mock_cache):
        """Verify all 6 unified contract fields are in stock fact pack."""
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter

        adapter = AkshareAdapter(mock_cache)

        with patch.object(adapter, "get_asset_info", new_callable=AsyncMock) as m_info, \
             patch.object(adapter, "get_financials", new_callable=AsyncMock) as m_fin, \
             patch.object(adapter, "_get_valuation_raw", new_callable=AsyncMock) as m_val, \
             patch.object(adapter, "get_money_flow", new_callable=AsyncMock) as m_mf, \
             patch.object(adapter, "get_stock_top10_shareholders", new_callable=AsyncMock) as m_top10, \
             patch.object(adapter, "get_stock_shareholder_changes", new_callable=AsyncMock) as m_chg, \
             patch.object(adapter, "get_dividend_info", new_callable=AsyncMock) as m_div, \
             patch.object(adapter, "get_repurchase_info", new_callable=AsyncMock) as m_rep, \
             patch.object(adapter, "get_restricted_release", new_callable=AsyncMock) as m_rst, \
             patch.object(adapter, "get_mainbz_info", new_callable=AsyncMock) as m_biz:

            for m in [m_info, m_fin, m_val, m_mf, m_top10, m_chg, m_div, m_rep, m_rst, m_biz]:
                m.return_value = {}
            m_info.return_value = _mock_asset_info("测试", "000001")

            result = _run(adapter.get_stock_fact_pack(symbol="000001"))

        # COL-181: the 6 contract fields
        required_fields = [
            "entity", "facts", "fact_markdown",
            "source_trace", "coverage", "missing_fields",
        ]
        for field in required_fields:
            assert field in result, f"Contract field '{field}' missing from fact pack"


# =====================================================================
# fact_markdown Contract Tests for all entity types (COL-182)
# =====================================================================


class TestAllFactPackMarkdownContracts:
    """Verify every fact-pack entity type returns fact_markdown from adapter."""

    def _make_mock_pack(self, entity_type: str, entity: dict, facts: dict) -> dict:
        """Build a minimal mock fact pack with fact_markdown."""
        return {
            "source": "akshare",
            "entity": entity,
            "facts": facts,
            "source_trace": {},
            "coverage": {},
            "missing_fields": [],
            "categories_fetched": len(facts),
            "categories_total": len(facts),
            "elapsed_seconds": 0.1,
            "fact_markdown": f"# {entity_type} test markdown with real content",
        }

    def test_fund_mcp_uses_adapter_markdown(self, mock_cache):
        """Fund fact pack MCP tool uses adapter's fact_markdown."""
        from src.server.mcp.tools.fact_pack_tools import register_fact_pack_tools
        from src.server.core.dependencies import Container

        mock_pack = self._make_mock_pack(
            "基金",
            {"fund_code": "110011", "type": "fund"},
            {"master": {"基金简称": "测试基金"}},
        )
        mock_gw = MagicMock()
        mock_gw.get_fund_fact_pack = AsyncMock(return_value=mock_pack)

        with patch.object(Container, "market_gateway", return_value=mock_gw):
            captured = {}
            class MockMCP:
                def tool(self, **kwargs):
                    def decorator(fn):
                        captured[frozenset(kwargs.get("tags", set()))] = fn
                        return fn
                    return decorator
            register_fact_pack_tools(MockMCP())

            tool_fn = None
            for key, fn in captured.items():
                if "fund" in key:
                    tool_fn = fn
                    break
            assert tool_fn is not None
            result = _run(tool_fn(fund_code="110011"))

        md = result["artifact"]["content"].get("markdown", "")
        assert "基金 test markdown with real content" in md

    def test_market_mcp_uses_adapter_markdown(self, mock_cache):
        """Market fact pack MCP tool uses adapter's fact_markdown."""
        from src.server.mcp.tools.fact_pack_tools import register_fact_pack_tools
        from src.server.core.dependencies import Container

        mock_pack = self._make_mock_pack(
            "行情",
            {"symbol": "600519", "type": "market"},
            {"master": {"pe": 30.5}},
        )
        mock_gw = MagicMock()
        mock_gw.get_market_fact_pack = AsyncMock(return_value=mock_pack)

        with patch.object(Container, "market_gateway", return_value=mock_gw):
            captured = {}
            class MockMCP:
                def tool(self, **kwargs):
                    def decorator(fn):
                        captured[frozenset(kwargs.get("tags", set()))] = fn
                        return fn
                    return decorator
            register_fact_pack_tools(MockMCP())

            tool_fn = None
            for key, fn in captured.items():
                if "market" in key and "fact-pack" in key:
                    tool_fn = fn
                    break
            assert tool_fn is not None
            result = _run(tool_fn(symbol="600519"))

        md = result["artifact"]["content"].get("markdown", "")
        assert "行情 test markdown with real content" in md

    def test_etf_mcp_uses_adapter_markdown(self, mock_cache):
        """ETF fact pack MCP tool uses adapter's fact_markdown."""
        from src.server.mcp.tools.fact_pack_tools import register_fact_pack_tools
        from src.server.core.dependencies import Container

        mock_pack = self._make_mock_pack(
            "ETF",
            {"symbol": "510300", "type": "etf"},
            {"master": {"名称": "沪深300ETF"}},
        )
        mock_gw = MagicMock()
        mock_gw.get_etf_fact_pack = AsyncMock(return_value=mock_pack)

        with patch.object(Container, "market_gateway", return_value=mock_gw):
            captured = {}
            class MockMCP:
                def tool(self, **kwargs):
                    def decorator(fn):
                        captured[frozenset(kwargs.get("tags", set()))] = fn
                        return fn
                    return decorator
            register_fact_pack_tools(MockMCP())

            tool_fn = None
            for key, fn in captured.items():
                if "etf" in key:
                    tool_fn = fn
                    break
            assert tool_fn is not None
            result = _run(tool_fn(symbol="510300"))

        md = result["artifact"]["content"].get("markdown", "")
        assert "ETF test markdown with real content" in md

    def test_index_mcp_uses_adapter_markdown(self, mock_cache):
        """Index fact pack MCP tool uses adapter's fact_markdown."""
        from src.server.mcp.tools.fact_pack_tools import register_fact_pack_tools
        from src.server.core.dependencies import Container

        mock_pack = self._make_mock_pack(
            "指数",
            {"symbol": "000300", "type": "index"},
            {"master": {"index_name": "沪深300"}},
        )
        mock_gw = MagicMock()
        mock_gw.get_index_fact_pack = AsyncMock(return_value=mock_pack)

        with patch.object(Container, "market_gateway", return_value=mock_gw):
            captured = {}
            class MockMCP:
                def tool(self, **kwargs):
                    def decorator(fn):
                        captured[frozenset(kwargs.get("tags", set()))] = fn
                        return fn
                    return decorator
            register_fact_pack_tools(MockMCP())

            tool_fn = None
            for key, fn in captured.items():
                if "index" in key:
                    tool_fn = fn
                    break
            assert tool_fn is not None
            result = _run(tool_fn(symbol="000300"))

        md = result["artifact"]["content"].get("markdown", "")
        assert "指数 test markdown with real content" in md

    def test_us_stock_mcp_uses_adapter_markdown(self, mock_cache):
        """US stock fact pack MCP tool uses adapter's fact_markdown."""
        from src.server.mcp.tools.fact_pack_tools import register_fact_pack_tools
        from src.server.core.dependencies import Container

        mock_pack = self._make_mock_pack(
            "美股",
            {"symbol": "AAPL", "type": "us_stock"},
            {"profile": {"company_name": "Apple Inc."}},
        )
        mock_gw = MagicMock()
        mock_gw.get_us_stock_fact_pack = AsyncMock(return_value=mock_pack)

        with patch.object(Container, "market_gateway", return_value=mock_gw):
            captured = {}
            class MockMCP:
                def tool(self, **kwargs):
                    def decorator(fn):
                        captured[frozenset(kwargs.get("tags", set()))] = fn
                        return fn
                    return decorator
            register_fact_pack_tools(MockMCP())

            tool_fn = None
            for key, fn in captured.items():
                if "us-fundamental" in key:
                    tool_fn = fn
                    break
            assert tool_fn is not None
            result = _run(tool_fn(ticker="AAPL"))

        md = result["artifact"]["content"].get("markdown", "")
        assert "美股 test markdown with real content" in md


# =====================================================================
# COL-211: Extractor Robustness Tests
# =====================================================================


class TestExtractorRobustness:
    """Verify extractors handle various akshare field name formats."""

    def test_fuzzy_get_exact_match(self):
        from src.server.api.routes.fact_pack import _fuzzy_get
        d = {"净资产收益率(%)": 15.3}
        assert _fuzzy_get(d, "净资产收益率(%)", "roe") == 15.3

    def test_fuzzy_get_fallback_match(self):
        from src.server.api.routes.fact_pack import _fuzzy_get
        d = {"roe": 12.5}
        assert _fuzzy_get(d, "净资产收益率(%)", "roe") == 12.5

    def test_fuzzy_get_contains_match(self):
        from src.server.api.routes.fact_pack import _fuzzy_get
        d = {"加权净资产收益率(%)": 18.2}
        # Exact key doesn't match, but "净资产收益率" is contained in "加权净资产收益率"
        assert _fuzzy_get(d, "净资产收益率(%)", "roe") == 18.2

    def test_fuzzy_get_no_match(self):
        from src.server.api.routes.fact_pack import _fuzzy_get
        d = {"other_field": 42}
        assert _fuzzy_get(d, "净资产收益率(%)", "roe") is None

    def test_extract_profitability_akshare_columns(self):
        """Test with actual akshare column names from stock_financial_analysis_indicator."""
        from src.server.api.routes.fact_pack import _extract_profitability
        facts = {
            "financial": {
                "financial_indicators": [
                    {"日期": "2023-12-31", "毛利率(%)": 91.5, "净利率(%)": 49.8, "净资产收益率(%)": 30.2},
                ],
            },
        }
        result = _extract_profitability(facts)
        assert result["roe"] == 30.2
        assert result["net_margin"] == 49.8
        assert result["gross_margin"] == 91.5

    def test_extract_profitability_english_columns(self):
        from src.server.api.routes.fact_pack import _extract_profitability
        facts = {
            "financial": {
                "financial_indicators": [
                    {"roe": 25.0, "net_margin": 45.0, "gross_margin": 90.0},
                ],
            },
        }
        result = _extract_profitability(facts)
        assert result["roe"] == 25.0
        assert result["net_margin"] == 45.0
        assert result["gross_margin"] == 90.0

    def test_extract_profitability_yoy_from_income(self):
        """YoY calculated from income_statement when indicators lack YoY."""
        from src.server.api.routes.fact_pack import _extract_profitability
        facts = {
            "financial": {
                "financial_indicators": [{"roe": 20.0}],
                "income_statement": [
                    {"报告期": "20241231", "营业收入": 1500000, "净利润": 750000},
                    {"报告期": "20231231", "营业收入": 1200000, "净利润": 600000},
                    {"报告期": "20221231", "营业收入": 1000000, "净利润": 500000},
                ],
            },
        }
        result = _extract_profitability(facts)
        assert result["revenue_yoy"] == 25.0  # (1500000-1200000)/1200000*100
        assert result["profit_yoy"] == 25.0   # (750000-600000)/600000*100

    def test_extract_profitability_empty_financial(self):
        from src.server.api.routes.fact_pack import _extract_profitability
        result = _extract_profitability({"financial": {}})
        assert result["roe"] is None
        assert result["net_margin"] is None
        assert result["revenue_yoy"] is None

    def test_extract_profitability_yoy_hyphenated_dates(self):
        """YoY must work with hyphenated dates like '2024-12-31' from akshare."""
        from src.server.api.routes.fact_pack import _extract_profitability
        facts = {
            "financial": {
                "financial_indicators": [{"roe": 20.0}],
                "income_statement": [
                    {"报告期": "2024-12-31", "营业收入": 1500000, "净利润": 750000},
                    {"报告期": "2023-12-31", "营业收入": 1200000, "净利润": 600000},
                ],
            },
        }
        result = _extract_profitability(facts)
        assert result["revenue_yoy"] == 25.0
        assert result["profit_yoy"] == 25.0

    def test_extract_valuation_akshare_fields(self):
        """Test with fields from stock_a_indicator_lg."""
        from src.server.api.routes.fact_pack import _extract_valuation
        facts = {
            "market": {
                "valuation": {
                    "pe": 35.2,
                    "pe_ttm": 33.8,
                    "pb": 11.5,
                    "ps_ttm": 15.0,
                    "dv_ratio": 1.8,
                },
            },
        }
        result = _extract_valuation(facts)
        assert result["pe_ttm"] == 33.8
        assert result["pb"] == 11.5
        assert result["ps_ttm"] == 15.0
        assert result["dv_ratio"] == 1.8

    def test_extract_valuation_flat_market(self):
        """market dict is the valuation data (no nested valuation key)."""
        from src.server.api.routes.fact_pack import _extract_valuation
        facts = {
            "market": {
                "pe": 30.0,
                "pb": 10.0,
            },
        }
        result = _extract_valuation(facts)
        assert result["pe_ttm"] == 30.0
        assert result["pb"] == 10.0

    def test_extract_valuation_empty(self):
        from src.server.api.routes.fact_pack import _extract_valuation
        result = _extract_valuation({"market": {}})
        assert result["pe_ttm"] is None
        assert result["pb"] is None

    def test_extract_financial_akshare_fields(self):
        from src.server.api.routes.fact_pack import _extract_financial
        facts = {
            "financial": {
                "balance_sheet": [
                    {"资产总计": 2000000, "负债合计": 800000},
                ],
                "cash_flow": [
                    {"经营活动产生的现金流量净额": 500000},
                ],
            },
        }
        result = _extract_financial(facts)
        assert result["total_assets"] == 2000000
        assert result["total_liabilities"] == 800000
        assert result["debt_ratio"] == 40.0
        assert result["operating_cashflow"] == 500000

    def test_extract_financial_debt_ratio_calc(self):
        from src.server.api.routes.fact_pack import _extract_financial
        facts = {
            "financial": {
                "balance_sheet": [{"资产总计": 1000000, "负债合计": 650000}],
                "cash_flow": [{}],
            },
        }
        result = _extract_financial(facts)
        assert result["debt_ratio"] == 65.0

    def test_extract_financial_empty(self):
        from src.server.api.routes.fact_pack import _extract_financial
        result = _extract_financial({"financial": {}})
        assert result["total_assets"] is None
        assert result["debt_ratio"] is None

    def test_extract_shareholder_various_keys(self):
        from src.server.api.routes.fact_pack import _extract_shareholder
        facts = {
            "governance": {
                "top10_shareholders": [
                    {"holder_name": "中国茅台", "hold_ratio": 60, "change": "+100"},
                    {"股东名称": "Other", "持股比例": 5.0, "增减": "-50"},
                ],
            },
        }
        result = _extract_shareholder(facts)
        assert len(result["top10_shareholders"]) == 2
        assert result["top10_shareholders"][0]["name"] == "中国茅台"
        assert result["top10_shareholders"][0]["ratio"] == 60.0

    def test_extract_dividend_various_keys(self):
        from src.server.api.routes.fact_pack import _extract_dividend
        facts = {
            "events": {
                "dividends": {
                    "data": [
                        {"dividend_yield": 0.025, "consecutive_years": 10, "payout_ratio": 0.52},
                    ],
                },
            },
        }
        result = _extract_dividend(facts)
        assert result["dividend_yield"] == 0.025
        assert result["consecutive_years"] == 10.0
        assert result["payout_ratio"] == 0.52

    def test_extract_dividend_chinese_keys(self):
        from src.server.api.routes.fact_pack import _extract_dividend
        facts = {
            "events": {
                "dividends": {"股息率": 2.5, "连续分红年数": 8, "股利支付率": 50.0},
            },
        }
        result = _extract_dividend(facts)
        assert result["dividend_yield"] == 2.5
        assert result["consecutive_years"] == 8.0

    def test_extract_dividend_non_dict(self):
        from src.server.api.routes.fact_pack import _extract_dividend
        result = _extract_dividend({"events": {"dividends": "not a dict"}})
        assert result["dividend_yield"] is None

    def test_extract_revenue_breakdown_product_region(self):
        from src.server.api.routes.fact_pack import _extract_revenue_breakdown
        facts = {
            "business_structure": {
                "rows": [
                    {"分类类型": "按产品分类", "主营构成": "茅台酒", "主营收入占比": 85.0, "主营收入": 1000000},
                    {"分类类型": "按地区分类", "主营构成": "国内", "主营收入占比": 90.0, "主营收入": 1050000},
                    {"分类类型": "按产品分类", "主营构成": "系列酒", "主营收入占比": 10.0, "主营收入": 120000},
                ],
            },
        }
        result = _extract_revenue_breakdown(facts)
        assert len(result["by_product"]) == 2
        assert len(result["by_region"]) == 1
        assert result["by_product"][0]["name"] == "茅台酒"
