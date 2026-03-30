# src/server/domain/structured_data/repositories/raw_repository.py
"""Repository for raw_snapshots and dataset_jobs tables.

Handles: raw data ingestion, job tracking, and snapshot queries.
Uses raw asyncpg SQL (project pattern — no ORM).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.server.utils.logger import logger


class RawRepository:
    """Manages dataset_jobs and raw_snapshots tables."""

    def __init__(self, postgres_conn):
        self._pg = postgres_conn

    async def _get_pool(self):
        if not self._pg.connected:
            ok = await self._pg.connect()
            if not ok:
                return None
        return self._pg.get_client()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------
    async def ensure_schema(self) -> bool:
        """Create dataset_jobs and raw_snapshots tables if they don't exist."""
        pool = await self._get_pool()
        if not pool:
            logger.warning("RawRepository: PostgreSQL not available")
            return False

        async with pool.acquire() as conn:
            # dataset_jobs — tracks refresh/sync jobs
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dataset_jobs (
                    job_id       UUID PRIMARY KEY,
                    dataset_key  TEXT NOT NULL,
                    status       TEXT NOT NULL DEFAULT 'PENDING',
                    triggered_by TEXT NOT NULL DEFAULT 'manual',
                    source       TEXT,
                    total_records INT NOT NULL DEFAULT 0,
                    success_count INT NOT NULL DEFAULT 0,
                    fail_count    INT NOT NULL DEFAULT 0,
                    error_message TEXT,
                    started_at    TIMESTAMP,
                    completed_at  TIMESTAMP,
                    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)

            # raw_snapshots — raw data as fetched from source
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_snapshots (
                    snapshot_id   UUID PRIMARY KEY,
                    job_id        UUID NOT NULL REFERENCES dataset_jobs(job_id) ON DELETE CASCADE,
                    dataset_key   TEXT NOT NULL,
                    source        TEXT NOT NULL,
                    business_key  TEXT NOT NULL,
                    raw_data      JSONB NOT NULL DEFAULT '{}',
                    fetched_at    TIMESTAMP NOT NULL DEFAULT NOW(),
                    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)

            # Indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_raw_snapshots_dataset_key
                ON raw_snapshots(dataset_key)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_raw_snapshots_business_key
                ON raw_snapshots(dataset_key, business_key, source)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_raw_snapshots_job_id
                ON raw_snapshots(job_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_dataset_jobs_status
                ON dataset_jobs(dataset_key, status)
            """)

        logger.info("✅ RawRepository schema ensured")
        return True

    # ------------------------------------------------------------------
    # Dataset Jobs
    # ------------------------------------------------------------------
    async def create_job(
        self,
        dataset_key: str,
        triggered_by: str = "manual",
        source: Optional[str] = None,
    ) -> str:
        """Create a new dataset job and return its ID."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        job_id = str(uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO dataset_jobs (job_id, dataset_key, triggered_by, source)
                VALUES ($1, $2, $3, $4)
                """,
                job_id, dataset_key, triggered_by, source,
            )
        return job_id

    async def start_job(self, job_id: str) -> None:
        """Mark a job as running."""
        pool = await self._get_pool()
        if not pool:
            return
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE dataset_jobs
                SET status = 'RUNNING', started_at = NOW(), updated_at = NOW()
                WHERE job_id = $1
                """,
                job_id,
            )

    async def complete_job(
        self,
        job_id: str,
        success_count: int = 0,
        fail_count: int = 0,
        total_records: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """Mark a job as completed or partial."""
        pool = await self._get_pool()
        if not pool:
            return
        status = "COMPLETED" if fail_count == 0 else "PARTIAL"
        if error_message and success_count == 0:
            status = "FAILED"
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE dataset_jobs
                SET status = $2,
                    success_count = $3,
                    fail_count = $4,
                    total_records = $5,
                    error_message = $6,
                    completed_at = NOW(),
                    updated_at = NOW()
                WHERE job_id = $1
                """,
                job_id, status, success_count, fail_count,
                total_records, error_message,
            )

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID."""
        pool = await self._get_pool()
        if not pool:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM dataset_jobs WHERE job_id = $1", job_id,
            )
            return dict(row) if row else None

    async def list_jobs(
        self,
        dataset_key: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List jobs, optionally filtered by dataset_key and status."""
        pool = await self._get_pool()
        if not pool:
            return []
        async with pool.acquire() as conn:
            if dataset_key and status:
                rows = await conn.fetch(
                    """
                    SELECT * FROM dataset_jobs
                    WHERE dataset_key = $1 AND status = $2
                    ORDER BY created_at DESC LIMIT $3
                    """,
                    dataset_key, status, limit,
                )
            elif dataset_key:
                rows = await conn.fetch(
                    """
                    SELECT * FROM dataset_jobs
                    WHERE dataset_key = $1
                    ORDER BY created_at DESC LIMIT $2
                    """,
                    dataset_key, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM dataset_jobs
                    ORDER BY created_at DESC LIMIT $1
                    """,
                    limit,
                )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Raw Snapshots
    # ------------------------------------------------------------------
    async def insert_snapshot(
        self,
        job_id: str,
        dataset_key: str,
        source: str,
        business_key: str,
        raw_data: Dict[str, Any],
    ) -> str:
        """Insert a raw snapshot and return its ID."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        snapshot_id = str(uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO raw_snapshots (snapshot_id, job_id, dataset_key, source, business_key, raw_data)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                snapshot_id, job_id, dataset_key, source,
                business_key, json.dumps(raw_data, default=str),
            )
        return snapshot_id

    async def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Get a raw snapshot by ID."""
        pool = await self._get_pool()
        if not pool:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM raw_snapshots WHERE snapshot_id = $1",
                snapshot_id,
            )
            return dict(row) if row else None

    async def list_snapshots(
        self,
        dataset_key: str,
        business_key: Optional[str] = None,
        source: Optional[str] = None,
        job_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List raw snapshots with optional filters."""
        pool = await self._get_pool()
        if not pool:
            return []
        async with pool.acquire() as conn:
            conditions = ["dataset_key = $1"]
            params: list = [dataset_key]
            idx = 2

            if business_key:
                conditions.append(f"business_key = ${idx}")
                params.append(business_key)
                idx += 1
            if source:
                conditions.append(f"source = ${idx}")
                params.append(source)
                idx += 1
            if job_id:
                conditions.append(f"job_id = ${idx}")
                params.append(job_id)
                idx += 1

            params.append(limit)
            where = " AND ".join(conditions)
            rows = await conn.fetch(
                f"SELECT * FROM raw_snapshots WHERE {where} ORDER BY fetched_at DESC LIMIT ${idx}",
                *params,
            )
        return [dict(r) for r in rows]

    async def get_latest_snapshot(
        self,
        dataset_key: str,
        business_key: str,
        source: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent snapshot for a given key + source."""
        pool = await self._get_pool()
        if not pool:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM raw_snapshots
                WHERE dataset_key = $1 AND business_key = $2 AND source = $3
                ORDER BY fetched_at DESC LIMIT 1
                """,
                dataset_key, business_key, source,
            )
            return dict(row) if row else None
