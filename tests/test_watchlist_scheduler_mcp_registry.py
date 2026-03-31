from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, ".")


async def _call_tool(mcp, tool_name: str, **kwargs):
    return await mcp._tool_manager._tools[tool_name].fn(**kwargs)


def _make_stub(item):
    """Create a stub object with a model_dump method that captures its own item (avoids closure bug)."""
    stub = type(
        f"Stub_{id(item)}",
        (),
        {"model_dump": lambda self, mode="json": item.copy()},
    )
    return stub()


class TestWatchlistMcpTools:
    @pytest.fixture
    def mcp(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.watchlist_tools import register_watchlist_tools

        mcp = FastMCP("test")
        register_watchlist_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_list_watchlists_returns_total_and_items(self, mcp):
        watchlists = [
            {"watchlist_id": "w1", "user_id": "u1", "name": "核心", "positions": []},
            {"watchlist_id": "w2", "user_id": "u1", "name": "观察", "positions": []},
        ]
        service = AsyncMock()
        service.list_watchlists.return_value = [_make_stub(item) for item in watchlists]

        with patch("src.server.mcp.tools.watchlist_tools._get_service", return_value=service):
            result = await _call_tool(mcp, "list_watchlists", user_id="u1")

        assert result["user_id"] == "u1"
        assert result["total"] == 2
        assert [item["watchlist_id"] for item in result["watchlists"]] == ["w1", "w2"]


class TestSchedulerMcpTools:
    @pytest.fixture
    def mcp(self):
        from fastmcp import FastMCP
        from src.server.mcp.tools.scheduler_tools import register_scheduler_tools

        mcp = FastMCP("test")
        register_scheduler_tools(mcp)
        return mcp

    @pytest.mark.asyncio
    async def test_list_scheduled_analyses_returns_total_and_jobs(self, mcp):
        jobs = [
            {"job_id": "j1", "user_id": "u1", "name": "晨报"},
            {"job_id": "j2", "user_id": "u1", "name": "午报"},
        ]
        service = AsyncMock()
        service.list_jobs.return_value = [_make_stub(item) for item in jobs]

        with patch("src.server.mcp.tools.scheduler_tools._get_service", return_value=service):
            result = await _call_tool(mcp, "list_scheduled_analyses", user_id="u1")

        assert result["user_id"] == "u1"
        assert result["total"] == 2
        assert [item["job_id"] for item in result["jobs"]] == ["j1", "j2"]

    @pytest.mark.asyncio
    async def test_run_scheduled_analysis_now_returns_error_when_job_missing(self, mcp):
        service = AsyncMock()
        service.get_job.return_value = None
        runner = AsyncMock()

        with patch("src.server.mcp.tools.scheduler_tools._get_service", return_value=service), patch(
            "src.server.mcp.tools.scheduler_tools._get_runner", return_value=runner
        ):
            result = await _call_tool(mcp, "run_scheduled_analysis_now", user_id="u1", job_id="missing")

        assert result == {"error": "Job missing not found"}
        runner.run_job.assert_not_called()


def test_registry_enabled_tool_count_matches_group_sum():
    from src.server.mcp.registry import TOOL_GROUPS, get_enabled_tool_count

    expected = sum(group.count for group in TOOL_GROUPS if group.enabled)

    assert get_enabled_tool_count() == expected
    # watchlist(4) + scheduler(4) = 8 new tools added
    assert expected == 206
