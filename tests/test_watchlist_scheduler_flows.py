from __future__ import annotations

import sys
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, ".")

from src.server.domain.scheduler.models import AnalysisRun, AnalysisRunStatus, ScheduledAnalysisJob, ScheduleType
from src.server.domain.watchlist.models import Watchlist


class _FakeWatchlistService:
    def __init__(self):
        self.created = []
        self.watchlist = Watchlist(user_id="u1", name="核心", description="长期")

    async def create_watchlist(self, user_id: str, name: str, description: str | None = None):
        self.created.append((user_id, name, description))
        self.watchlist = Watchlist(user_id=user_id, name=name, description=description)
        return self.watchlist

    async def list_watchlists(self, user_id: str):
        return [self.watchlist]

    async def get_watchlist(self, user_id: str, watchlist_id: str):
        if watchlist_id != self.watchlist.watchlist_id:
            return None
        return self.watchlist

    async def add_position(self, **kwargs):
        return self.watchlist

    async def remove_position(self, user_id: str, watchlist_id: str, ticker: str):
        return ticker.upper() == "SZSE:000001"


class _FakeSchedulerService:
    def __init__(self):
        self.job = ScheduledAnalysisJob(
            user_id="u1",
            name="早报",
            watchlist_id="wl-1",
            schedule_type=ScheduleType.daily,
            schedule_value="09:00",
        )
        self.created = []
        self.enabled = []
        self.disabled = []

    async def create_job(self, **kwargs):
        self.created.append(kwargs)
        self.job = ScheduledAnalysisJob(**kwargs)
        return self.job

    async def list_jobs(self, user_id: str):
        return [self.job]

    async def get_job(self, user_id: str, job_id: str):
        if job_id != self.job.job_id:
            return None
        return self.job

    async def enable_job(self, user_id: str, job_id: str):
        self.enabled.append((user_id, job_id))
        if job_id != self.job.job_id:
            return None
        self.job.enabled = True
        return self.job

    async def disable_job(self, user_id: str, job_id: str):
        self.disabled.append((user_id, job_id))
        if job_id != self.job.job_id:
            return None
        self.job.enabled = False
        return self.job

    async def list_runs(self, job_id: str, limit: int = 20):
        return []

    async def get_run(self, job_id: str, run_id: str):
        return None


@pytest.fixture
def watchlist_client():
    from src.server.api.routes.watchlist import router, set_watchlist_components
    from fastapi import FastAPI

    app = FastAPI()
    service = _FakeWatchlistService()
    set_watchlist_components(service=service)
    app.include_router(router)
    return TestClient(app), service


@pytest.fixture
def scheduler_client():
    from src.server.api.routes.scheduler import router, set_scheduler_components
    from fastapi import FastAPI

    app = FastAPI()
    service = _FakeSchedulerService()
    runner = AsyncMock()
    runner.run_job.return_value = AnalysisRun(job_id=service.job.job_id, status=AnalysisRunStatus.success)
    engine = AsyncMock()
    set_scheduler_components(service=service, runner=runner, engine=engine, repo=None)
    app.include_router(router)
    return TestClient(app), service, runner, engine


class TestWatchlistRestFlows:
    def test_create_watchlist_returns_rest_payload(self, watchlist_client):
        client, service = watchlist_client

        response = client.post(
            "/api/v1/watchlists",
            json={"user_id": "u1", "name": "核心持仓", "description": "长期"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["code"] == 0
        assert payload["message"] == "success"
        assert payload["data"]["user_id"] == "u1"
        assert payload["data"]["name"] == "核心持仓"
        assert service.created == [("u1", "核心持仓", "长期")]

    def test_remove_position_returns_404_when_position_missing(self, watchlist_client):
        client, _ = watchlist_client

        response = client.delete(
            "/api/v1/watchlists/unknown/positions/nasdaq:aapl",
            params={"user_id": "u1"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Position not found"


class TestSchedulerRestFlows:
    def test_create_job_syncs_engine_and_returns_rest_payload(self, scheduler_client):
        client, service, _, engine = scheduler_client

        response = client.post(
            "/api/v1/scheduler/jobs",
            json={
                "user_id": "u1",
                "name": "开盘监控",
                "watchlist_id": "wl-1",
                "schedule_type": "daily",
                "schedule_value": "09:30",
                "analysis_types": ["news", "fact_pack"],
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["code"] == 0
        assert payload["message"] == "success"
        assert payload["data"]["name"] == "开盘监控"
        assert service.created[0]["schedule_value"] == "09:30"
        engine.sync_job.assert_awaited_once()

    def test_run_job_returns_run_payload(self, scheduler_client):
        client, service, runner, _ = scheduler_client

        response = client.post(
            f"/api/v1/scheduler/jobs/{service.job.job_id}/run",
            params={"user_id": "u1"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["code"] == 0
        assert payload["message"] == "success"
        assert payload["data"]["job_id"] == service.job.job_id
        assert payload["data"]["status"] == "success"
        runner.run_job.assert_awaited_once()

    def test_disable_job_removes_job_from_engine(self, scheduler_client):
        client, service, _, engine = scheduler_client

        response = client.post(
            f"/api/v1/scheduler/jobs/{service.job.job_id}/disable",
            params={"user_id": "u1"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["data"]["enabled"] is False
        engine.remove_job.assert_awaited_once_with(service.job.job_id)
