# src/server/domain/scheduler/service.py
"""Scheduler domain service — CRUD for jobs and triggering runs."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from src.server.domain.scheduler.models import (
    ScheduledAnalysisJob,
    AnalysisRun,
    AnalysisRunStatus,
    ScheduleType,
    AnalysisType,
)
from src.server.domain.scheduler.repository import RedisSchedulerRepository
from src.server.utils.logger import logger


class SchedulerService:
    def __init__(self, repo: RedisSchedulerRepository):
        self._repo = repo

    async def create_job(
        self,
        *,
        user_id: str,
        name: str,
        watchlist_id: str,
        schedule_type: ScheduleType = ScheduleType.daily,
        schedule_value: str = "09:00",
        analysis_types: Optional[list[str]] = None,
    ) -> ScheduledAnalysisJob:
        types = analysis_types or ["news", "filings"]
        job = ScheduledAnalysisJob(
            user_id=user_id,
            name=name,
            watchlist_id=watchlist_id,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            analysis_types=[AnalysisType(t) for t in types],
        )
        saved = await self._repo.save_job(job)
        logger.info("Created scheduled analysis job", job_id=job.job_id, user_id=user_id)
        return saved

    async def get_job(self, user_id: str, job_id: str) -> Optional[ScheduledAnalysisJob]:
        return await self._repo.get_job(user_id, job_id)

    async def list_jobs(self, user_id: str) -> list[ScheduledAnalysisJob]:
        return await self._repo.list_jobs(user_id)

    async def delete_job(self, user_id: str, job_id: str) -> bool:
        return await self._repo.delete_job(user_id, job_id)

    async def enable_job(self, user_id: str, job_id: str) -> Optional[ScheduledAnalysisJob]:
        job = await self._repo.get_job(user_id, job_id)
        if job is None:
            return None
        job.enabled = True
        job.updated_at = datetime.now(UTC)
        saved = await self._repo.save_job(job)
        return saved

    async def disable_job(self, user_id: str, job_id: str) -> Optional[ScheduledAnalysisJob]:
        job = await self._repo.get_job(user_id, job_id)
        if job is None:
            return None
        job.enabled = False
        job.updated_at = datetime.now(UTC)
        saved = await self._repo.save_job(job)
        return saved

    async def get_run(self, job_id: str, run_id: str) -> Optional[AnalysisRun]:
        return await self._repo.get_run(job_id, run_id)

    async def list_runs(self, job_id: str, limit: int = 20) -> list[AnalysisRun]:
        return await self._repo.list_runs(job_id, limit=limit)
