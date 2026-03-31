# src/server/api/routes/watchlist.py
"""Watchlist REST API routes."""

from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/watchlists", tags=["自选股 Watchlist"])

# Module-level service injection (set from bootstrap)
_watchlist_service = None


def set_watchlist_components(service=None):
    global _watchlist_service
    _watchlist_service = service


def _require_service():
    if _watchlist_service is None:
        raise HTTPException(status_code=503, detail="Watchlist service not initialized")
    return _watchlist_service


class CreateWatchlistRequest(BaseModel):
    user_id: str
    name: str
    description: Optional[str] = None


class AddPositionRequest(BaseModel):
    ticker: str
    quantity: float
    average_cost: float
    notes: Optional[str] = None
    tags: Optional[list[str]] = None


@router.post("", summary="创建自选股组合")
async def create_watchlist(req: CreateWatchlistRequest) -> Dict[str, Any]:
    service = _require_service()
    try:
        watchlist = await service.create_watchlist(
            user_id=req.user_id,
            name=req.name,
            description=req.description,
        )
        return rest_response(data=watchlist.model_dump(mode="json"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", summary="列出用户自选股组合")
async def list_watchlists(
    user_id: str = Query(..., description="用户ID"),
) -> Dict[str, Any]:
    service = _require_service()
    try:
        watchlists = await service.list_watchlists(user_id)
        return rest_response(
            data=[w.model_dump(mode="json") for w in watchlists],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{watchlist_id}", summary="获取自选股组合详情")
async def get_watchlist(
    watchlist_id: str,
    user_id: str = Query(..., description="用户ID"),
) -> Dict[str, Any]:
    service = _require_service()
    try:
        watchlist = await service.get_watchlist(user_id, watchlist_id)
        if watchlist is None:
            raise HTTPException(status_code=404, detail="Watchlist not found")
        return rest_response(data=watchlist.model_dump(mode="json"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{watchlist_id}/positions", summary="添加持仓")
async def add_position(
    watchlist_id: str,
    req: AddPositionRequest,
    user_id: str = Query(..., description="用户ID"),
) -> Dict[str, Any]:
    service = _require_service()
    try:
        watchlist = await service.add_position(
            user_id=user_id,
            watchlist_id=watchlist_id,
            ticker=req.ticker,
            quantity=req.quantity,
            average_cost=req.average_cost,
            notes=req.notes,
            tags=req.tags,
        )
        return rest_response(data=watchlist.model_dump(mode="json"))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{watchlist_id}/positions/{ticker}", summary="移除持仓")
async def remove_position(
    watchlist_id: str,
    ticker: str,
    user_id: str = Query(..., description="用户ID"),
) -> Dict[str, Any]:
    service = _require_service()
    try:
        removed = await service.remove_position(user_id, watchlist_id, ticker)
        if not removed:
            raise HTTPException(status_code=404, detail="Position not found")
        return rest_response(data={"removed": True})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
