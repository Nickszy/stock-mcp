# src/server/domain/structured_data/approval_service.py
"""Approval Service — encapsulates approve/reject/override business logic.

Extracts approval workflow logic from route handlers into a domain service
so that both REST and MCP can share the same business rules.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger

from .enums import ApprovalAction, PipelineState
from .repositories.candidate_repository import CandidateRepository
from .repositories.canonical_repository import CanonicalRepository
from .repositories.issue_repository import IssueRepository


class ApprovalService:
    """Coordinates approval workflow: approve / reject / override / detail."""

    def __init__(
        self,
        candidate_repo: CandidateRepository,
        canonical_repo: CanonicalRepository,
        issue_repo: IssueRepository,
    ):
        self._candidates = candidate_repo
        self._canonical = canonical_repo
        self._issues = issue_repo

    # ------------------------------------------------------------------
    # Core actions
    # ------------------------------------------------------------------

    async def approve(
        self,
        task_id: str,
        reviewer: str = "admin",
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Approve a pending record and publish to canonical.

        Steps:
        1. Validate task is unresolved
        2. Record APPROVE action (audit trail)
        3. Transition candidate → APPROVED
        4. Publish candidate data to canonical table
        5. Transition candidate → PUBLISHED
        6. Mark task as resolved
        """
        task = await self._require_unresolved_task(task_id)

        # Record audit action
        await self._issues.record_action(
            task_id, reviewer, ApprovalAction.APPROVE.value, comment,
        )

        # Transition and publish
        candidate_id = str(task["candidate_id"])
        ok = await self._candidates.transition_state(
            candidate_id, PipelineState.APPROVED.value,
        )
        if not ok:
            raise ValueError(
                f"Failed to transition candidate {candidate_id} to APPROVED "
                f"(concurrent modification?)"
            )

        candidate = await self._candidates.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(
                f"Candidate {candidate_id} not found — cannot publish"
            )

        data = _parse_jsonb(candidate.get("normalized_data", {}))
        canonical_id = await self._canonical.publish(
            candidate_id=candidate_id,
            dataset_key=str(task["dataset_key"]),
            business_key=str(task["business_key"]),
            data=data,
            source="approved",
        )
        ok = await self._candidates.transition_state(
            candidate_id, PipelineState.PUBLISHED.value,
        )
        if not ok:
            logger.warning(
                "Failed to transition to PUBLISHED after canonical publish",
                candidate_id=candidate_id,
            )
        # Supersede older candidates
        await self._candidates.mark_superseded(
            dataset_key=str(task["dataset_key"]),
            business_key=str(task["business_key"]),
            except_candidate_id=candidate_id,
        )

        await self._issues.resolve_task(task_id)

        logger.info(
            "Approval completed",
            task_id=task_id,
            reviewer=reviewer,
            canonical_id=canonical_id,
        )
        return {
            "task_id": task_id,
            "status": "approved",
            "canonical_id": canonical_id,
        }

    async def reject(
        self,
        task_id: str,
        reviewer: str = "admin",
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Reject a pending record.

        Steps:
        1. Validate task is unresolved
        2. Record REJECT action (audit trail)
        3. Transition candidate → REJECTED
        4. Mark task as resolved
        """
        task = await self._require_unresolved_task(task_id)

        await self._issues.record_action(
            task_id, reviewer, ApprovalAction.REJECT.value, comment,
        )

        candidate_id = str(task["candidate_id"])
        await self._candidates.transition_state(
            candidate_id, PipelineState.REJECTED.value,
        )
        await self._issues.resolve_task(task_id)

        logger.info("Rejection completed", task_id=task_id, reviewer=reviewer)
        return {"task_id": task_id, "status": "rejected"}

    async def override_publish(
        self,
        task_id: str,
        reviewer: str = "admin",
        data_override: Optional[Dict[str, Any]] = None,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Override publish — force publish with optional data edits.

        Allows a reviewer to modify field values before publishing.
        The override is recorded in the audit trail for traceability.
        """
        task = await self._require_unresolved_task(task_id)

        candidate_id = str(task["candidate_id"])
        candidate = await self._candidates.get_candidate(candidate_id)

        # Use override data if provided, otherwise use original candidate data
        if data_override is not None:
            publish_data = data_override
        elif candidate:
            publish_data = _parse_jsonb(candidate.get("normalized_data", {}))
        else:
            raise ValueError(
                f"Candidate {candidate_id} not found — cannot override publish"
            )

        # Include override detail in audit comment for traceability
        audit_comment = comment or "Override publish"
        if data_override:
            import json as _json
            audit_comment += f" | data_override: {_json.dumps(data_override, default=str)}"

        await self._issues.record_action(
            task_id,
            reviewer,
            ApprovalAction.OVERRIDE_PUBLISH.value,
            audit_comment,
        )

        # Transition: PENDING_REVIEW → APPROVED → PUBLISHED
        ok = await self._candidates.transition_state(
            candidate_id, PipelineState.APPROVED.value,
        )
        if not ok:
            raise ValueError(
                f"Failed to transition candidate {candidate_id} to APPROVED"
            )

        canonical_id = await self._canonical.publish(
            candidate_id=candidate_id,
            dataset_key=str(task["dataset_key"]),
            business_key=str(task["business_key"]),
            data=publish_data,
            source="override",
        )

        await self._candidates.transition_state(
            candidate_id, PipelineState.PUBLISHED.value,
        )
        await self._candidates.mark_superseded(
            dataset_key=str(task["dataset_key"]),
            business_key=str(task["business_key"]),
            except_candidate_id=candidate_id,
        )
        await self._issues.resolve_task(task_id)

        logger.info(
            "Override publish completed",
            task_id=task_id,
            reviewer=reviewer,
            canonical_id=canonical_id,
        )
        return {
            "task_id": task_id,
            "status": "override_published",
            "canonical_id": canonical_id,
        }

    # ------------------------------------------------------------------
    # Detail / Query
    # ------------------------------------------------------------------

    async def get_task_detail(self, task_id: str) -> Dict[str, Any]:
        """Get complete task detail including candidate, diff, issues, actions.

        Returns a rich object suitable for the admin UI:
        {
            task: {...},
            candidate: {...},
            canonical_current: {...} | null,
            field_diff: [{field, old, new, changed}, ...],
            validation_issues: [...],
            actions: [...],
        }
        """
        task = await self._issues.get_task(task_id)
        if not task:
            raise KeyError(f"Approval task not found: {task_id}")

        candidate_id = str(task["candidate_id"])
        candidate = await self._candidates.get_candidate(candidate_id)

        # Get current canonical for diff
        canonical_current = await self._canonical.get_current(
            str(task["dataset_key"]),
            str(task["business_key"]),
        )

        # Compute field diff
        candidate_data = _parse_jsonb(
            candidate.get("normalized_data", {}) if candidate else {},
        )
        canonical_data = _parse_jsonb(
            canonical_current.get("data", {}) if canonical_current else {},
        )
        field_diff = _compute_field_diff(canonical_data, candidate_data)

        # Validation issues
        validation_issues = await self._candidates.list_issues(
            candidate_id=candidate_id,
        ) if candidate else []

        # Action history
        actions = await self._issues.list_actions(task_id)

        return {
            "task": _serialize_row(task),
            "candidate": _serialize_row(candidate) if candidate else None,
            "canonical_current": _serialize_row(canonical_current) if canonical_current else None,
            "field_diff": field_diff,
            "validation_issues": [_serialize_row(i) for i in validation_issues],
            "actions": [_serialize_row(a) for a in actions],
        }

    async def get_actions(self, task_id: str) -> List[Dict[str, Any]]:
        """Get audit trail for a task."""
        actions = await self._issues.list_actions(task_id)
        return [_serialize_row(a) for a in actions]

    async def get_field_diff(self, task_id: str) -> List[Dict[str, Any]]:
        """Compute field diff between candidate and current canonical."""
        task = await self._issues.get_task(task_id)
        if not task:
            return []

        candidate = await self._candidates.get_candidate(str(task["candidate_id"]))
        canonical = await self._canonical.get_current(
            str(task["dataset_key"]),
            str(task["business_key"]),
        )

        candidate_data = _parse_jsonb(
            candidate.get("normalized_data", {}) if candidate else {},
        )
        canonical_data = _parse_jsonb(
            canonical.get("data", {}) if canonical else {},
        )
        return _compute_field_diff(canonical_data, candidate_data)

    async def get_stats(self) -> Dict[str, Any]:
        """Dashboard statistics."""
        pending_tasks = await self._issues.list_pending_tasks(limit=1000)
        pending_count = len(pending_tasks)

        # Group by dataset_key
        by_dataset: Dict[str, int] = {}
        for t in pending_tasks:
            dk = t.get("dataset_key", "unknown")
            by_dataset[dk] = by_dataset.get(dk, 0) + 1

        return {
            "pending_count": pending_count,
            "pending_by_dataset": by_dataset,
        }

    async def comment(
        self,
        task_id: str,
        reviewer: str,
        comment: str,
    ) -> Dict[str, Any]:
        """Add an audit comment without changing task or candidate state."""
        task = await self._require_unresolved_task(task_id)
        action_id = await self._issues.record_action(
            task_id, reviewer, ApprovalAction.COMMENT.value, comment,
        )
        logger.info("Comment recorded", task_id=task_id, reviewer=reviewer)
        return {"task_id": task_id, "action_id": action_id, "status": "commented"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _require_unresolved_task(self, task_id: str) -> Dict[str, Any]:
        """Get task and validate it's unresolved."""
        task = await self._issues.get_task(task_id)
        if not task:
            raise KeyError(f"Approval task not found: {task_id}")
        if task.get("is_resolved"):
            raise ValueError(f"Task already resolved: {task_id}")
        return task


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _parse_jsonb(value: Any) -> Dict[str, Any]:
    """Parse JSONB value which may be a string or dict."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(value, dict):
        return value
    return {}


def _compute_field_diff(
    old_data: Dict[str, Any],
    new_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Compute per-field diff between old and new data.

    Returns a list of {field, old_value, new_value, changed} dicts.
    """
    all_keys = sorted(set(list(old_data.keys()) + list(new_data.keys())))
    diff: List[Dict[str, Any]] = []
    for key in all_keys:
        old_val = old_data.get(key)
        new_val = new_data.get(key)
        diff.append({
            "field": key,
            "old_value": old_val,
            "new_value": new_val,
            "changed": old_val != new_val,
        })
    return diff


def _serialize_row(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Convert asyncpg row dict values to JSON-serializable form."""
    if row is None:
        return None
    import uuid as _uuid
    result = {}
    for k, v in row.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
        elif isinstance(v, _uuid.UUID):
            result[k] = str(v)
        elif isinstance(v, bytes):
            result[k] = v.decode("utf-8", errors="replace")
        else:
            result[k] = v
    return result
