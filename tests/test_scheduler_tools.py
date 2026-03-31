from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, ".")

from src.server.domain.scheduler.models import AnalysisRun, ScheduledAnalysisJob
from src.server.domain.watchlist.models import Watchlist


class TestWatchlistTools:
    @pytest.mark.asyncio
    async def test_register_watchlist_tools(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.watchlist_tools import register_watchlist_tools

        mcp = FastMCP("test")
        register_watchlist_tools(mcp)

        assert "create_watchlist" in mcp._tool_manager._tools
        assert "list_watchlists" in mcp._tool_manager._tools
        assert "add_watchlist_position" in mcp._tool_manager._tools
        assert "remove_watchlist_position" in mcp._tool_manager._tools

    @pytest.mark.asyncio
    async def test_create_watchlist_tool(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.watchlist_tools import register_watchlist_tools

        mcp = FastMCP("test")
        register_watchlist_tools(mcp)
        fn = mcp._tool_manager._tools["create_watchlist"].fn

        service = AsyncMock()
        service.create_watchlist.return_value = Watchlist(user_id="u1", name="Core")

        with patch("src.server.mcp.tools.watchlist_tools._get_service", return_value=service):
            result = await fn(user_id="u1", name="Core", description=None)

        assert result["name"] == "Core"
        service.create_watchlist.assert_awaited()


class TestSchedulerTools:
    @pytest.mark.asyncio
    async def test_register_scheduler_tools(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.scheduler_tools import register_scheduler_tools

        mcp = FastMCP("test")
        register_scheduler_tools(mcp)

        assert "create_scheduled_analysis" in mcp._tool_manager._tools
        assert "list_scheduled_analyses" in mcp._tool_manager._tools
        assert "run_scheduled_analysis_now" in mcp._tool_manager._tools
        assert "get_analysis_run_result" in mcp._tool_manager._tools

    @pytest.mark.asyncio
    async def test_run_scheduled_analysis_now(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.scheduler_tools import register_scheduler_tools

        mcp = FastMCP("test")
        register_scheduler_tools(mcp)
        fn = mcp._tool_manager._tools["run_scheduled_analysis_now"].fn

        service = AsyncMock()
        runner = AsyncMock()
        service.get_job.return_value = ScheduledAnalysisJob(
            job_id="j1",
            user_id="u1",
            name="Morning scan",
            watchlist_id="w1",
        )
        runner.run_job.return_value = AnalysisRun(job_id="j1")

        with patch("src.server.mcp.tools.scheduler_tools._get_service", return_value=service), \
             patch("src.server.mcp.tools.scheduler_tools._get_runner", return_value=runner):
            result = await fn(user_id="u1", job_id="j1")

        assert result["job_id"] == "j1"
        runner.run_job.assert_awaited()
