# tests/test_options.py
"""Tests for option market data MCP tools.

Covers:
  - Registry: option tool group
  - MCP tools: registration
  - REST routes: option endpoints

Run: uv run pytest tests/test_options.py -v
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


class TestOptionRegistry:
    """Verify option tool group registration."""

    def test_option_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        opt = [g for g in TOOL_GROUPS if g.name == "option"]
        assert len(opt) == 1
        assert opt[0].count == 3
        assert opt[0].enabled is True

    def test_total_tool_count_increased(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total >= 159, f"Expected >= 159, got {total}"


class TestOptionToolRegistration:
    """Verify option tools register without error."""

    def test_register_option_tools_succeeds(self):
        from src.server.mcp.tools.option_tools import register_option_tools
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_option_tools(mcp)


class TestOptionRoutes:
    """Verify REST route module loads and has correct shape."""

    def test_router_has_correct_prefix(self):
        from src.server.api.routes.options import router
        assert router.prefix == "/api/v1/options"

    def test_router_has_routes(self):
        from src.server.api.routes.options import router
        route_paths = [r.path for r in router.routes]
        expected_suffixes = ["/chain", "/greeks", "/price-history"]
        for suffix in expected_suffixes:
            full = f"/api/v1/options{suffix}"
            assert full in route_paths, f"Missing route {full}"
