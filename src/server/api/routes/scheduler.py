# src/server/api/routes/scheduler.py
"""Scheduler REST API routes."""

from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/scheduler", tags=["定时任务 Scheduler"])

# Module-level service injection (set from bootstrap)
_scheduler_service = None
_scheduler_runner = None
_scheduler_engine = None
_scheduler_repo = None


def set_scheduler_components(
    service=None,
    runner=None,
    engine=None,
    repo=None,
):
    global _scheduler_service, _scheduler_runner, _scheduler_engine, _scheduler_repo
    _scheduler_service = service
    _scheduler_runner = runner
    _scheduler_engine = engine
    _scheduler_repo = repo


def _require_service():
    if _scheduler_service is None:
        raise HTTPException(status_code=503, detail="Scheduler service not initialized")
    return _scheduler_service


def _require_runner():
    if _scheduler_runner is None:
        raise HTTPException(status_code=503, detail="Scheduler runner not initialized")
    return _scheduler_runner


class CreateJobRequest(BaseModel):
    user_id: str
    name: str
    watchlist_id: str
    schedule_type: str = "daily"
    schedule_value: str = "09:00"
    analysis_types: Optional[list[str]] = None


@router.post("/jobs", summary="创建定时分析任务")
async def create_job(req: CreateJobRequest) -> Dict[str, Any]:
    service = _require_service()
    try:
        from src.server.domain.scheduler.models import ScheduleType
        job = await service.create_job(
            user_id=req.user_id,
            name=req.name,
            watchlist_id=req.watchlist_id,
            schedule_type=ScheduleType(req.schedule_type),
            schedule_value=req.schedule_value,
            analysis_types=req.analysis_types,
        )
        # Sync to engine if available
        if _scheduler_engine:
            await _scheduler_engine.sync_job(job)
        return rest_response(data=job.model_dump(mode="json"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs", summary="列出用户的定时任务")
async def list_jobs(
    user_id: str = Query(..., description="用户ID"),
) -> Dict[str, Any]:
    service = _require_service()
    try:
        jobs = await service.list_jobs(user_id)
        return rest_response(
            data=[j.model_dump(mode="json") for j in jobs],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", summary="获取任务详情")
async def get_job(
    job_id: str,
    user_id: str = Query(..., description="用户ID"),
) -> Dict[str, Any]:
    service = _require_service()
    try:
        job = await service.get_job(user_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return rest_response(data=job.model_dump(mode="json"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/run", summary="手动执行一次任务")
async def run_job(
    job_id: str,
    user_id: str = Query(..., description="用户ID"),
) -> Dict[str, Any]:
    service = _require_service()
    runner = _require_runner()
    try:
        job = await service.get_job(user_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        run = await runner.run_job(job)
        return rest_response(data=run.model_dump(mode="json"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/enable", summary="启用任务")
async def enable_job(
    job_id: str,
    user_id: str = Query(..., description="用户ID"),
) -> Dict[str, Any]:
    service = _require_service()
    try:
        job = await service.enable_job(user_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if _scheduler_engine:
            await _scheduler_engine.sync_job(job)
        return rest_response(data=job.model_dump(mode="json"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/jobs/{job_id}/disable", summary="禁用任务")
async def disable_job(
    job_id: str,
    user_id: str = Query(..., description="用户ID"),
) -> Dict[str, Any]:
    service = _require_service()
    try:
        job = await service.disable_job(user_id, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if _scheduler_engine:
            await _scheduler_engine.remove_job(job_id)
        return rest_response(data=job.model_dump(mode="json"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}/runs", summary="获取任务执行历史")
async def list_runs(
    job_id: str,
    limit: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    service = _require_service()
    try:
        runs = await service.list_runs(job_id, limit=limit)
        return rest_response(
            data=[r.model_dump(mode="json") for r in runs],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}", summary="获取单次执行结果")
async def get_run(
    run_id: str,
    job_id: str = Query(..., description="所属任务ID"),
) -> Dict[str, Any]:
    service = _require_service()
    try:
        run = await service.get_run(job_id, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return rest_response(data=run.model_dump(mode="json"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
