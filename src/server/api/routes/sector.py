# src/server/api/routes/sector.py
"""Sector / industry API routes.

Provides RESTful HTTP endpoints for sector-level data:
- Industry board list (all A-share industry sectors)
"""

from fastapi import APIRouter, HTTPException, status
from typing import Dict, Any

from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/sector", tags=["行业 Sector"])


@router.get(
    "/industry-list",
    summary="行业板块列表",
    description=(
        "返回全市场行业板块列表，含板块代码、名称、涨跌幅、成分股数量、领涨股等汇总数据。"
        "板块 code 可用于后续板块详情查询。"
    ),
)
async def get_industry_list() -> Dict[str, Any]:
    try:
        logger.info("API: get_industry_list")
        result = await Container.market_gateway().get_industry_list()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_industry_list: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get industry list: {str(e)}",
        )
