# tests/test_hk_market.py
"""Tests for Hong Kong market MCP tools.

Covers:
  - Registry: hk-market tool group
  - MCP tools: registration
  - REST routes: hk endpoints

Run: uv run pytest tests/test_hk_market.py -v
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


class TestHKMarketRegistry:
    def test_hk_market_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "hk-market"]
        assert len(groups) == 1
        assert groups[0].count == 4
        assert groups[0].enabled is True

    def test_total_tool_count_increased(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total >= 159, f"Expected >= 159, got {total}"


class TestHKMarketToolRegistration:
    def test_register_hk_market_tools_succeeds(self):
        from src.server.mcp.tools.hk_market_tools import register_hk_market_tools
        from fastmcp import FastMCP
        mcp = FastMCP("test")
        register_hk_market_tools(mcp)


class TestHKMarketRoutes:
    def test_router_has_correct_prefix(self):
        from src.server.api.routes.hk_market import router
        assert router.prefix == "/api/v1/hk"

    def test_router_has_routes(self):
        from src.server.api.routes.hk_market import router
        route_paths = [r.path for r in router.routes]
        expected_suffixes = ["/spot", "/hot-rank", "/main-board", "/overview"]
        for suffix in expected_suffixes:
            full = f"/api/v1/hk{suffix}"
            assert full in route_paths, f"Missing route {full}"
