# src/server/api/routes/hk_market.py
"""Hong Kong market REST API routes."""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from src.server.utils.logger import logger
from src.server.core.use_cases import hk_market as hk_uc
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/hk", tags=["港股 Hong Kong"])


@router.get("/spot", summary="港股全市场实时行情")
async def get_hk_market_spot() -> Dict[str, Any]:
    try:
        result = await hk_uc.get_hk_market_spot()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_hk_market_spot: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hot-rank", summary="港股热度排行")
async def get_hk_hot_rank() -> Dict[str, Any]:
    try:
        result = await hk_uc.get_hk_hot_rank()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_hk_hot_rank: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/main-board", summary="港股主板实时行情")
async def get_hk_main_board() -> Dict[str, Any]:
    try:
        result = await hk_uc.get_hk_main_board()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_hk_main_board: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview", summary="港股市场概览")
async def get_hk_market_overview() -> Dict[str, Any]:
    try:
        result = await hk_uc.get_hk_market_overview()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_hk_market_overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
