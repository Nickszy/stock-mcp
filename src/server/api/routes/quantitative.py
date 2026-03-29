# src/server/api/routes/quantitative.py
"""Quantitative analysis API routes.

Provides RESTful HTTP endpoints for quantitative analysis:
- Stock screener (multi-factor filtering)
- Industry ranking
- Concept ranking
- Stock factor calculation
- Stock correlation matrix
- Factor ranking
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any, Optional

from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/quant", tags=["Quantitative Analysis"])


# ------------------------------------------------------------------
# screen_stocks
# ------------------------------------------------------------------
@router.get(
    "/screen",
    summary="量化选股筛选",
    description=(
        "全市场多因子条件筛选: PE/PB/市值/价格/换手率/量比/"
        "涨跌幅/年初至今/60日涨跌幅/振幅"
    ),
)
async def screen_stocks(
    min_pe: Optional[float] = Query(None, description="最小PE"),
    max_pe: Optional[float] = Query(None, description="最大PE"),
    min_pb: Optional[float] = Query(None, description="最小PB"),
    max_pb: Optional[float] = Query(None, description="最大PB"),
    min_market_cap: Optional[float] = Query(None, description="最小市值(亿)"),
    max_market_cap: Optional[float] = Query(None, description="最大市值(亿)"),
    min_price: Optional[float] = Query(None, description="最低价"),
    max_price: Optional[float] = Query(None, description="最高价"),
    min_turnover_rate: Optional[float] = Query(None, description="最小换手率%"),
    max_turnover_rate: Optional[float] = Query(None, description="最大换手率%"),
    min_volume_ratio: Optional[float] = Query(None, description="最小量比"),
    max_volume_ratio: Optional[float] = Query(None, description="最大量比"),
    min_change_pct: Optional[float] = Query(None, description="最小涨跌幅%"),
    max_change_pct: Optional[float] = Query(None, description="最大涨跌幅%"),
    min_ytd_change: Optional[float] = Query(None, description="最小年初至今涨跌幅%"),
    max_ytd_change: Optional[float] = Query(None, description="最大年初至今涨跌幅%"),
    min_60d_change: Optional[float] = Query(None, description="最小60日涨跌幅%"),
    max_60d_change: Optional[float] = Query(None, description="最大60日涨跌幅%"),
    min_amplitude: Optional[float] = Query(None, description="最小振幅%"),
    max_amplitude: Optional[float] = Query(None, description="最大振幅%"),
    exchange: Optional[str] = Query(None, description="交易所筛选 (SSE/SZSE/BSE)"),
    sector: Optional[str] = Query(None, description="行业板块筛选"),
    sort_by: str = Query("market_cap", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向 (asc/desc)"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
) -> Dict[str, Any]:
    try:
        logger.info("API: screen_stocks")
        result = await Container.market_gateway().screen_stocks(
            min_pe=min_pe, max_pe=max_pe,
            min_pb=min_pb, max_pb=max_pb,
            min_market_cap=min_market_cap, max_market_cap=max_market_cap,
            min_price=min_price, max_price=max_price,
            min_turnover_rate=min_turnover_rate, max_turnover_rate=max_turnover_rate,
            min_volume_ratio=min_volume_ratio, max_volume_ratio=max_volume_ratio,
            min_change_pct=min_change_pct, max_change_pct=max_change_pct,
            min_ytd_change=min_ytd_change, max_ytd_change=max_ytd_change,
            min_60d_change=min_60d_change, max_60d_change=max_60d_change,
            min_amplitude=min_amplitude, max_amplitude=max_amplitude,
            exchange=exchange, sector=sector,
            sort_by=sort_by, sort_order=sort_order, limit=limit,
        )
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in screen_stocks: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to screen stocks: {str(e)}",
        )


# ------------------------------------------------------------------
# get_industry_ranking
# ------------------------------------------------------------------
@router.get(
    "/industry-ranking",
    summary="行业板块排行",
    description="全市场行业板块实时涨跌排行",
)
async def get_industry_ranking(
    sort_by: str = Query("change_pct", description="排序字段 (change_pct/turnover_rate/volume/turnover/amplitude)"),
    sort_order: str = Query("desc", description="排序方向"),
    limit: int = Query(30, ge=1, le=100, description="返回数量"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_industry_ranking")
        result = await Container.market_gateway().get_industry_ranking(
            sort_by=sort_by, sort_order=sort_order, limit=limit,
        )
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_industry_ranking: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get industry ranking: {str(e)}",
        )


# ------------------------------------------------------------------
# get_concept_ranking
# ------------------------------------------------------------------
@router.get(
    "/concept-ranking",
    summary="概念板块排行",
    description="全市场概念板块实时涨跌排行",
)
async def get_concept_ranking(
    sort_by: str = Query("change_pct", description="排序字段 (change_pct/turnover_rate/volume/turnover/amplitude)"),
    sort_order: str = Query("desc", description="排序方向"),
    limit: int = Query(30, ge=1, le=100, description="返回数量"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_concept_ranking")
        result = await Container.market_gateway().get_concept_ranking(
            sort_by=sort_by, sort_order=sort_order, limit=limit,
        )
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_concept_ranking: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get concept ranking: {str(e)}",
        )


# ------------------------------------------------------------------
# get_stock_factors
# ------------------------------------------------------------------
@router.get(
    "/factors",
    summary="个股量化因子",
    description="计算单只股票的量化因子 (动量/波动率/换手率/市值/流动性)",
)
async def get_stock_factors(
    symbol: str = Query(..., description="股票代码 (如 600519)"),
    days: int = Query(250, ge=30, le=500, description="计算窗口天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_stock_factors", symbol=symbol)
        result = await Container.market_gateway().get_stock_factors(
            symbol, days=days,
        )
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_stock_factors: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stock factors: {str(e)}",
        )


# ------------------------------------------------------------------
# get_stock_correlation
# ------------------------------------------------------------------
@router.get(
    "/correlation",
    summary="股票相关性矩阵",
    description="计算多只股票之间的相关系数矩阵",
)
async def get_stock_correlation(
    symbols: str = Query(..., description="逗号分隔的股票代码 (如 600519,000858,000333)"),
    days: int = Query(60, ge=20, le=250, description="计算窗口天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_stock_correlation", symbols=symbols)
        result = await Container.market_gateway().get_stock_correlation(
            symbols, days=days,
        )
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_stock_correlation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stock correlation: {str(e)}",
        )


# ------------------------------------------------------------------
# get_factor_ranking
# ------------------------------------------------------------------
@router.get(
    "/factor-ranking",
    summary="全市场因子排名",
    description="按因子对全市场股票排名 (涨跌幅/换手率/量比/振幅)",
)
async def get_factor_ranking(
    factor: str = Query("change_pct", description="因子名称 (change_pct/turnover_rate/volume_ratio/amplitude)"),
    direction: str = Query("desc", description="排序方向 (desc/asc)"),
    limit: int = Query(30, ge=1, le=100, description="返回数量"),
    exchange: str = Query("", description="交易所筛选 (SSE/SZSE/BSE)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_factor_ranking", factor=factor)
        result = await Container.market_gateway().get_factor_ranking(
            factor=factor, direction=direction, limit=limit, exchange=exchange,
        )
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_factor_ranking: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get factor ranking: {str(e)}",
        )
