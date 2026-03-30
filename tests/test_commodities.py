# tests/test_commodities.py
"""Tests for commodity asset MCP tools (COL-244).

Covers:
  - Registry: commodity tool group
  - MCP tools: registration
  - REST routes: commodity endpoints

Run: uv run pytest tests/test_commodities.py -v
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


class TestCommodityRegistry:
    """Verify commodity tool group registration."""

    def test_commodity_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        c = [g for g in TOOL_GROUPS if g.name == "commodity"]
        assert len(c) == 1
        assert c[0].count == 6
        assert c[0].enabled is True

    def test_total_tool_count_increased(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total >= 150, f"Expected >= 150, got {total}"


class TestCommodityToolRegistration:
    """Verify commodity tools register without error."""

    def test_register_commodity_tools_succeeds(self):
        from src.server.mcp.tools.commodity_tools import register_commodity_tools
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_commodity_tools(mcp)


class TestCommodityRoutes:
    """Verify REST route module loads and has correct shape."""

    def test_router_has_correct_prefix(self):
        from src.server.api.routes.commodities import router
        assert router.prefix == "/api/v1/commodities"

    def test_router_has_routes(self):
        from src.server.api.routes.commodities import router
        route_paths = [r.path for r in router.routes]
        expected_suffixes = ["/gold", "/silver", "/crude-oil", "/copper", "/industrial-metals", "/overview"]
        for suffix in expected_suffixes:
            full = f"/api/v1/commodities{suffix}"
            assert full in route_paths, f"Missing route {full}"
