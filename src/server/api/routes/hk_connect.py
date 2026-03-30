# src/server/api/routes/hk_connect.py
"""Hong Kong Connect / southbound flow REST API routes."""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any
from src.server.utils.logger import logger
from src.server.core.use_cases import hk_connect as hc_uc
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/hk-connect", tags=["港股通 HK Connect"])


@router.get("/components", summary="港股通成分股")
async def get_hk_connect_components() -> Dict[str, Any]:
    try:
        result = await hc_uc.get_hk_connect_components()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_hk_connect_components: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fund-flow", summary="沪深港通资金流汇总")
async def get_hsgt_fund_flow_summary() -> Dict[str, Any]:
    try:
        result = await hc_uc.get_hsgt_fund_flow_summary()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_hsgt_fund_flow_summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hold-stock", summary="港股通持股排行")
async def get_hsgt_hold_stock(
    market: str = Query("港股通", description="市场"),
    indicator: str = Query("5日排行", description="排行周期"),
) -> Dict[str, Any]:
    try:
        result = await hc_uc.get_hsgt_hold_stock(market=market, indicator=indicator)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_hsgt_hold_stock: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview", summary="港股通概览")
async def get_hk_connect_overview() -> Dict[str, Any]:
    try:
        result = await hc_uc.get_hk_connect_overview()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_hk_connect_overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
