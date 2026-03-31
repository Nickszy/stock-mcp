# tests/test_news_tools.py
"""Tests for MCP news tool group.

Verifies:
  - Tool registration count
  - Registry enabled state and count
  - Total tool count updated
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, ".")


class TestNewsToolRegistration:
    """Verify news tools are registered correctly."""

    def test_registers_three_tools(self):
        from src.server.mcp.tools.news_tools import register_news_tools

        mcp = MagicMock()
        registered = []

        def capture_tool(**kwargs):
            def decorator(fn):
                registered.append(fn.__name__)
                return fn
            return decorator

        mcp.tool = capture_tool
        register_news_tools(mcp)

        expected = ["get_stock_news", "get_latest_news", "get_us_news_sentiment"]
        for name in expected:
            assert name in registered, f"Missing tool: {name}"


class TestNewsRegistry:
    """Verify news group is registered and enabled."""

    def test_news_group_enabled(self):
        from src.server.mcp.registry import TOOL_GROUPS
        groups = [g for g in TOOL_GROUPS if g.name == "news"]
        assert len(groups) == 1, "news group must exist"
        assert groups[0].enabled is True
        assert groups[0].count == 3

    def test_total_tool_count_updated(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        # 180 (prior) + 2 (news was disabled with count=1, now enabled with count=3, net +2)
        assert total == 196, f"Expected 196, got {total}"
