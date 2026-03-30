# tests/test_sentiment.py
"""Tests for QVIX / sentiment MCP tools.

Covers:
  - Registry: sentiment tool group
  - MCP tools: registration
  - REST routes: sentiment endpoints

Run: uv run pytest tests/test_sentiment.py -v
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")


class TestSentimentRegistry:
    def test_sentiment_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "sentiment"]
        assert len(groups) == 1
        assert groups[0].count == 5
        assert groups[0].enabled is True

    def test_total_tool_count_increased(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total >= 159, f"Expected >= 159, got {total}"


class TestSentimentToolRegistration:
    def test_register_sentiment_tools_succeeds(self):
        from src.server.mcp.tools.sentiment_tools import register_sentiment_tools
        from fastmcp import FastMCP
        mcp = FastMCP("test")
        register_sentiment_tools(mcp)


class TestSentimentRoutes:
    def test_router_has_correct_prefix(self):
        from src.server.api.routes.sentiment import router
        assert router.prefix == "/api/v1/sentiment"

    def test_router_has_routes(self):
        from src.server.api.routes.sentiment import router
        route_paths = [r.path for r in router.routes]
        expected_suffixes = ["/qvix/50etf", "/qvix/300etf", "/qvix/1000index", "/qvix/cyb", "/overview"]
        for suffix in expected_suffixes:
            full = f"/api/v1/sentiment{suffix}"
            assert full in route_paths, f"Missing route {full}"
