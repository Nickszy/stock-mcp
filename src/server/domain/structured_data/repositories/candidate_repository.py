# src/server/domain/structured_data/repositories/candidate_repository.py
"""Repository for normalized_candidates and validation_issues tables.

Handles: normalized data storage, validation issues, state transitions,
and comparison results.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.server.utils.logger import logger

from ..enums import PipelineState, can_transition


class CandidateRepository:
    """Manages normalized_candidates and validation_issues tables."""

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
        """Create normalized_candidates and validation_issues tables."""
        pool = await self._get_pool()
        if not pool:
            logger.warning("CandidateRepository: PostgreSQL not available")
            return False

        async with pool.acquire() as conn:
            # normalized_candidates — normalized data with state tracking
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS normalized_candidates (
                    candidate_id      UUID PRIMARY KEY,
                    snapshot_id       UUID NOT NULL,
                    job_id            UUID NOT NULL,
                    dataset_key       TEXT NOT NULL,
                    source            TEXT NOT NULL,
                    business_key      TEXT NOT NULL,
                    normalized_data   JSONB NOT NULL DEFAULT '{}',
                    state             TEXT NOT NULL DEFAULT 'RAW_INGESTED',
                    confidence_score  REAL,
                    comparison_result JSONB,
                    version           INT NOT NULL DEFAULT 1,
                    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
                    updated_at        TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)

            # validation_issues — issues found during validation
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS validation_issues (
                    issue_id       UUID PRIMARY KEY,
                    candidate_id   UUID NOT NULL,
                    dataset_key    TEXT NOT NULL,
                    rule_name      TEXT NOT NULL,
                    severity       TEXT NOT NULL DEFAULT 'WARNING',
                    status         TEXT NOT NULL DEFAULT 'OPEN',
                    field_path     TEXT,
                    expected_value TEXT,
                    actual_value   TEXT,
                    message        TEXT,
                    created_at     TIMESTAMP NOT NULL DEFAULT NOW(),
                    resolved_at    TIMESTAMP
                )
            """)

            # Indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_candidates_dataset_key
                ON normalized_candidates(dataset_key)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_candidates_business_key
                ON normalized_candidates(dataset_key, business_key)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_candidates_state
                ON normalized_candidates(dataset_key, state)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_candidates_source
                ON normalized_candidates(dataset_key, source, business_key)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_issues_candidate_id
                ON validation_issues(candidate_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_issues_status
                ON validation_issues(dataset_key, status)
            """)

        logger.info("✅ CandidateRepository schema ensured")
        return True

    # ------------------------------------------------------------------
    # Candidates — CRUD
    # ------------------------------------------------------------------
    async def insert_candidate(
        self,
        snapshot_id: str,
        job_id: str,
        dataset_key: str,
        source: str,
        business_key: str,
        normalized_data: Dict[str, Any],
    ) -> str:
        """Insert a new normalized candidate and return its ID."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        # Determine next version
        version = await self._next_version(pool, dataset_key, business_key)

        candidate_id = str(uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO normalized_candidates (
                    candidate_id, snapshot_id, job_id, dataset_key,
                    source, business_key, normalized_data, version
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                candidate_id, snapshot_id, job_id, dataset_key,
                source, business_key, json.dumps(normalized_data, default=str),
                version,
            )
        return candidate_id

    async def _next_version(self, pool, dataset_key: str, business_key: str) -> int:
        """Get the next version number for a business key."""
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT MAX(version) as max_ver
                FROM normalized_candidates
                WHERE dataset_key = $1 AND business_key = $2
                """,
                dataset_key, business_key,
            )
            return (row["max_ver"] or 0) + 1

    async def get_candidate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        """Get a candidate by ID."""
        pool = await self._get_pool()
        if not pool:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM normalized_candidates WHERE candidate_id = $1",
                candidate_id,
            )
            return dict(row) if row else None

    async def list_candidates(
        self,
        dataset_key: str,
        business_key: Optional[str] = None,
        state: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List candidates with optional filters."""
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
            if state:
                conditions.append(f"state = ${idx}")
                params.append(state)
                idx += 1
            if source:
                conditions.append(f"source = ${idx}")
                params.append(source)
                idx += 1

            params.append(limit)
            where = " AND ".join(conditions)
            rows = await conn.fetch(
                f"""
                SELECT * FROM normalized_candidates
                WHERE {where}
                ORDER BY version DESC, created_at DESC LIMIT ${idx}
                """,
                *params,
            )
        return [dict(r) for r in rows]

    async def get_latest_candidate(
        self,
        dataset_key: str,
        business_key: str,
    ) -> Optional[Dict[str, Any]]:
        """Get the latest version of a candidate by business key."""
        pool = await self._get_pool()
        if not pool:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM normalized_candidates
                WHERE dataset_key = $1 AND business_key = $2
                ORDER BY version DESC LIMIT 1
                """,
                dataset_key, business_key,
            )
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Candidates — State transitions
    # ------------------------------------------------------------------
    async def transition_state(
        self,
        candidate_id: str,
        new_state: str,
        confidence_score: Optional[float] = None,
        comparison_result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Transition a candidate to a new state. Validates the transition first."""
        pool = await self._get_pool()
        if not pool:
            return False

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state FROM normalized_candidates WHERE candidate_id = $1",
                candidate_id,
            )
            if not row:
                return False

            from_state = PipelineState(row["state"])
            to_state = PipelineState(new_state)

            if not can_transition(from_state, to_state):
                raise ValueError(
                    f"Invalid transition: {from_state.value} → {to_state.value}"
                )

            sets = ["state = $2", "updated_at = NOW()"]
            params: list = [candidate_id, new_state]
            idx = 3

            if confidence_score is not None:
                sets.append(f"confidence_score = ${idx}")
                params.append(confidence_score)
                idx += 1
            if comparison_result is not None:
                sets.append(f"comparison_result = ${idx}")
                params.append(json.dumps(comparison_result, default=str))
                idx += 1

            set_clause = ", ".join(sets)
            await conn.execute(
                f"UPDATE normalized_candidates SET {set_clause} WHERE candidate_id = $1",
                *params,
            )
        return True

    async def mark_superseded(
        self,
        dataset_key: str,
        business_key: str,
        except_candidate_id: str,
    ) -> int:
        """Mark all older PUBLISHED/AUTO_PUBLISHED candidates as SUPERSEDED."""
        pool = await self._get_pool()
        if not pool:
            return 0
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE normalized_candidates
                SET state = 'SUPERSEDED', updated_at = NOW()
                WHERE dataset_key = $1
                  AND business_key = $2
                  AND candidate_id != $3
                  AND state IN ('AUTO_PUBLISHED', 'PUBLISHED')
                """,
                dataset_key, business_key, except_candidate_id,
            )
            count = int(result.split()[-1]) if result else 0
        return count

    # ------------------------------------------------------------------
    # Validation Issues — CRUD
    # ------------------------------------------------------------------
    async def insert_issue(
        self,
        candidate_id: str,
        dataset_key: str,
        rule_name: str,
        severity: str = "WARNING",
        field_path: Optional[str] = None,
        expected_value: Optional[str] = None,
        actual_value: Optional[str] = None,
        message: Optional[str] = None,
    ) -> str:
        """Insert a validation issue and return its ID."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        issue_id = str(uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO validation_issues (
                    issue_id, candidate_id, dataset_key, rule_name,
                    severity, field_path, expected_value, actual_value, message
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                issue_id, candidate_id, dataset_key, rule_name,
                severity, field_path, expected_value, actual_value, message,
            )
        return issue_id

    async def list_issues(
        self,
        candidate_id: Optional[str] = None,
        dataset_key: Optional[str] = None,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List validation issues with optional filters."""
        pool = await self._get_pool()
        if not pool:
            return []
        async with pool.acquire() as conn:
            conditions = []
            params: list = []
            idx = 1

            if candidate_id:
                conditions.append(f"candidate_id = ${idx}")
                params.append(candidate_id)
                idx += 1
            if dataset_key:
                conditions.append(f"dataset_key = ${idx}")
                params.append(dataset_key)
                idx += 1
            if status:
                conditions.append(f"status = ${idx}")
                params.append(status)
                idx += 1
            if severity:
                conditions.append(f"severity = ${idx}")
                params.append(severity)
                idx += 1

            params.append(limit)
            where = " AND ".join(conditions) if conditions else "TRUE"
            rows = await conn.fetch(
                f"""
                SELECT * FROM validation_issues
                WHERE {where}
                ORDER BY created_at DESC LIMIT ${idx}
                """,
                *params,
            )
        return [dict(r) for r in rows]

    async def resolve_issue(self, issue_id: str, status: str = "RESOLVED") -> bool:
        """Resolve a validation issue."""
        pool = await self._get_pool()
        if not pool:
            return False
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE validation_issues
                SET status = $2, resolved_at = NOW()
                WHERE issue_id = $1
                """,
                issue_id, status,
            )
            return "UPDATE 1" in result

    async def count_open_errors(self, candidate_id: str) -> int:
        """Count open ERROR-severity issues for a candidate."""
        pool = await self._get_pool()
        if not pool:
            return 0
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) as cnt FROM validation_issues
                WHERE candidate_id = $1 AND severity = 'ERROR' AND status = 'OPEN'
                """,
                candidate_id,
            )
            return row["cnt"] if row else 0
