# src/server/api/routes/admin.py
"""Admin REST API -- Structured Data Approval Workbench.

Provides endpoints for the human-in-the-loop approval workflow:
- Dashboard stats
- List / detail pending approval tasks
- Approve / reject / override-publish / comment actions
- Field diff between candidate and current canonical

All endpoints delegate business logic to ApprovalService.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.server.domain.response_contract import rest_response
from src.server.utils.logger import logger
from .admin_template import ADMIN_HTML


# REST API router  (prefix /api/v1/admin)
router = APIRouter(prefix="/api/v1/admin", tags=["Admin -- Approval Workbench"])

# HTML workbench router  (no prefix — mounts at /admin)
html_router = APIRouter(tags=["Admin -- Approval Workbench"])


@html_router.get("/admin", response_class=HTMLResponse, include_in_schema=False)
async def admin_workbench() -> HTMLResponse:
    """Serve the Structured Data Approval Workbench UI."""
    return HTMLResponse(content=ADMIN_HTML)


# ---------------------------------------------------------------------------
# Module-level service reference (set by bootstrap via set_approval_service)
# ---------------------------------------------------------------------------

_approval_service = None
_board_catalog_service = None


def set_approval_service(service) -> None:
    """Inject the ApprovalService instance (called from bootstrap)."""
    global _approval_service
    _approval_service = service


def set_board_catalog_components(service=None) -> None:
    """Inject the board catalog service instance (called from bootstrap)."""
    global _board_catalog_service
    _board_catalog_service = service


def _require_service():
    """Return the ApprovalService or raise 503."""
    if _approval_service is None:
        raise HTTPException(
            status_code=503,
            detail="Admin service not initialized (PostgreSQL required)",
        )
    return _approval_service


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ApproveRequest(BaseModel):
    reviewer: str = "admin"
    comment: Optional[str] = None


class RejectRequest(BaseModel):
    reviewer: str = "admin"
    comment: Optional[str] = None


class OverridePublishRequest(BaseModel):
    reviewer: str = "admin"
    data_override: Optional[Dict[str, Any]] = None
    comment: Optional[str] = None


class CommentRequest(BaseModel):
    reviewer: str
    comment: str


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get(
    "/stats",
    summary="Dashboard statistics",
    description="Return pending task counts grouped by dataset.",
)
async def get_stats() -> Dict[str, Any]:
    """Return approval dashboard statistics."""
    svc = _require_service()
    stats = await svc.get_stats()
    return rest_response(data=stats)


# ---------------------------------------------------------------------------
# Pending tasks
# ---------------------------------------------------------------------------


@router.get(
    "/approval/pending",
    summary="List pending tasks",
    description="List all pending human-review approval tasks.",
)
async def list_pending_approvals(
    dataset_key: Optional[str] = Query(None, description="Filter by dataset"),
    limit: int = Query(50, description="Max results", ge=1, le=500),
) -> Dict[str, Any]:
    """List pending approval tasks."""
    svc = _require_service()
    tasks = await svc._issues.list_pending_tasks(dataset_key=dataset_key, limit=limit)
    return rest_response(data=tasks, total=len(tasks))


# ---------------------------------------------------------------------------
# Task detail and diff
# ---------------------------------------------------------------------------


@router.get(
    "/approval/{task_id}",
    summary="Task detail",
    description="Full task detail: candidate, field diff, validation issues, action history.",
)
async def get_task_detail(task_id: str) -> Dict[str, Any]:
    """Get full detail for an approval task."""
    svc = _require_service()
    try:
        detail = await svc.get_task_detail(task_id)
        return rest_response(data=detail)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get(
    "/approval/{task_id}/diff",
    summary="Field diff",
    description="Per-field diff between candidate normalized_data and current canonical.",
)
async def get_task_diff(task_id: str) -> Dict[str, Any]:
    """Get field-level diff between candidate and current canonical."""
    svc = _require_service()
    diff = await svc.get_field_diff(task_id)
    return rest_response(data=diff, total=len(diff))


@router.get(
    "/approval/{task_id}/actions",
    summary="Audit trail",
    description="Full audit trail of actions taken on this task.",
)
async def get_task_actions(task_id: str) -> Dict[str, Any]:
    """Get full audit trail for an approval task."""
    svc = _require_service()
    actions = await svc.get_actions(task_id)
    return rest_response(data=actions, total=len(actions))


# ---------------------------------------------------------------------------
# Approval actions
# ---------------------------------------------------------------------------


@router.post(
    "/approval/{task_id}/approve",
    summary="Approve",
    description="Approve the candidate and publish to canonical table.",
)
async def approve_task(task_id: str, body: ApproveRequest) -> Dict[str, Any]:
    """Approve a pending record and publish to canonical."""
    svc = _require_service()
    try:
        result = await svc.approve(task_id, reviewer=body.reviewer, comment=body.comment)
        return rest_response(data=result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Approve failed", task_id=task_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/approval/{task_id}/reject",
    summary="Reject",
    description="Reject the candidate. Task closed, candidate state changes to REJECTED.",
)
async def reject_task(task_id: str, body: RejectRequest) -> Dict[str, Any]:
    """Reject a pending record."""
    svc = _require_service()
    try:
        result = await svc.reject(task_id, reviewer=body.reviewer, comment=body.comment)
        return rest_response(data=result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Reject failed", task_id=task_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/approval/{task_id}/override-publish",
    summary="Override publish",
    description="Force publish with optional field overrides recorded in audit trail.",
)
async def override_publish_task(
    task_id: str, body: OverridePublishRequest
) -> Dict[str, Any]:
    """Override publish with optional data edits."""
    svc = _require_service()
    try:
        result = await svc.override_publish(
            task_id,
            reviewer=body.reviewer,
            data_override=body.data_override,
            comment=body.comment,
        )
        return rest_response(data=result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Override publish failed", task_id=task_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/approval/{task_id}/comment",
    summary="Add comment",
    description="Record an audit comment without changing task or candidate state.",
)
async def add_comment(task_id: str, body: CommentRequest) -> Dict[str, Any]:
    """Add an audit comment without changing task state."""
    svc = _require_service()
    try:
        result = await svc.comment(task_id, reviewer=body.reviewer, comment=body.comment)
        return rest_response(data=result)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Comment failed", task_id=task_id, error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Board catalog admin
# ---------------------------------------------------------------------------


@router.post(
    "/board-catalog/refresh",
    summary="Refresh board catalog",
    description="Trigger manual refresh of persisted board catalog from akshare.",
)
async def refresh_board_catalog() -> Dict[str, Any]:
    """Refresh board catalog into PostgreSQL."""
    if _board_catalog_service is None:
        raise HTTPException(
            status_code=503,
            detail="Board catalog service not initialized (PostgreSQL required)",
        )
    try:
        result = await _board_catalog_service.refresh_catalog()
        return rest_response(data=result)
    except Exception as exc:
        logger.error("Board catalog refresh failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
