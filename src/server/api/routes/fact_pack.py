# src/server/api/routes/fact_pack.py
"""Fact pack API routes.

Provides RESTful HTTP endpoints for aggregated fact pack data:
- Stock fact pack (COL-148)
- Fund fact pack (COL-150)
- Market fact pack (COL-152)
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any

from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/fact-pack", tags=["Fact Pack"])


# ------------------------------------------------------------------
# get_stock_fact_pack
# ------------------------------------------------------------------
@router.get(
    "/stock/{symbol}",
    summary="获取股票事实包",
    description=(
        "聚合全维度股票结构化事实数据: 证券主档、财务、市场估值、公司治理、"
        "事件(分红/回购/解禁)、业务结构。"
    ),
)
async def get_stock_fact_pack(
    symbol: str,
) -> Dict[str, Any]:
    try:
        logger.info("API: get_stock_fact_pack", symbol=symbol)
        result = await Container.market_gateway().get_stock_fact_pack(symbol=symbol)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_stock_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stock fact pack: {str(e)}",
        )


# ------------------------------------------------------------------
# get_fund_fact_pack
# ------------------------------------------------------------------
@router.get(
    "/fund/{fund_code}",
    summary="获取基金事实包",
    description=(
        "聚合全维度基金结构化事实数据: 基金主档、净值收益、持仓穿透、基金经理、"
        "规模份额、资产配置、费率分红、同类比较。"
    ),
)
async def get_fund_fact_pack(
    fund_code: str,
) -> Dict[str, Any]:
    try:
        logger.info("API: get_fund_fact_pack", fund_code=fund_code)
        result = await Container.market_gateway().get_fund_fact_pack(fund_code=fund_code)
        return rest_response(data=result, symbol=fund_code, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_fund_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fund fact pack: {str(e)}",
        )


# ------------------------------------------------------------------
# get_market_fact_pack
# ------------------------------------------------------------------
@router.get(
    "/market/{symbol}",
    summary="获取行情事实包",
    description=(
        "聚合全维度行情结构化事实数据: 标的估值、技术快照、K线因子、资金流、"
        "市场广度、指数板块、衍生行情、相对强弱。"
    ),
)
async def get_market_fact_pack(
    symbol: str,
) -> Dict[str, Any]:
    try:
        logger.info("API: get_market_fact_pack", symbol=symbol)
        result = await Container.market_gateway().get_market_fact_pack(symbol=symbol)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_market_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get market fact pack: {str(e)}",
        )
