# src/server/api/routes/corporate_action.py
"""Corporate action API routes.

Provides RESTful HTTP endpoints for A-share corporate action data:
- Shareholder holding detail (COL-147)
- IPO calendar
- IPO stock info
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any

from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/corporate-action", tags=["Corporate Action"])


# ------------------------------------------------------------------
# get_shareholder_holding_detail
# ------------------------------------------------------------------
@router.get(
    "/shareholder-holding",
    summary="获取股东增减持明细",
    description="查询个股或全市场股东持股变动明细，包括股东名称、持股数量、变动方向等。",
)
async def get_shareholder_holding_detail(
    symbol: str = Query("", description="股票代码 (如 688235), 为空返回全市场"),
    date: str = Query("", description="季度日期 (如 20240930)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_shareholder_holding_detail", symbol=symbol, date=date)
        result = await Container.market_gateway().get_shareholder_holding_detail(
            symbol=symbol, date=date,
        )
        return rest_response(data=result, symbol=symbol or "全市场", source="akshare")
    except Exception as e:
        logger.error(f"API error in get_shareholder_holding_detail: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get shareholder holding detail: {str(e)}",
        )


# ------------------------------------------------------------------
# get_ipo_calendar
# ------------------------------------------------------------------
@router.get(
    "/ipo-calendar",
    summary="获取新股IPO日历",
    description="查询近期新股申购日期、发行价格、中签率、上市日期等信息。",
)
async def get_ipo_calendar() -> Dict[str, Any]:
    try:
        logger.info("API: get_ipo_calendar")
        result = await Container.market_gateway().get_ipo_calendar()
        return rest_response(data=result, symbol="IPO Calendar", source="akshare")
    except Exception as e:
        logger.error(f"API error in get_ipo_calendar: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get IPO calendar: {str(e)}",
        )


# ------------------------------------------------------------------
# get_ipo_info
# ------------------------------------------------------------------
@router.get(
    "/ipo-info/{stock}",
    summary="获取个股IPO详情",
    description="获取个股IPO详情：发行价、市盈率、中签率、上市日期等。",
)
async def get_ipo_info(
    stock: str,
) -> Dict[str, Any]:
    try:
        logger.info("API: get_ipo_info", stock=stock)
        result = await Container.market_gateway().get_ipo_info(stock=stock)
        return rest_response(data=result, symbol=stock, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_ipo_info: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get IPO info: {str(e)}",
        )
