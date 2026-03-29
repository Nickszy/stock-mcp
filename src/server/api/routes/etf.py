# src/server/api/routes/etf.py
"""ETF data API routes.

Provides RESTful HTTP endpoints for ETF data:
- ETF list with real-time quotes
- ETF detail info
- ETF performance / price history
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any

from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/etf", tags=["ETF Data"])


# ------------------------------------------------------------------
# get_etf_list
# ------------------------------------------------------------------
@router.get(
    "/list",
    summary="获取ETF列表",
    description="获取ETF实时行情列表，支持按类型筛选",
)
async def get_etf_list(
    etf_type: str = Query("", description="ETF类型筛选 (股票型/债券型/商品型/跨境型)"),
    limit: int = Query(50, ge=1, le=500, description="返回数量"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_etf_list", etf_type=etf_type)
        result = await Container.market_gateway().get_etf_list(
            etf_type=etf_type, limit=limit,
        )
        return rest_response(data=result)
    except Exception as e:
        logger.error(f"API error in get_etf_list: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get ETF list: {str(e)}",
        )


# ------------------------------------------------------------------
# get_etf_detail
# ------------------------------------------------------------------
@router.get(
    "/detail",
    summary="获取ETF详情",
    description="获取ETF基金详情数据",
)
async def get_etf_detail(
    symbol: str = Query(..., description="ETF代码 (如 510300, 159919)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_etf_detail", symbol=symbol)
        result = await Container.market_gateway().get_etf_detail(symbol)
        return rest_response(data=result, symbol=symbol)
    except Exception as e:
        logger.error(f"API error in get_etf_detail: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get ETF detail: {str(e)}",
        )


# ------------------------------------------------------------------
# get_etf_performance
# ------------------------------------------------------------------
@router.get(
    "/performance",
    summary="获取ETF行情历史",
    description="获取ETF价格历史数据 (OHLCV)",
)
async def get_etf_performance(
    symbol: str = Query("510300", description="ETF代码"),
    period: str = Query("daily", description="周期 (daily/weekly/monthly)"),
    start_date: str = Query("", description="开始日期 (如 20260101)"),
    end_date: str = Query("", description="结束日期 (如 20260328)"),
    limit: int = Query(60, ge=1, le=500, description="返回数量"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_etf_performance", symbol=symbol)
        result = await Container.market_gateway().get_etf_performance(
            symbol=symbol, period=period,
            start_date=start_date, end_date=end_date, limit=limit,
        )
        return rest_response(data=result, symbol=symbol)
    except Exception as e:
        logger.error(f"API error in get_etf_performance: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get ETF performance: {str(e)}",
        )
