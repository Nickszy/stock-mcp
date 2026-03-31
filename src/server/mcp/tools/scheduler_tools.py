# src/server/mcp/tools/scheduler_tools.py
"""MCP tools for scheduled analysis management."""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

from src.server.domain.scheduler import (
    RedisSchedulerRepository,
    SchedulerService,
    SchedulerRunner,
    ScheduleType,
)
from src.server.domain.watchlist import RedisWatchlistRepository
from src.server.core.dependencies import Container
from src.server.utils.logger import logger

# Module-level runner/engine refs (set from bootstrap or lazily initialized)
_runner: Optional[SchedulerRunner] = None


def set_scheduler_tools_runner(runner: SchedulerRunner) -> None:
    global _runner
    _runner = runner


def _get_service() -> SchedulerService:
    redis_conn = Container.redis()
    repo = RedisSchedulerRepository(redis_conn)
    return SchedulerService(repo)


def _get_runner() -> SchedulerRunner:
    if _runner is not None:
        return _runner
    redis_conn = Container.redis()
    scheduler_repo = RedisSchedulerRepository(redis_conn)
    watchlist_repo = RedisWatchlistRepository(redis_conn)
    gateway = Container.market_gateway()
    news_service = Container.news_service()
    filings_service = Container.filings_service()
    research_report_service = Container.research_report_service()
    return SchedulerRunner(
        scheduler_repo=scheduler_repo,
        watchlist_repo=watchlist_repo,
        gateway=gateway,
        news_service=news_service,
        filings_service=filings_service,
        research_report_service=research_report_service,
    )


def register_scheduler_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def create_scheduled_analysis(
        user_id: str,
        name: str,
        watchlist_id: str,
        schedule_type: str = "daily",
        schedule_value: str = "09:00",
        analysis_types: Optional[list[str]] = None,
    ) -> dict:
        """创建定时分析任务。对指定自选股组合定期执行新闻/公告/研报/事实包分析。"""
        service = _get_service()
        job = await service.create_job(
            user_id=user_id,
            name=name,
            watchlist_id=watchlist_id,
            schedule_type=ScheduleType(schedule_type),
            schedule_value=schedule_value,
            analysis_types=analysis_types,
        )
        return job.model_dump(mode="json")

    @mcp.tool()
    async def list_scheduled_analyses(user_id: str) -> dict:
        """列出用户的所有定时分析任务。"""
        service = _get_service()
        jobs = await service.list_jobs(user_id)
        return {
            "user_id": user_id,
            "total": len(jobs),
            "jobs": [j.model_dump(mode="json") for j in jobs],
        }

    @mcp.tool()
    async def run_scheduled_analysis_now(
        user_id: str,
        job_id: str,
    ) -> dict:
        """立即执行一次定时分析任务（不等定时触发）。"""
        service = _get_service()
        runner = _get_runner()
        job = await service.get_job(user_id, job_id)
        if job is None:
            return {"error": f"Job {job_id} not found"}
        run = await runner.run_job(job)
        return run.model_dump(mode="json")

    @mcp.tool()
    async def get_analysis_run_result(
        user_id: str,
        job_id: str,
        run_id: str,
    ) -> dict:
        """获取某次分析执行的详细结果。"""
        service = _get_service()
        run = await service.get_run(user_id, job_id, run_id)
        if run is None:
            return {"error": f"Run {run_id} not found for job {job_id}"}
        return run.model_dump(mode="json")
