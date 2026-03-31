# src/server/domain/scheduler/repository.py
"""Redis-backed persistence for ScheduledAnalysisJob and AnalysisRun."""

from __future__ import annotations

import json
from typing import Optional

from src.server.domain.scheduler.models import (
    ScheduledAnalysisJob,
    AnalysisRun,
)
from src.server.utils.logger import logger


class RedisSchedulerRepository:
    def __init__(self, redis_conn):
        self._redis_conn = redis_conn

    async def _get_client(self):
        if not self._redis_conn.connected:
            ok = await self._redis_conn.connect()
            if not ok:
                raise RuntimeError("Redis not available")
        client = self._redis_conn.get_client()
        if client is None:
            raise RuntimeError("Redis client not available")
        return client

    # --- Job keys ---
    def _job_key(self, user_id: str, job_id: str) -> str:
        return f"scheduled_job:{user_id}:{job_id}"

    def _jobs_key(self, user_id: str) -> str:
        return f"scheduled_jobs:{user_id}"

    # --- Run keys ---
    def _run_key(self, job_id: str, run_id: str) -> str:
        return f"analysis_run:{job_id}:{run_id}"

    def _runs_key(self, job_id: str) -> str:
        return f"analysis_runs:{job_id}"

    # ---- Job CRUD ----
    async def save_job(self, job: ScheduledAnalysisJob) -> ScheduledAnalysisJob:
        client = await self._get_client()
        payload = job.model_dump(mode="json")
        await client.set(
            self._job_key(job.user_id, job.job_id),
            json.dumps(payload),
        )
        await client.sadd(self._jobs_key(job.user_id), job.job_id)
        return job

    async def get_job(
        self, user_id: str, job_id: str,
    ) -> Optional[ScheduledAnalysisJob]:
        client = await self._get_client()
        raw = await client.get(self._job_key(user_id, job_id))
        if not raw:
            return None
        return ScheduledAnalysisJob.model_validate(json.loads(raw))

    async def list_jobs(self, user_id: str) -> list[ScheduledAnalysisJob]:
        client = await self._get_client()
        job_ids = sorted(await client.smembers(self._jobs_key(user_id)))
        items: list[ScheduledAnalysisJob] = []
        for job_id in job_ids:
            job = await self.get_job(user_id, job_id)
            if job is not None:
                items.append(job)
        return items

    async def delete_job(self, user_id: str, job_id: str) -> bool:
        client = await self._get_client()
        existed = await client.get(self._job_key(user_id, job_id))
        if not existed:
            return False
        await client.delete(self._job_key(user_id, job_id))
        await client.srem(self._jobs_key(user_id), job_id)
        # Also delete associated runs
        run_ids = await client.smembers(self._runs_key(job_id))
        for run_id in run_ids:
            await client.delete(self._run_key(job_id, run_id))
        await client.delete(self._runs_key(job_id))
        return True

    async def list_enabled_jobs(self, user_id: str) -> list[ScheduledAnalysisJob]:
        all_jobs = await self.list_jobs(user_id)
        return [j for j in all_jobs if j.enabled]

    async def list_all_enabled_jobs(self) -> list[ScheduledAnalysisJob]:
        client = await self._get_client()
        items: list[ScheduledAnalysisJob] = []
        seen: set[str] = set()
        async for key in client.scan_iter(match="scheduled_job:*"):
            raw = await client.get(key)
            if not raw:
                continue
            job = ScheduledAnalysisJob.model_validate(json.loads(raw))
            if job.enabled and job.job_id not in seen:
                items.append(job)
                seen.add(job.job_id)
        return items

    # ---- Run CRUD ----
    async def save_run(self, run: AnalysisRun) -> AnalysisRun:
        client = await self._get_client()
        payload = run.model_dump(mode="json")
        await client.set(
            self._run_key(run.job_id, run.run_id),
            json.dumps(payload),
        )
        await client.sadd(self._runs_key(run.job_id), run.run_id)
        return run

    async def get_run(self, job_id: str, run_id: str) -> Optional[AnalysisRun]:
        client = await self._get_client()
        raw = await client.get(self._run_key(job_id, run_id))
        if not raw:
            return None
        return AnalysisRun.model_validate(json.loads(raw))

    async def list_runs(self, job_id: str, limit: int = 20) -> list[AnalysisRun]:
        client = await self._get_client()
        run_ids = sorted(await client.smembers(self._runs_key(job_id)))
        recent = run_ids[-limit:] if len(run_ids) > limit else run_ids
        items: list[AnalysisRun] = []
        for run_id in recent:
            run = await self.get_run(job_id, run_id)
            if run is not None:
                items.append(run)
        return items
