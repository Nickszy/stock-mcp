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

            result = _run(adapter.get_stock_fact_pack(symbol="600519"))

        # Should still succeed with partial data
        assert "facts" in result
        # financial coverage should show error
        assert result["coverage"].get("financial", "").startswith("error")
        # company_master and peers are always in missing_fields (not_implemented)
        assert "company_master" in result["missing_fields"]
        assert "peers" in result["missing_fields"]

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
        # 110 (COL-147) + 1 (fact-pack) = 111
        assert total == 111, f"Expected 111, got {total}"

    def test_fact_pack_group_present(self):
        from src.server.mcp.registry import TOOL_GROUPS
        names = {g.name for g in TOOL_GROUPS}
        assert "fact-pack" in names

    def test_fact_pack_group_count(self):
        from src.server.mcp.registry import TOOL_GROUPS
        fp = [g for g in TOOL_GROUPS if g.name == "fact-pack"]
        assert len(fp) == 1
        assert fp[0].count == 1
        assert fp[0].enabled is True
