# src/server/api/routes/options.py
"""Option market data REST API routes."""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any
from src.server.utils.logger import logger
from src.server.core.use_cases import options as opt_uc
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/options", tags=["期权 Options"])


@router.get("/chain", summary="期权合约列表")
async def get_option_chain(
    symbol: str = Query("50ETF", description="标的名称(50ETF/300ETF)"),
    exchange: str = Query("null", description="交易所"),
) -> Dict[str, Any]:
    try:
        result = await opt_uc.get_option_chain(symbol=symbol, exchange=exchange)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_option_chain: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/greeks", summary="期权Greeks(Delta/Gamma/Theta/Vega/IV)")
async def get_option_greeks(
    contract: str = Query(..., description="合约代码(如 10003045)"),
) -> Dict[str, Any]:
    try:
        result = await opt_uc.get_option_greeks(contract=contract)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_option_greeks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/price-history", summary="期权合约历史行情")
async def get_option_price_history(
    contract: str = Query(..., description="合约代码(如 10003889)"),
) -> Dict[str, Any]:
    try:
        result = await opt_uc.get_option_price_history(contract=contract)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_option_price_history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
