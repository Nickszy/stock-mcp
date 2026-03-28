"""Fund data API routes.

Provides RESTful HTTP endpoints for fund/ETF data.
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any

from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/fund", tags=["Fund Data"])


# ------------------------------------------------------------------
# search_funds
# ------------------------------------------------------------------
@router.get(
    "/search",
    summary="搜索公募基金",
    description="按名称/代码模糊搜索基金，支持多周期业绩排序",
)
async def search_funds(
    keyword: str = Query("", description="搜索关键词 (名称或代码)"),
    sort_by: str = Query("近1年", description="排序维度 (近1周/近1月/近3月/近6月/近1年/近3年/今年来/成立来)"),
    sort_order: str = Query("desc", description="排序方向"),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
) -> Dict[str, Any]:
    try:
        logger.info("API: search_funds", keyword=keyword)
        result = await Container.market_gateway().search_funds(
            keyword=keyword, sort_by=sort_by,
            sort_order=sort_order, limit=limit,
        )
        return rest_response(data=result)
    except Exception as e:
        logger.error(f"API error in search_funds: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search funds: {str(e)}",
        )


# ------------------------------------------------------------------
# get_fund_detail
# ------------------------------------------------------------------
@router.get(
    "/detail",
    summary="获取基金详情",
    description="获取基金基本信息、费率、资产配置等",
)
async def get_fund_detail(
    fund_code: str = Query(..., description="基金代码 (如 110011, 005827)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_fund_detail", fund_code=fund_code)
        result = await Container.market_gateway().get_fund_detail(fund_code=fund_code)
        return rest_response(data=result, symbol=fund_code)
    except Exception as e:
        logger.error(f"API error in get_fund_detail: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fund detail: {str(e)}",
        )


# ------------------------------------------------------------------
# get_fund_ranking
# ------------------------------------------------------------------
@router.get(
    "/ranking",
    summary="获取基金排行",
    description="按类型和业绩周期筛选排序基金",
)
async def get_fund_ranking(
    fund_type: str = Query("全部", description="基金类型 (全部/股票型/混合型/债券型/指数型/QDII/FOF/货币型)"),
    sort_by: str = Query("近1年", description="排序维度 (近1周/近1月/近3年/近6月/近1年/近3年/今年来/成立来)"),
    sort_order: str = Query("desc", description="排序方向"),
    limit: int = Query(30, ge=1, le=100, description="返回数量"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_fund_ranking", fund_type=fund_type)
        result = await Container.market_gateway().get_fund_ranking(
            fund_type=fund_type, sort_by=sort_by,
            sort_order=sort_order, limit=limit,
        )
        return rest_response(data=result)
    except Exception as e:
        logger.error(f"API error in get_fund_ranking: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fund ranking: {str(e)}",
        )


# ------------------------------------------------------------------
# get_fund_manager
# ------------------------------------------------------------------
@router.get(
    "/manager",
    summary="获取基金经理信息",
    description="按姓名或公司搜索基金经理",
)
async def get_fund_manager(
    manager_name: str = Query("", description="经理姓名 (模糊匹配)"),
    fund_company: str = Query("", description="基金公司 (模糊匹配)"),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_fund_manager", manager_name=manager_name)
        result = await Container.market_gateway().get_fund_manager(
            manager_name=manager_name, fund_company=fund_company, limit=limit,
        )
        return rest_response(data=result)
    except Exception as e:
        logger.error(f"API error in get_fund_manager: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fund manager: {str(e)}",
        }


# ------------------------------------------------------------------
# get_fund_valuation
# ------------------------------------------------------------------
@router.get(
    "/valuation",
    summary="获取基金实时估值",
    description="获取基金实时估值数据 (估算净值、估算涨跌幅",
)
async def get_fund_valuation(
    fund_code: str = Query("", description="基金代码 (为空返回全市场前20)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_fund_valuation", fund_code=fund_code)
        result = await Container.market_gateway().get_fund_valuation(fund_code=fund_code)
        return rest_response(data=result)
    except Exception as e:
        logger.error(f"API error in get_fund_valuation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fund valuation: {str(e)}",
        }


# ------------------------------------------------------------------
# get_fund_performance
# ------------------------------------------------------------------
@router.get(
    "/performance",
    summary="获取基金业绩分析",
    description="获取基金业绩分析,包括排名、超额收益、最大回撤、盈利概率",
)
async def get_fund_performance(
    fund_code: str = Query(..., description="基金代码 (如 110011, 005827)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_fund_performance", fund_code=fund_code)
        result = await Container.market_gateway().get_fund_performance(fund_code=fund_code)
        return rest_response(data=result, symbol=fund_code)
    except Exception as e:
        logger.error(f"API error in get_fund_performance: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fund performance: {str(e)}",
        )


# ------------------------------------------------------------------
# get_fund_scale
# ------------------------------------------------------------------
@router.get(
    "/scale",
    summary="获取全市场基金规模变动",
    description="获取全市场基金规模变动: 基金家数、申购/赎回/净资产的历史变化趋势",
)
async def get_fund_scale() -> Dict[str, Any]:
    try:
        logger.info("API: get_fund_scale")
        result = await Container.market_gateway().get_fund_scale()
        return rest_response(data=result)
    except Exception as e:
        logger.error(f"API error in get_fund_scale: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fund scale: {str(e)}",



# ------------------------------------------------------------------
# get_fund_nav
# ------------------------------------------------------------------
@router.get(
    "/nav",
    summary="获取基金净值历史",
    description="获取基金净值历史数据",
)
async def get_fund_nav(
    fund_code: str = Query(..., description="基金代码"),
    days: int = Query(30, ge=1, le=365, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_fund_nav", fund_code=fund_code)
        result = await Container.market_gateway().get_fund_nav(fund_code=fund_code, days=days)
        return rest_response(data=result, symbol=fund_code)
    except Exception as e:
        logger.error(f"API error in get_fund_nav: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fund nav: {str(e)}",
        )


# ------------------------------------------------------------------
# get_fund_holdings
# ------------------------------------------------------------------
@router.get(
    "/holdings",
    summary="获取基金持仓",
    description="获取基金持仓数据（重仓股、行业配置等）",
)
async def get_fund_holdings(
    fund_code: str = Query(..., description="基金代码"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_fund_holdings", fund_code=fund_code)
        result = await Container.market_gateway().get_fund_holdings(fund_code=fund_code)
        return rest_response(data=result, symbol=fund_code)
    except Exception as e:
        logger.error(f"API error in get_fund_holdings: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get fund holdings: {str(e)}",
