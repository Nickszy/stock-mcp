# src/server/api/routes/fixed_income.py
"""Fixed income / bond research REST API routes."""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any
from src.server.utils.logger import logger
from src.server.core.use_cases import fixed_income as fi_uc
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/fixed-income", tags=["固定收益 Fixed Income"])


@router.get("/bond-yield", summary="中国债券收益率曲线")
async def get_cn_bond_yield(
    start_date: str = Query("", description="起始日期(YYYYMMDD)"),
    end_date: str = Query("", description="截止日期(YYYYMMDD)"),
) -> Dict[str, Any]:
    try:
        result = await fi_uc.get_bond_yield_curve(start_date=start_date, end_date=end_date)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_bond_yield: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/convertible-bonds", summary="可转债实时行情列表")
async def get_cn_convertible_bonds(
    bond_code: str = Query("", description="债券代码(可选筛选)"),
) -> Dict[str, Any]:
    try:
        result = await fi_uc.get_convertible_bonds(bond_code=bond_code)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_convertible_bonds: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/convertible-bond-history", summary="可转债历史K线")
async def get_cn_convertible_bond_history(
    symbol: str = Query(..., description="债券代码(如 sz123138)"),
    days: int = Query(120, ge=1, le=1000, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await fi_uc.get_convertible_bond_history(symbol=symbol, days=days)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_convertible_bond_history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/convertible-bond-detail", summary="可转债条款详情")
async def get_cn_convertible_bond_detail(
    symbol: str = Query(..., description="债券代码(如 123138)"),
) -> Dict[str, Any]:
    try:
        result = await fi_uc.get_convertible_bond_detail(symbol=symbol)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_convertible_bond_detail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/credit-spread", summary="信用利差")
async def get_cn_credit_spread(
    start_date: str = Query("", description="起始日期(YYYYMMDD)"),
    end_date: str = Query("", description="截止日期(YYYYMMDD)"),
) -> Dict[str, Any]:
    try:
        result = await fi_uc.get_credit_spread(start_date=start_date, end_date=end_date)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_credit_spread: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview", summary="中国固定收益全景概览")
async def get_cn_fixed_income_overview() -> Dict[str, Any]:
    try:
        result = await fi_uc.get_fixed_income_overview()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_fixed_income_overview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
