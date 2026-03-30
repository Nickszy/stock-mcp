# src/server/api/routes/structured_data.py
"""Structured Data Platform API routes.

Provides RESTful HTTP endpoints for the structured data pipeline:
- Trigger pipeline refresh for a dataset
- Query canonical data
- Admin: approval workflow, pipeline status
"""

from fastapi import APIRouter, HTTPException, Query, status
from typing import Dict, Any, Optional

from src.server.utils.logger import logger
from src.server.core.use_cases import structured_data as sd_use_cases
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/structured-data", tags=["结构化数据 Structured Data"])


# ---------------------------------------------------------------------------
# Dataset Management
# ---------------------------------------------------------------------------

@router.get(
    "/datasets",
    summary="列出所有数据维度",
    description="列出所有可用的结构化数据维度及其配置",
)
async def list_datasets(
    active_only: bool = Query(True, description="只返回活跃的数据维度"),
) -> Dict[str, Any]:
    """List all registered datasets."""
    datasets = await sd_use_cases.list_datasets(active_only=active_only)
    return rest_response(data=datasets, total=len(datasets))


@router.get(
    "/datasets/{dataset_key}",
    summary="获取数据维度详情",
    description="获取指定数据维度的详细配置信息",
)
async def get_dataset_info(dataset_key: str) -> Dict[str, Any]:
    """Get detailed info about a specific dataset."""
    try:
        info = await sd_use_cases.get_dataset_info(dataset_key)
        return rest_response(data=info)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------------------------
# Pipeline Operations
# ---------------------------------------------------------------------------

@router.post(
    "/datasets/{dataset_key}/refresh",
    summary="触发数据刷新",
    description="""
    触发指定数据维度的刷新任务。

    **流程:**
    1. 创建 Job
    2. 从数据源抓取原始数据
    3. 标准化 → 校验 → 自动发布/进入审批
    """,
)
async def refresh_dataset(
    dataset_key: str,
    symbol: Optional[str] = Query(None, description="标的代码 (格式: EXCHANGE:SYMBOL)"),
    source: Optional[str] = Query(None, description="指定数据源 (akshare/tushare)"),
    force: bool = Query(False, description="强制刷新，忽略 TTL"),
) -> Dict[str, Any]:
    """Trigger a refresh for a dataset."""
    try:
        runner = _get_runner()
        if runner is None:
            raise HTTPException(
                status_code=503,
                detail="Structured data subsystem not initialized (PostgreSQL required)",
            )

        result = await sd_use_cases.refresh_dataset(
            dataset_key=dataset_key,
            business_key=symbol,
            source=source,
            force=force,
            runner=runner,
        )
        return rest_response(data=result)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Refresh failed", dataset_key=dataset_key, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Refresh failed: {str(e)}",
        )


@router.post(
    "/datasets/{dataset_key}/process",
    summary="执行管道处理",
    description="""
    对指定 Job 的原始数据执行完整的管道处理:
    normalize → validate → auto_publish / pending_review

    通常在 refresh 完成后自动调用，也可手动触发。
    """,
)
async def process_dataset(
    dataset_key: str,
    job_id: str = Query(..., description="要处理的 Job ID"),
) -> Dict[str, Any]:
    """Process a completed job through the pipeline."""
    try:
        orchestrator = _get_orchestrator()
        if orchestrator is None:
            raise HTTPException(
                status_code=503,
                detail="Structured data subsystem not initialized",
            )

        result = await orchestrator.process_job(job_id=job_id, dataset_key=dataset_key)
        return rest_response(data=result)
    except Exception as e:
        logger.error("Process failed", dataset_key=dataset_key, job_id=job_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Canonical Data Query
# ---------------------------------------------------------------------------

@router.get(
    "/canonical/{dataset_key}",
    summary="查询 Canonical 数据",
    description="""
    查询已发布的 Canonical 数据（最高质量的结构化数据）。

    这是下游消费者（投研 Web、AI 问答等）读取数据的主要入口。
    """,
)
async def get_canonical_data(
    dataset_key: str,
    business_key: Optional[str] = Query(None, description="业务主键"),
    limit: int = Query(50, description="返回数量"),
) -> Dict[str, Any]:
    """Query published canonical data."""
    try:
        canonical_repo = _get_canonical_repo()
        if canonical_repo is None:
            raise HTTPException(
                status_code=503,
                detail="Structured data subsystem not initialized",
            )

        if business_key:
            record = await canonical_repo.get_current(dataset_key, business_key)
            if not record:
                raise HTTPException(status_code=404, detail="No canonical data found")
            # Parse the JSONB data field
            data = record.get("data", {})
            if isinstance(data, str):
                import json
                data = json.loads(data)
            return rest_response(data=data, meta={
                "dataset_key": dataset_key,
                "business_key": business_key,
                "version": record.get("version"),
                "published_at": str(record.get("published_at", "")),
                "source": record.get("source"),
            })
        else:
            records = await canonical_repo.list_by_dataset(dataset_key, limit=limit)
            items = []
            for r in records:
                d = r.get("data", {})
                if isinstance(d, str):
                    import json
                    d = json.loads(d)
                items.append({
                    "business_key": r.get("business_key"),
                    "version": r.get("version"),
                    "source": r.get("source"),
                    "published_at": str(r.get("published_at", "")),
                    "data": d,
                })
            return rest_response(data=items, total=len(items))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Canonical query failed", dataset_key=dataset_key, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Financial Statements — convenience endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/financial-statements/{symbol}",
    summary="查询 Canonical 财报数据",
    description="""
    查询指定股票的 Canonical 财报三表数据。

    如果 canonical 表中不存在，会自动触发一次 refresh + process 然后返回。
    """,
)
async def get_financial_statements_canonical(
    symbol: str,
) -> Dict[str, Any]:
    """Get canonical financial statements for a symbol."""
    try:
        canonical_repo = _get_canonical_repo()
        if canonical_repo is None:
            raise HTTPException(
                status_code=503,
                detail="Structured data subsystem not initialized",
            )

        # Build business key pattern
        # The symbol may be in various formats — normalize to find matches
        import re
        clean = re.sub(r'^(SSE|SZSE|BSE):', '', symbol)

        # Try common exchange prefixes
        for exchange in ["SSE", "SZSE", "BSE"]:
            biz_key_prefix = f"{exchange}:{clean}:"
            records = await canonical_repo.list_by_dataset("financial_statements", limit=10)
            for r in records:
                bk = r.get("business_key", "")
                if bk.startswith(biz_key_prefix):
                    d = r.get("data", {})
                    if isinstance(d, str):
                        import json
                        d = json.loads(d)
                    return rest_response(data=d, meta={
                        "dataset_key": "financial_statements",
                        "business_key": bk,
                        "version": r.get("version"),
                        "published_at": str(r.get("published_at", "")),
                    })

        # No canonical data found — try to trigger refresh
        runner = _get_runner()
        if runner is None:
            raise HTTPException(status_code=404, detail="No canonical data found and cannot refresh")

        refresh_result = await sd_use_cases.refresh_dataset(
            dataset_key="financial_statements",
            business_key=symbol,
            runner=runner,
        )

        # After refresh, try to process and query again
        if refresh_result.get("status") in ("completed", "partial"):
            job_id = refresh_result.get("job_id")
            if job_id:
                orchestrator = _get_orchestrator()
                if orchestrator:
                    await orchestrator.process_job(job_id=job_id, dataset_key="financial_statements")

            # Query again
            for exchange in ["SSE", "SZSE", "BSE"]:
                biz_key_prefix = f"{exchange}:{clean}:"
                records = await canonical_repo.list_by_dataset("financial_statements", limit=10)
                for r in records:
                    bk = r.get("business_key", "")
                    if bk.startswith(biz_key_prefix):
                        d = r.get("data", {})
                        if isinstance(d, str):
                            import json
                            d = json.loads(d)
                        return rest_response(data=d, meta={
                            "dataset_key": "financial_statements",
                            "business_key": bk,
                            "version": r.get("version"),
                            "published_at": str(r.get("published_at", "")),
                        })

        raise HTTPException(status_code=404, detail="No canonical financial data found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Financial statements canonical query failed", symbol=symbol, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Approval / Admin
# ---------------------------------------------------------------------------

@router.get(
    "/approval/pending",
    summary="查询待审批记录",
    description="查询所有待人工审批的记录",
)
async def list_pending_approvals(
    dataset_key: Optional[str] = Query(None, description="按数据维度过滤"),
    limit: int = Query(50, description="返回数量"),
) -> Dict[str, Any]:
    """List pending approval tasks."""
    issue_repo = _get_issue_repo()
    if issue_repo is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")

    tasks = await issue_repo.list_pending_tasks(dataset_key=dataset_key, limit=limit)
    return rest_response(data=tasks, total=len(tasks))


@router.get(
    "/approval/{task_id}",
    summary="审批任务详情",
    description="获取审批任务详情，包含候选数据、字段差异、校验问题及操作历史",
)
async def get_task_detail(task_id: str) -> Dict[str, Any]:
    """Get full detail for an approval task."""
    svc = _get_approval_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")
    try:
        detail = await svc.get_task_detail(task_id)
        return rest_response(data=detail)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post(
    "/approval/{task_id}/approve",
    summary="批准记录",
    description="批准一条待审批记录，将其发布到 canonical 表",
)
async def approve_task(
    task_id: str,
    reviewer: str = Query("admin", description="审批人"),
    comment: Optional[str] = Query(None, description="审批备注"),
) -> Dict[str, Any]:
    """Approve a pending record."""
    svc = _get_approval_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")
    try:
        result = await svc.approve(task_id, reviewer=reviewer, comment=comment)
        return rest_response(data=result)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/approval/{task_id}/reject",
    summary="驳回记录",
    description="驳回一条待审批记录",
)
async def reject_task(
    task_id: str,
    reviewer: str = Query("admin", description="审批人"),
    comment: Optional[str] = Query(None, description="驳回原因"),
) -> Dict[str, Any]:
    """Reject a pending record."""
    svc = _get_approval_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")
    try:
        result = await svc.reject(task_id, reviewer=reviewer, comment=comment)
        return rest_response(data=result)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/approval/{task_id}/override",
    summary="覆盖发布",
    description="允许覆盖字段值后强制发布到 canonical 表",
)
async def override_publish_task(
    task_id: str,
    reviewer: str = Query("admin", description="审批人"),
    comment: Optional[str] = Query(None, description="覆盖说明"),
    data_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Override publish with optional data edits."""
    svc = _get_approval_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")
    try:
        result = await svc.override_publish(
            task_id, reviewer=reviewer, data_override=data_override, comment=comment,
        )
        return rest_response(data=result)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/approval/{task_id}/actions",
    summary="审计轨迹",
    description="获取审批任务的完整操作审计记录",
)
async def get_task_actions(task_id: str) -> Dict[str, Any]:
    """Get audit trail for an approval task."""
    svc = _get_approval_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")
    actions = await svc.get_actions(task_id)
    return rest_response(data=actions, total=len(actions))


@router.get(
    "/approval/{task_id}/diff",
    summary="字段差异",
    description="获取候选数据与当前 canonical 数据的字段级差异",
)
async def get_task_diff(task_id: str) -> Dict[str, Any]:
    """Get field-level diff between candidate and current canonical."""
    svc = _get_approval_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")
    diff = await svc.get_field_diff(task_id)
    return rest_response(data=diff, total=len(diff))


@router.get(
    "/stats",
    summary="仪表板统计",
    description="获取审批任务总览统计（待审批数量、按维度分组）",
)
async def get_stats() -> Dict[str, Any]:
    """Dashboard statistics."""
    svc = _get_approval_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")
    stats = await svc.get_stats()
    return rest_response(data=stats)


@router.get(
    "/candidates/{candidate_id}",
    summary="候选记录详情",
    description="获取指定候选记录的详情",
)
async def get_candidate(candidate_id: str) -> Dict[str, Any]:
    """Get candidate record detail."""
    candidate_repo = _get_candidate_repo()
    if candidate_repo is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")
    record = await candidate_repo.get_candidate(candidate_id)
    if not record:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return rest_response(data=record)


# ---------------------------------------------------------------------------
# Pipeline Status & Jobs
# ---------------------------------------------------------------------------

@router.get(
    "/jobs",
    summary="查询 Job 列表",
    description="查询数据刷新任务列表",
)
async def list_jobs(
    dataset_key: Optional[str] = Query(None, description="按数据维度过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(50, description="返回数量"),
) -> Dict[str, Any]:
    """List dataset jobs."""
    raw_repo = _get_raw_repo()
    if raw_repo is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")

    jobs = await raw_repo.list_jobs(dataset_key=dataset_key, status=status, limit=limit)
    return rest_response(data=jobs, total=len(jobs))


@router.get(
    "/jobs/{job_id}",
    summary="查询 Job 详情",
)
async def get_job(job_id: str) -> Dict[str, Any]:
    """Get job details."""
    raw_repo = _get_raw_repo()
    if raw_repo is None:
        raise HTTPException(status_code=503, detail="Structured data subsystem not initialized")

    job = await raw_repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return rest_response(data=job)


# ---------------------------------------------------------------------------
# Helpers — get initialized components
# ---------------------------------------------------------------------------

_runner_instance = None
_orchestrator_instance = None
_approval_service_instance = None
_publish_service_instance = None


def set_structured_data_components(runner=None, orchestrator=None, approval_service=None, publish_service=None):
    """Called during init to store references."""
    global _runner_instance, _orchestrator_instance, _approval_service_instance, _publish_service_instance
    _runner_instance = runner
    _orchestrator_instance = orchestrator
    _approval_service_instance = approval_service
    _publish_service_instance = publish_service


def _get_runner():
    return _runner_instance


def _get_orchestrator():
    return _orchestrator_instance


def _get_approval_service():
    return _approval_service_instance


def _get_publish_service():
    return _publish_service_instance


def _get_raw_repo():
    runner = _get_runner()
    return runner._raw_repo if runner else None


def _get_candidate_repo():
    orchestrator = _get_orchestrator()
    return orchestrator._candidate_repo if orchestrator else None


def _get_canonical_repo():
    orchestrator = _get_orchestrator()
    return orchestrator._canonical_repo if orchestrator else None


def _get_issue_repo():
    orchestrator = _get_orchestrator()
    return orchestrator._issue_repo if orchestrator else None
