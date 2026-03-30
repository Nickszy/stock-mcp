# src/server/api/routes/commodities.py
"""Commodity asset REST API routes (gold, silver, crude oil, copper, industrial metals)."""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any
from src.server.utils.logger import logger
from src.server.core.use_cases import commodities as comm_uc
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/commodities", tags=["大宗商品 Commodities"])


@router.get("/gold", summary="黄金期货行情")
async def get_gold_price(
    days: int = Query(60, ge=1, le=500, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await comm_uc.get_commodity_price("AU0", days)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_gold_price: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/silver", summary="白银期货行情")
async def get_silver_price(
    days: int = Query(60, ge=1, le=500, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await comm_uc.get_commodity_price("AG0", days)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_silver_price: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/crude-oil", summary="原油期货行情(SC)")
async def get_crude_oil_price(
    days: int = Query(60, ge=1, le=500, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await comm_uc.get_commodity_price("SC0", days)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_crude_oil_price: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/copper", summary="铜期货行情")
async def get_copper_price(
    days: int = Query(60, ge=1, le=500, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await comm_uc.get_commodity_price("CU0", days)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_copper_price: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industrial-metals", summary="工业金属全景概览(铜+铝+锌+螺纹钢)")
async def get_industrial_metals_overview(
    days: int = Query(30, ge=1, le=500, description="各品种天数"),
) -> Dict[str, Any]:
    try:
        result = await comm_uc.get_industrial_metals_overview(days)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_industrial_metals_overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview", summary="大宗商品全景概览")
async def get_commodity_overview() -> Dict[str, Any]:
    try:
        result = await comm_uc.get_commodity_overview()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_commodity_overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
