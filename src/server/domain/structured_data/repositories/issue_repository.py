# src/server/domain/structured_data/repositories/issue_repository.py
"""Repository for approval_tasks and approval_actions tables.

Handles: approval workflow — create tasks, record actions, query pending reviews.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.server.utils.logger import logger


class IssueRepository:
    """Manages approval_tasks and approval_actions tables."""

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
        """Create approval_tasks and approval_actions tables."""
        pool = await self._get_pool()
        if not pool:
            logger.warning("IssueRepository: PostgreSQL not available")
            return False

        async with pool.acquire() as conn:
            # approval_tasks — records pending human review
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_tasks (
                    task_id       UUID PRIMARY KEY,
                    candidate_id  UUID NOT NULL,
                    dataset_key   TEXT NOT NULL,
                    business_key  TEXT NOT NULL,
                    reason        TEXT,
                    is_resolved   BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
                    resolved_at   TIMESTAMP
                )
            """)

            # approval_actions — audit trail for review decisions
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_actions (
                    action_id   UUID PRIMARY KEY,
                    task_id     UUID NOT NULL REFERENCES approval_tasks(task_id) ON DELETE CASCADE,
                    reviewer    TEXT NOT NULL,
                    action      TEXT NOT NULL DEFAULT 'COMMENT',
                    comment     TEXT,
                    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)

            # Indexes
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_approval_tasks_dataset
                ON approval_tasks(dataset_key, is_resolved)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_approval_tasks_candidate
                ON approval_tasks(candidate_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_approval_actions_task
                ON approval_actions(task_id)
            """)

        logger.info("✅ IssueRepository schema ensured")
        return True

    # ------------------------------------------------------------------
    # Approval Tasks
    # ------------------------------------------------------------------
    async def create_task(
        self,
        candidate_id: str,
        dataset_key: str,
        business_key: str,
        reason: Optional[str] = None,
    ) -> str:
        """Create an approval task and return its ID."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        task_id = str(uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO approval_tasks (task_id, candidate_id, dataset_key, business_key, reason)
                VALUES ($1, $2, $3, $4, $5)
                """,
                task_id, candidate_id, dataset_key, business_key, reason,
            )
        return task_id

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get an approval task by ID."""
        pool = await self._get_pool()
        if not pool:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM approval_tasks WHERE task_id = $1",
                task_id,
            )
            return dict(row) if row else None

    async def list_pending_tasks(
        self,
        dataset_key: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List unresolved approval tasks."""
        pool = await self._get_pool()
        if not pool:
            return []
        async with pool.acquire() as conn:
            if dataset_key:
                rows = await conn.fetch(
                    """
                    SELECT * FROM approval_tasks
                    WHERE dataset_key = $1 AND is_resolved = FALSE
                    ORDER BY created_at ASC LIMIT $2
                    """,
                    dataset_key, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM approval_tasks
                    WHERE is_resolved = FALSE
                    ORDER BY created_at ASC LIMIT $1
                    """,
                    limit,
                )
        return [dict(r) for r in rows]

    async def resolve_task(self, task_id: str) -> bool:
        """Mark a task as resolved."""
        pool = await self._get_pool()
        if not pool:
            return False
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE approval_tasks
                SET is_resolved = TRUE, resolved_at = NOW()
                WHERE task_id = $1
                """,
                task_id,
            )
            return "UPDATE 1" in result

    async def get_task_for_candidate(self, candidate_id: str) -> Optional[Dict[str, Any]]:
        """Get the active (unresolved) approval task for a candidate."""
        pool = await self._get_pool()
        if not pool:
            return None
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM approval_tasks
                WHERE candidate_id = $1 AND is_resolved = FALSE
                ORDER BY created_at DESC LIMIT 1
                """,
                candidate_id,
            )
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Approval Actions (Audit Trail)
    # ------------------------------------------------------------------
    async def record_action(
        self,
        task_id: str,
        reviewer: str,
        action: str = "COMMENT",
        comment: Optional[str] = None,
    ) -> str:
        """Record an approval action and return its ID."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        action_id = str(uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO approval_actions (action_id, task_id, reviewer, action, comment)
                VALUES ($1, $2, $3, $4, $5)
                """,
                action_id, task_id, reviewer, action, comment,
            )
        return action_id

    async def list_actions(self, task_id: str) -> List[Dict[str, Any]]:
        """List all actions for an approval task."""
        pool = await self._get_pool()
        if not pool:
            return []
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM approval_actions
                WHERE task_id = $1
                ORDER BY created_at ASC
                """,
                task_id,
            )
        return [dict(r) for r in rows]
