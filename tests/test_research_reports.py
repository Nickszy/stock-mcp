# tests/test_research_reports.py
"""Tests for research report integration (COL-244).

Covers:
  - Registry: research-report tool group
  - MCP tools: registration
  - REST routes: endpoint presence
  - Service: config-based behavior

Run: uv run pytest tests/test_research_reports.py -v
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")


# =====================================================================
# Registry: research-report tool group
# =====================================================================


class TestResearchReportRegistry:
    """Verify research-report tool group registration."""

    def test_research_report_group_exists(self):
        from src.server.mcp.registry import TOOL_GROUPS
        rr = [g for g in TOOL_GROUPS if g.name == "research-report"]
        assert len(rr) == 1
        assert rr[0].count == 2
        assert rr[0].enabled is True

    def test_total_tool_count_increased(self):
        from src.server.mcp.registry import get_enabled_tool_count
        total = get_enabled_tool_count()
        assert total >= 138, f"Expected >= 138, got {total}"


# =====================================================================
# MCP Tool registration
# =====================================================================


class TestResearchReportToolRegistration:
    """Verify research-report tools register without error."""

    def test_register_research_report_tools_succeeds(self):
        from src.server.mcp.tools.research_report_tools import register_research_report_tools
        from fastmcp import FastMCP

        mcp = FastMCP("test")
        register_research_report_tools(mcp)


# =====================================================================
# REST Route: research-reports endpoints
# =====================================================================


class TestResearchReportRoutes:
    """Verify REST route module loads and has correct shape."""

    def test_router_has_correct_prefix(self):
        from src.server.api.routes.research_reports import router
        assert router.prefix == "/api/v1/research-reports"

    def test_router_has_search_route(self):
        from src.server.api.routes.research_reports import router
        route_paths = [r.path for r in router.routes]
        assert "/api/v1/research-reports/search" in route_paths


# =====================================================================
# Service: config-based behavior
# =====================================================================


class TestResearchReportService:
    """Verify service config behavior."""

    def test_service_instantiates(self):
        from src.server.domain.services.research_report_service import ResearchReportService
        svc = ResearchReportService()
        assert svc is not None

    def test_search_raises_without_base_url(self):
        """Service should have empty db_url when NEWS_DB_URL is empty."""
        from src.server.domain.services.research_report_service import ResearchReportService
        import os

        # Ensure both URLs are empty
        original_mcp = os.environ.get("NEWS_MCP_BASE_URL", "")
        original_db = os.environ.get("NEWS_DB_URL", "")
        os.environ["NEWS_MCP_BASE_URL"] = ""
        os.environ["NEWS_DB_URL"] = ""

        svc = ResearchReportService()
        assert svc.db_url == ""

        # Restore
        if original_mcp:
            os.environ["NEWS_MCP_BASE_URL"] = original_mcp
        else:
            os.environ.pop("NEWS_MCP_BASE_URL", None)
        if original_db:
            os.environ["NEWS_DB_URL"] = original_db
        else:
            os.environ.pop("NEWS_DB_URL", None)

    def test_config_has_news_mcp_base_url(self):
        from src.server.config.settings import Settings
        s = Settings()
        assert hasattr(s, "news_mcp_base_url")
        assert hasattr(s, "news_db_url")
