# src/server/domain/scheduler/engine.py
"""Scheduler engine — manages background scheduling using APScheduler or in-process fallback."""
from __future__ import annotations

from typing import Optional

from apscheduler.triggers.cron import CronTrigger

from src.server.domain.scheduler.models import ScheduledAnalysisJob, ScheduleType
from src.server.domain.scheduler.repository import RedisSchedulerRepository
from src.server.domain.scheduler.runner import SchedulerRunner
from src.server.utils.logger import logger


class SchedulerEngine:
    """Manages the lifecycle of scheduled jobs.

    Wraps APScheduler when available, otherwise provides
    manual-trigger-only mode (no automatic execution).
    """

    def __init__(
        self,
        scheduler_repo: RedisSchedulerRepository,
        runner: SchedulerRunner,
    ):
        self._repo = scheduler_repo
        self._runner = runner
        self._scheduler = None
        self._running = False

    def _create_scheduler(self):
        """Try to create an APScheduler instance, fall back to None."""
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            scheduler = AsyncIOScheduler(timezone="UTC")
            logger.info("APScheduler AsyncIOScheduler created")
            return scheduler
        except ImportError:
            logger.info("APScheduler not available — manual-trigger mode only")
            return None
        except Exception as e:
            logger.warning(f"Failed to create APScheduler: {e}")
            return None

    async def start(self) -> None:
        """Start the scheduler engine and restore enabled jobs."""
        self._scheduler = self._create_scheduler()
        if self._scheduler:
            self._scheduler.start()
            logger.info("Scheduler engine started (APScheduler)")
        else:
            logger.info("Scheduler engine started (manual-trigger mode)")

        self._running = True
        await self._restore_enabled_jobs()

    async def stop(self) -> None:
        """Stop the scheduler engine."""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler engine stopped (APScheduler)")
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def _restore_enabled_jobs(self) -> None:
        jobs = await self._repo.list_all_enabled_jobs()
        if not jobs:
            logger.info("No enabled scheduler jobs to restore")
            return
        restored = 0
        for job in jobs:
            await self.sync_job(job)
            restored += 1
        logger.info("Restored enabled scheduler jobs", count=restored)

    async def sync_job(self, job: ScheduledAnalysisJob) -> None:
        """Add or update a job in the scheduler (if APScheduler is available)."""
        if not self._scheduler:
            return
        job_id = job.job_id
        # Remove existing if present
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        if job.enabled:
            trigger = self._build_trigger(job)
            if trigger is None:
                logger.warning("Could not build trigger for job", job_id=job_id)
                return
            self._scheduler.add_job(
                self._execute_job,
                trigger,
                id=job_id,
                args=[job.job_id, job.user_id],
                replace_existing=True,
            )
            logger.info(
                "Synced job to APScheduler",
                job_id=job.job_id,
                schedule=job.schedule_value,
            )

    @staticmethod
    def _build_trigger(job: ScheduledAnalysisJob):
        """Build an APScheduler trigger from the job's schedule config."""
        try:
            if job.schedule_type == ScheduleType.daily:
                parts = job.schedule_value.strip().split(":")
                return CronTrigger(hour=int(parts[0]), minute=int(parts[1]))
            elif job.schedule_type == ScheduleType.weekly:
                # Format: "DOW HH:MM" e.g. "MON 09:30"
                dow, time_str = job.schedule_value.strip().split()
                hour, minute = time_str.split(":")
                return CronTrigger(
                    day_of_week=dow[:3].lower(),
                    hour=int(hour),
                    minute=int(minute),
                )
            elif job.schedule_type == ScheduleType.cron:
                # 5-field cron: "min hour dom month dow"
                fields = job.schedule_value.strip().split()
                return CronTrigger(
                    minute=fields[0],
                    hour=fields[1],
                    day=fields[2],
                    month=fields[3],
                    day_of_week=fields[4],
                )
        except Exception as e:
            logger.warning("Failed to build trigger", job_id=job.job_id, error=str(e))
            return None

    async def remove_job(self, job_id: str) -> None:
        """Remove a job from the scheduler."""
        if not self._scheduler:
            return
        try:
            self._scheduler.remove_job(job_id)
            logger.info("Removed job from APScheduler", job_id=job_id)
        except Exception:
            pass

    async def _execute_job(self, job_id: str, user_id: str) -> None:
        """Callback for APScheduler — load job and run it."""
        try:
            job = await self._repo.get_job(user_id, job_id)
            if job is None or not job.enabled:
                return
            await self._runner.run_job(job)
        except Exception as e:
            logger.error(
                "Scheduled job execution failed",
                job_id=job_id,
                error=str(e),
            )
