# src/server/api/routes/cn_macro.py
"""China macroeconomic data REST API routes."""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any
from src.server.utils.logger import logger
from src.server.core.use_cases import money_flow as money_flow_use_cases
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/cn-macro", tags=["中国宏观 Macro CN"])


@router.get("/gdp", summary="中国GDP")
async def get_cn_gdp(
    quarters: int = Query(20, ge=1, le=80, description="季度数"),
) -> Dict[str, Any]:
    try:
        result = await money_flow_use_cases.get_gdp_data(quarters)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_gdp: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cpi", summary="中国CPI")
async def get_cn_cpi(
    months: int = Query(60, ge=1, le=240, description="月数"),
) -> Dict[str, Any]:
    try:
        result = await money_flow_use_cases.get_inflation_data(months)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_cpi: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ppi", summary="中国PPI")
async def get_cn_ppi(
    months: int = Query(60, ge=1, le=240, description="月数"),
) -> Dict[str, Any]:
    try:
        result = await money_flow_use_cases.get_inflation_data(months)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_ppi: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pmi", summary="中国PMI")
async def get_cn_pmi(
    months: int = Query(60, ge=1, le=240, description="月数"),
) -> Dict[str, Any]:
    try:
        result = await money_flow_use_cases.get_pmi_data(months)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_pmi: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/money-supply", summary="中国货币供应量(M0/M1/M2)")
async def get_cn_money_supply(
    months: int = Query(60, ge=1, le=240, description="月数"),
) -> Dict[str, Any]:
    try:
        result = await money_flow_use_cases.get_money_supply(months)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_money_supply: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/interest-rates", summary="中国利率(SHIBOR+LPR)")
async def get_cn_interest_rates(
    shibor_days: int = Query(252, ge=1, le=1000, description="Shibor天数"),
    lpr_months: int = Query(60, ge=1, le=240, description="LPR月数"),
) -> Dict[str, Any]:
    try:
        result = await money_flow_use_cases.get_interest_rates(shibor_days, lpr_months)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_interest_rates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trade-balance", summary="中国进出口贸易差额")
async def get_cn_trade_balance(
    months: int = Query(60, ge=1, le=240, description="月数"),
) -> Dict[str, Any]:
    try:
        result = await money_flow_use_cases.get_trade_balance(months)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_trade_balance: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/social-financing", summary="中国社会融资规模")
async def get_cn_social_financing(
    months: int = Query(60, ge=1, le=240, description="月数"),
) -> Dict[str, Any]:
    try:
        result = await money_flow_use_cases.get_social_financing(months)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_cn_social_financing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/overview", summary="中国宏观经济全景概览")
async def get_cn_macro_overview() -> Dict[str, Any]:
    """Aggregate all key China macro indicators into one response."""
    import asyncio

    indicators: Dict[str, Any] = {}

    async def _safe(label: str, coro):
        try:
            indicators[label] = await coro
        except Exception:
            pass

    await asyncio.gather(
        _safe("gdp", money_flow_use_cases.get_gdp_data(4)),
        _safe("inflation", money_flow_use_cases.get_inflation_data(12)),
        _safe("pmi", money_flow_use_cases.get_pmi_data(12)),
        _safe("money_supply", money_flow_use_cases.get_money_supply(12)),
        _safe("social_financing", money_flow_use_cases.get_social_financing(12)),
        _safe("interest_rates", money_flow_use_cases.get_interest_rates(30, 12)),
        _safe("trade_balance", money_flow_use_cases.get_trade_balance(12)),
    )

    return rest_response(data=indicators, source="akshare")
