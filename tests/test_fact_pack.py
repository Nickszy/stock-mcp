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
            m_rep.return_value = None
            m_rst.return_value = None
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

        # categories_total is 8
        assert result["categories_total"] == 8

    def test_handles_sub_method_failure_gracefully(self, mock_cache):
        """When a sub-method fails, fact pack should still return partial data."""
        from src.server.domain.adapters.akshare_adapter import AkshareAdapter

        adapter = AkshareAdapter(mock_cache)

        with patch.object(adapter, "get_asset_info", new_callable=AsyncMock) as m_info, \
             patch.object(adapter, "get_financials", new_callable=AsyncMock, side_effect=Exception("API error")), \
             patch.object(adapter, "_get_valuation_raw", new_callable=AsyncMock) as m_val, \
             patch.object(adapter, "get_money_flow", new_callable=AsyncMock) as m_mf, \
             patch.object(adapter, "get_stock_top10_shareholders", new_callable=AsyncMock) as m_top10, \
             patch.object(adapter, "get_stock_shareholder_changes", new_callable=AsyncMock) as m_chg, \
             patch.object(adapter, "get_dividend_info", new_callable=AsyncMock) as m_div, \
             patch.object(adapter, "get_repurchase_info", new_callable=AsyncMock) as m_rep, \
             patch.object(adapter, "get_restricted_release", new_callable=AsyncMock) as m_rst, \
             patch.object(adapter, "get_mainbz_info", new_callable=AsyncMock) as m_biz:

            m_info.return_value = _mock_asset_info("贵州茅台", "600519")
            m_val.return_value = {"pe": 30.5}
            m_mf.return_value = {}
            m_top10.return_value = {"data": []}
            m_chg.return_value = {"data": []}
            m_div.return_value = {}
            m_rep.return_value = None
            m_rst.return_value = None
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
# Registry Tests
# =====================================================================


class TestFactPackRegistry:
    """Verify registry is consistent after COL-148."""

    def test_total_tool_count(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        # 110 + 1(stock) + 1(fund) + 1(market) = 113
        assert total == 113, f"Expected 113, got {total}"

    def test_fact_pack_group_present(self):
        from src.server.mcp.registry import TOOL_GROUPS
        names = {g.name for g in TOOL_GROUPS}
        assert "fact-pack" in names

    def test_fact_pack_group_count(self):
        from src.server.mcp.registry import TOOL_GROUPS
        fp = [g for g in TOOL_GROUPS if g.name == "fact-pack"]
        assert len(fp) == 1
        assert fp[0].count == 3  # stock + fund + market
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
             patch.object(adapter, "get_fund_scale", new_callable=AsyncMock) as m_scale:

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
             patch.object(adapter, "get_fund_scale", new_callable=AsyncMock) as m_scale:

            m_nav.return_value = {"data": []}
            m_perf.return_value = {"fund_code": "110011"}
            m_val.return_value = {}
            m_hold.return_value = {"data": [], "total": 0}
            m_mgr.return_value = {"data": []}
            m_scale.return_value = {"基金家数": 10000}

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
             patch.object(adapter, "get_relative_strength", new_callable=AsyncMock) as m_rs:

            m_val.return_value = {"pe": 30.5, "pb": 10.2}
            m_tech.return_value = {"MA": [{"date": "2025-01-01", "ma5": 100}], "RSI": [{"date": "2025-01-01", "rsi": 55}]}
            m_fac.return_value = {"factors": {"momentum_1m": 0.05}, "symbol": "600519"}
            m_flow.return_value = {"net_inflow": 1e8, "data": []}
            m_br.return_value = {"up_count": 2000, "down_count": 1500, "advance_decline_ratio": 1.33}
            m_sec.return_value = {"sector": "白酒", "trend": "up"}
            m_basis.return_value = {"basis": -10.5, "index_code": "IF0"}
            m_rs.return_value = {"rs_pct": 0.03, "benchmark": "000300"}

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

        # All 8 categories should be fetched
        assert result["categories_fetched"] == 8
        assert result["categories_total"] == 8

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
