# src/server/domain/structured_data/repositories/canonical_repository.py
"""Repository for canonical data records - version tracking and rollback.

Uses raw asyncpg SQL (project pattern - no ORM).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.server.utils.logger import logger


class CanonicalRepository:
    """Manages canonical_records table - published records, version tracking, and rollback."""

    def __init__(self, postgres_conn):
        self._pg = postgres_conn

    async def _get_pool(self):
        if not self._pg.connected:
            ok = await self._pg.connect()
            if not ok:
                return None
        return self._pg.get_client()

    async def ensure_schema(self) -> bool:
        pool = await self._get_pool()
        if not pool:
            logger.warning("CanonicalRepository: PostgreSQL not available")
            return False
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS canonical_records (
                    canonical_id  UUID PRIMARY KEY,
                    dataset_key   TEXT NOT NULL,
                    business_key  TEXT NOT NULL,
                    candidate_id UUID,
                    data          JSONB NOT NULL DEFAULT '{}',
                    version       INT NOT NULL DEFAULT 1,
                    source       TEXT NOT NULL DEFAULT 'auto',
                    published_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    superseded_at TIMESTAMP,
                    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_dataset
                ON canonical_records(dataset_key)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_bizkey_ver
                ON canonical_records(dataset_key, business_key, version)
            """)
        logger.info("CanonicalRepository schema ensured")
        return True

    async def _next_version(self, pool, dataset_key: str, business_key: str) -> int:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT MAX(version) as max_ver
                FROM canonical_records
                WHERE dataset_key = $1 AND business_key = $2
                """,
                dataset_key,
                business_key,
            )
            return (row["max_ver"] or 0) + 1

    async def publish(
        self,
        candidate_id: str,
        dataset_key: str,
        business_key: str,
        data: Dict[str, Any],
        source: str = "auto",
    ) -> str:
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        canonical_id = str(uuid4())
        version = await self._next_version(pool, dataset_key, business_key)

        async with pool.acquire() as conn:
            # Mark older active records as superseded
            await conn.execute(
                """
                UPDATE canonical_records
                SET superseded_at = NOW(), updated_at = NOW()
                WHERE dataset_key = $1 AND business_key = $2
                  AND superseded_at IS NULL
                  AND canonical_id != $3
                """,
                dataset_key,
                business_key,
                canonical_id,
            )
            # Insert new canonical record
            await conn.execute(
                """
                INSERT INTO canonical_records (
                    canonical_id, dataset_key, business_key, candidate_id,
                    data, version, source
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                canonical_id,
                dataset_key,
                business_key,
                candidate_id,
                json.dumps(data, default=str),
                version,
                source,
            )

        logger.info(
            "Published canonical record",
            dataset_key=dataset_key,
            business_key=business_key,
            version=version,
            source=source,
        )
        return canonical_id

    async def get_current(self, dataset_key: str, business_key: str) -> Optional[Dict[str, Any]]:
        pool = await self._get_pool()
        if not pool:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM canonical_records
                WHERE dataset_key = $1 AND business_key = $2
                  AND superseded_at IS NULL
                ORDER BY version DESC LIMIT 1
                """,
                dataset_key,
                business_key,
            )
            return dict(row) if row else None

    async def get_version_history(
        self,
        dataset_key: str,
        business_key: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        if not pool:
            return []
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM canonical_records
                WHERE dataset_key = $1 AND business_key = $2
                ORDER BY version DESC LIMIT $3
                """,
                dataset_key,
                business_key,
                limit,
            )
        return [dict(r) for r in rows]

    async def list_by_dataset(self, dataset_key: str, limit: int = 50) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        if not pool:
            return []
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM canonical_records
                WHERE dataset_key = $1
                ORDER BY published_at DESC LIMIT $2
                """,
                dataset_key,
                limit,
            )
        return [dict(r) for r in rows]

    async def rollback(self, dataset_key: str, business_key: str, target_version: int) -> int:
        """Roll back: supersede newer versions, re-publish the target version.

        Returns the number of records superseded.
        """
        pool = await self._get_pool()
        if not pool:
            return 0
        async with pool.acquire() as conn:
            # Mark current active records as superseded
            await conn.execute(
                """
                UPDATE canonical_records
                SET superseded_at = NOW(), updated_at = NOW()
                WHERE dataset_key = $1 AND business_key = $2
                  AND superseded_at IS NULL
                """,
                dataset_key,
                business_key,
            )
            # Un-supersede the target version (re-publish it it )
            result = await conn.execute(
                """
                UPDATE canonical_records
                SET superseded_at = NULL, updated_at = NOW()
                WHERE dataset_key = $1 AND business_key = $2
                  AND version = $3
                """,
                dataset_key,
                business_key,
                target_version,
            )
            count = int(result.split()[-1]) if result else 0
            logger.info(
                "Rollback complete",
                dataset_key=dataset_key,
                business_key=business_key,
                target_version=target_version,
                affected=count,
    )
        return count
