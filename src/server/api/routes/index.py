# src/server/api/routes/index.py
"""Index data API routes.

Provides RESTful HTTP endpoints for A-share index data:
- Index list
- Index PE/PB valuation history
- Index performance
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any

from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/index", tags=["Index Data"])


# ------------------------------------------------------------------
# get_index_list
# ------------------------------------------------------------------
@router.get(
    "/list",
    summary="获取A股指数列表",
    description="获取A股全部指数列表：代码、名称、发布日期",
)
async def get_index_list() -> Dict[str, Any]:
    try:
        logger.info("API: get_index_list")
        result = await Container.market_gateway().get_index_list()
        return rest_response(data=result)
    except Exception as e:
        logger.error(f"API error in get_index_list: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get index list: {str(e)}",
        )


# ------------------------------------------------------------------
# get_index_pe_pb
# ------------------------------------------------------------------
@router.get(
    "/pe-pb",
    summary="获取指数估值历史",
    description="获取指数PE/PB估值历史数据 (如 沪深300, 上证50)",
)
async def get_index_pe_pb(
    symbol: str = Query("沪深300", description="指数名称 (如 沪深300, 上证50, 创业板指)"),
    limit: int = Query(30, ge=1, le=500, description="返回最近N条"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_index_pe_pb", symbol=symbol)
        result = await Container.market_gateway().get_index_pe_pb(
            symbol=symbol, limit=limit,
        )
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_index_pe_pb: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get index PE/PB: {str(e)}",
        )


# ------------------------------------------------------------------
# get_index_performance
# ------------------------------------------------------------------
@router.get(
    "/performance",
    summary="获取指数行情",
    description="获取指数近期行情表现数据",
)
async def get_index_performance(
    symbol: str = Query("000300", description="指数代码 (如 000300)"),
    limit: int = Query(30, ge=1, le=365, description="返回数量"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_index_performance", symbol=symbol)
        result = await Container.market_gateway().get_index_performance(
            symbol=symbol, limit=limit,
        )
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_index_performance: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get index performance: {str(e)}",
        )
