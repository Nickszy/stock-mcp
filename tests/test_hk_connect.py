# tests/test_hk_connect.py
"""Tests for HK Connect MCP tools.

Covers:
  - Registry: hk-connect tool group
  - MCP tools: registration
  - REST routes: hk-connect endpoints

Run: uv run pytest tests/test_hk_connect.py -v
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


class TestHKConnectRegistry:
    def test_hk_connect_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "hk-connect"]
        assert len(groups) == 1
        assert groups[0].count == 4
        assert groups[0].enabled is True

    def test_total_tool_count_increased(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total >= 163, f"Expected >= 163, got {total}"


class TestHKConnectToolRegistration:
    def test_register_hk_connect_tools_succeeds(self):
        from src.server.mcp.tools.hk_connect_tools import register_hk_connect_tools
        from fastmcp import FastMCP
        mcp = FastMCP("test")
        register_hk_connect_tools(mcp)


class TestHKConnectRoutes:
    def test_router_has_correct_prefix(self):
        from src.server.api.routes.hk_connect import router
        assert router.prefix == "/api/v1/hk-connect"

    def test_router_has_routes(self):
        from src.server.api.routes.hk_connect import router
        route_paths = [r.path for r in router.routes]
        expected_suffixes = ["/components", "/fund-flow", "/hold-stock", "/overview"]
        for suffix in expected_suffixes:
            full = f"/api/v1/hk-connect{suffix}"
            assert full in route_paths, f"Missing route {full}"
