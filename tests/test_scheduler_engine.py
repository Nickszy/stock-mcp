from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, ".")

from src.server.domain.scheduler.engine import SchedulerEngine
from src.server.domain.scheduler.models import ScheduledAnalysisJob


class TestSchedulerEngine:
    @pytest.mark.asyncio
    async def test_start_restores_enabled_jobs(self):
        repo = AsyncMock()
        runner = AsyncMock()
        scheduler = MagicMock()
        scheduler.start.return_value = None
        repo.list_all_enabled_jobs.return_value = [
            ScheduledAnalysisJob(
                job_id="j1",
                user_id="u1",
                name="Morning scan",
                watchlist_id="w1",
                enabled=True,
            ),
            ScheduledAnalysisJob(
                job_id="j2",
                user_id="u2",
                name="Close scan",
                watchlist_id="w2",
                enabled=True,
            ),
        ]

        engine = SchedulerEngine(repo, runner)
        engine._create_scheduler = lambda: scheduler
        engine.sync_job = AsyncMock()

        await engine.start()

        scheduler.start.assert_called_once()
        assert engine.is_running is True
        assert engine.sync_job.await_count == 2

    @pytest.mark.asyncio
    async def test_start_without_enabled_jobs(self):
        repo = AsyncMock()
        runner = AsyncMock()
        repo.list_all_enabled_jobs.return_value = []

        engine = SchedulerEngine(repo, runner)
        engine._create_scheduler = lambda: None
        engine.sync_job = AsyncMock()

        await engine.start()

        assert engine.is_running is True
        engine.sync_job.assert_not_awaited()
