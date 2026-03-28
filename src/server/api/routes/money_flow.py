# src/server/api/routes/money_flow.py
"""Money flow analysis API routes.

Provides RESTful HTTP endpoints for money flow and capital flow data.
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any, List, Optional
from src.server.utils.logger import logger
from src.server.core.use_cases import money_flow as money_flow_use_cases
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/money-flow", tags=["Money Flow Analysis"])




@router.get(
    "/stock/{symbol}",
    summary="获取个股资金流向",
    description="""
    获取个股主力资金和散户资金的流入流出情况

    **支持的代码格式:**
    - A股: `600519`, `600519.SH`, `SSE:600519`
    - A股: `000001`, `000001.SZ`, `SZSE:000001`

    **返回数据:**
    - 主力资金净流入/流出
    - 散户资金净流入/流出
    - 资金流向趋势分析
    """,
)
async def get_stock_money_flow(
    symbol: str, days: int = Query(20, ge=1, le=90, description="获取最近N天数据")
) -> Dict[str, Any]:
    """获取个股资金流向数据"""
    try:
        logger.info(
            "API: get_stock_money_flow called",
            symbol=symbol,
            days=days,
        )

        result = await money_flow_use_cases.get_money_flow(symbol, days)

        return rest_response(data=result, symbol=symbol, limit=days)

    except Exception as e:
        logger.error(f"API error in get_stock_money_flow: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get money flow: {str(e)}",
        )


@router.get(
    "/north-bound",
    summary="获取北向资金流向",
    description="""
    获取北向资金(沪深港通)流入A股市场的情况

    **数据说明:**
    - 沪股通: 香港投资者买卖上交所股票
    - 深股通: 香港投资者买卖深交所股票
    - 北向资金被称为"聪明钱"，对市场有重要参考价值

    **返回数据:**
    - 每日沪股通/深股通净流入
    - 北向资金合计
    - 流向趋势分析
    """,
)
async def get_north_bound_flow(
    days: int = Query(30, ge=1, le=120, description="获取最近N天数据")
) -> Dict[str, Any]:
    """获取北向资金流向数据"""
    try:
        logger.info("API: get_north_bound_flow called", days=days)

        result = await money_flow_use_cases.get_north_bound_flow(days)

        return rest_response(data=result, limit=days)

    except Exception as e:
        logger.error(f"API error in get_north_bound_flow: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get north bound flow: {str(e)}",
        )


@router.get(
    "/chip-distribution/{symbol}",
    summary="获取筹码分布数据",
    description="""
    获取个股的筹码分布和成本分析数据

    **数据说明:**
    - 筹码分布反映投资者持仓成本分布
    - 获利比例显示当前价格下的盈利投资者占比
    - 成本集中度反映主力筹码的集中程度

    **返回数据:**
    - 筹码分布历史
    - 获利比例
    - 成本集中度指标
    """,
)
async def get_chip_distribution(
    symbol: str, days: int = Query(30, ge=1, le=90, description="获取最近N天数据")
) -> Dict[str, Any]:
    """获取筹码分布数据"""
    try:
        logger.info(
            "API: get_chip_distribution called",
            symbol=symbol,
            days=days,
        )

        result = await money_flow_use_cases.get_chip_distribution(symbol, days)

        return rest_response(data=result, symbol=symbol, limit=days)

    except Exception as e:
        logger.error(f"API error in get_chip_distribution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get chip distribution: {str(e)}",
        )


# ------------------------------------------------------------------
# Gateway-based endpoints (market breadth / sector / style / margin)
# ------------------------------------------------------------------

@router.get(
    "/sector-trend",
    summary="行业板块趋势",
    description="按行业名称查看板块涨跌趋势",
)
async def get_sector_trend(
    sector_name: str = Query("", description="行业名称 (如 白酒/医药/科技)"),
    days: int = Query(10, ge=1, le=120, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_sector_trend", sector_name=sector_name)
        result = await Container.market_gateway().get_sector_trend(
            sector_name=sector_name, days=days,
        )
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_sector_trend: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get sector trend: {str(e)}",
        )


@router.get(
    "/sector-money-flow",
    summary="板块资金流历史",
    description="按行业名称查看板块资金流历史",
)
async def get_sector_money_flow_history(
    sector_name: str = Query("", description="行业名称"),
    days: int = Query(20, ge=1, le=60, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_sector_money_flow_history", sector_name=sector_name)
        result = await Container.market_gateway().get_sector_money_flow_history(
            sector_name=sector_name, days=days,
        )
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_sector_money_flow_history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get sector money flow: {str(e)}",
        )


@router.get(
    "/market-breadth",
    summary="市场广度",
    description="上涨/下跌/平家数, 中位数收益",
)
async def get_market_breadth(
    days: int = Query(20, ge=1, le=30, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_market_breadth")
        result = await Container.market_gateway().get_market_breadth(days=days)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_market_breadth: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get market breadth: {str(e)}",
        )


@router.get(
    "/relative-strength",
    summary="相对强弱",
    description="个股相对基准指数涨跌幅对比",
)
async def get_relative_strength(
    symbol: str = Query(..., description="股票代码 (如 600519)"),
    benchmark: str = Query("000300", description="基准指数 (默认沪深300)"),
    days: int = Query(30, ge=5, le=60, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_relative_strength", symbol=symbol)
        result = await Container.market_gateway().get_relative_strength(
            symbol=symbol, benchmark=benchmark, days=days,
        )
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_relative_strength: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get relative strength: {str(e)}",
        )


@router.get(
    "/margin-trading",
    summary="融资融券",
    description="个股融资融券余额与买入额",
)
async def get_margin_trading(
    ticker: str = Query(..., description="股票代码 (如 600519)"),
    days: int = Query(30, ge=1, le=90, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_margin_trading", ticker=ticker)
        result = await Container.market_gateway().get_margin_trading(
            ticker=ticker, days=days,
        )
        return rest_response(data=result, symbol=ticker, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_margin_trading: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get margin trading: {str(e)}",
        )


@router.get(
    "/repurchase",
    summary="回购数据",
    description="股票回购进度与金额",
)
async def get_repurchase_info(
    symbol: str = Query("", description="股票代码 (为空返回全市场)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_repurchase_info", symbol=symbol)
        result = await Container.market_gateway().get_repurchase_info(symbol=symbol)
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_repurchase_info: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get repurchase info: {str(e)}",
        )


@router.get(
    "/restricted-release",
    summary="限售解禁",
    description="限售股解禁时间表与市值",
)
async def get_restricted_release(
    symbol: str = Query("", description="股票代码 (为空返回全市场)"),
    days: int = Query(90, ge=7, le=365, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_restricted_release", symbol=symbol)
        result = await Container.market_gateway().get_restricted_release(
            symbol=symbol, days=days,
        )
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_restricted_release: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get restricted release: {str(e)}",
        )


@router.get(
    "/style-rotation",
    summary="风格轮动",
    description="大盘/小盘, 成长/价值风格轮动指标",
)
async def get_style_rotation() -> Dict[str, Any]:
    try:
        logger.info("API: get_style_rotation")
        result = await Container.market_gateway().get_style_rotation()
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_style_rotation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get style rotation: {str(e)}",
        )


@router.get(
    "/futures-basis",
    summary="期指基差",
    description="股指期货基差 (期货价格 - 现货指数价格)",
)
async def get_futures_basis(
    index_code: str = Query("IF0", description="主力品种 (如 IF0/IC0/IM0)"),
    days: int = Query(60, ge=5, le=120, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_futures_basis", index_code=index_code)
        result = await Container.market_gateway().get_futures_basis(
            index_code=index_code, days=days,
        )
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_futures_basis: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get futures basis: {str(e)}",
        )
