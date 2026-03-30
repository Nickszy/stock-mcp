# src/server/domain/structured_data/repositories/canonical_repository.py
"""Repository for canonical data records - version tracking and rollback.

Uses raw asyncpg SQL (project pattern - no ORM).
All version mutations use atomic subqueries or single-statement operations
to prevent race conditions under concurrent writes.
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
                    source        TEXT NOT NULL DEFAULT 'auto',
                    published_at  TIMESTAMP NOT NULL DEFAULT NOW(),
                    superseded_at TIMESTAMP,
                    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at    TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            # UNIQUE constraint prevents version race conditions
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_canonical_bizkey_version
                ON canonical_records(dataset_key, business_key, version)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_dataset
                ON canonical_records(dataset_key)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical_bizkey_active
                ON canonical_records(dataset_key, business_key)
                WHERE superseded_at IS NULL
            """)
        logger.info("CanonicalRepository schema ensured")
        return True

    async def publish(
        self,
        candidate_id: str,
        dataset_key: str,
        business_key: str,
        data: Dict[str, Any],
        source: str = "auto",
    ) -> str:
        """Publish data to canonical table atomically.

        Uses a single transaction with:
        1. Atomic version via subquery (no read-then-write race)
        2. Mark older records as superseded
        3. Insert new record
        """
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        canonical_id = str(uuid4())

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Mark older active records as superseded
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
                # Insert new record with atomic version
                await conn.execute(
                    """
                    INSERT INTO canonical_records (
                        canonical_id, dataset_key, business_key, candidate_id,
                        data, version, source
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        (SELECT COALESCE(MAX(version), 0) + 1
                         FROM canonical_records
                         WHERE dataset_key = $2 AND business_key = $3),
                        $6
                    )
                    """,
                    canonical_id,
                    dataset_key,
                    business_key,
                    candidate_id,
                    json.dumps(data, default=str),
                    source,
                )

        logger.info(
            "Published canonical record",
            dataset_key=dataset_key,
            business_key=business_key,
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

        Creates a NEW record (new version) that copies the target version's data,
        preserving full audit trail rather than mutating superseded_at flags.

        Returns the new canonical_id.
        """
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        new_id = str(uuid4())

        async with pool.acquire() as conn:
            async with conn.transaction():
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
                # Insert new record copying data from target version
                await conn.execute(
                    """
                    INSERT INTO canonical_records (
                        canonical_id, dataset_key, business_key, candidate_id,
                        data, version, source
                    ) SELECT
                        $1, dataset_key, business_key, candidate_id,
                        data,
                        (SELECT COALESCE(MAX(version), 0) + 1
                         FROM canonical_records
                         WHERE dataset_key = canonical_records.dataset_key
                           AND business_key = canonical_records.business_key),
                        'rollback'
                    FROM canonical_records
                    WHERE dataset_key = $2 AND business_key = $3 AND version = $4
                    """,
                    new_id,
                    dataset_key,
                    business_key,
                    target_version,
                )

        logger.info(
            "Rollback complete",
            dataset_key=dataset_key,
            business_key=business_key,
            target_version=target_version,
        )
        return new_id
