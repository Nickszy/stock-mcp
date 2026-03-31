from __future__ import annotations

import sys
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, ".")

from src.server.domain.scheduler.models import AnalysisRun, ScheduledAnalysisJob
from src.server.domain.watchlist.models import Watchlist, WatchlistPosition


class TestWatchlistRoutes:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from src.server.api.routes.watchlist import set_watchlist_components

        self.service = AsyncMock()
        set_watchlist_components(service=self.service)
        yield
        set_watchlist_components(service=None)

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from src.server.api.routes.watchlist import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_create_watchlist(self, client: TestClient):
        self.service.create_watchlist.return_value = Watchlist(user_id="u1", name="Core")

        response = client.post(
            "/api/v1/watchlists",
            json={"user_id": "u1", "name": "Core", "description": "Main holdings"},
        )

        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["user_id"] == "u1"
        assert payload["name"] == "Core"

    def test_add_position(self, client: TestClient):
        watchlist = Watchlist(
            user_id="u1",
            name="Core",
            positions=[
                WatchlistPosition(
                    ticker="NASDAQ:AAPL",
                    quantity=10,
                    average_cost=180,
                )
            ],
        )
        self.service.add_position.return_value = watchlist

        response = client.post(
            "/api/v1/watchlists/w1/positions?user_id=u1",
            json={
                "ticker": "NASDAQ:AAPL",
                "quantity": 10,
                "average_cost": 180,
            },
        )

        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["positions"][0]["ticker"] == "NASDAQ:AAPL"


class TestSchedulerRoutes:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from src.server.api.routes.scheduler import set_scheduler_components

        self.service = AsyncMock()
        self.runner = AsyncMock()
        self.engine = AsyncMock()
        self.repo = AsyncMock()
        set_scheduler_components(
            service=self.service,
            runner=self.runner,
            engine=self.engine,
            repo=self.repo,
        )
        yield
        set_scheduler_components(service=None, runner=None, engine=None, repo=None)

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from src.server.api.routes.scheduler import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_create_job(self, client: TestClient):
        job = ScheduledAnalysisJob(
            user_id="u1",
            name="Morning scan",
            watchlist_id="w1",
        )
        self.service.create_job.return_value = job

        response = client.post(
            "/api/v1/scheduler/jobs",
            json={
                "user_id": "u1",
                "name": "Morning scan",
                "watchlist_id": "w1",
                "schedule_type": "daily",
                "schedule_value": "09:00",
            },
        )

        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["name"] == "Morning scan"
        self.engine.sync_job.assert_awaited()

    def test_run_job(self, client: TestClient):
        job = ScheduledAnalysisJob(
            job_id="j1",
            user_id="u1",
            name="Morning scan",
            watchlist_id="w1",
        )
        run = AnalysisRun(job_id="j1")
        self.service.get_job.return_value = job
        self.runner.run_job.return_value = run

        response = client.post("/api/v1/scheduler/jobs/j1/run?user_id=u1")

        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["job_id"] == "j1"
