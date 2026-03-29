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


# ------------------------------------------------------------------
# Batch: 26 missing REST endpoints for money-flow / market data
# COL-177: Close MCP→REST coverage gap (119→109 endpoints)
# ------------------------------------------------------------------


@router.get("/market-money-flow", summary="全市场资金流向")
async def get_market_money_flow(
    days: int = Query(30, ge=5, le=120, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_market_money_flow(days=days)
        return rest_response(data=result, symbol="全市场", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market-liquidity", summary="市场流动性指标")
async def get_market_liquidity(
    days: int = Query(30, ge=5, le=120, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_market_liquidity(days=days)
        return rest_response(data=result, symbol="全市场", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/money-supply", summary="货币供应量(M0/M1/M2)")
async def get_money_supply() -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_money_supply()
        return rest_response(data=result, symbol="货币供应", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/social-financing", summary="社会融资规模")
async def get_social_financing() -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_social_financing()
        return rest_response(data=result, symbol="社融", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pmi", summary="PMI 制造业/非制造业指数")
async def get_pmi_data() -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_pmi_data()
        return rest_response(data=result, symbol="PMI", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/gdp", summary="国内生产总值 GDP")
async def get_gdp_data() -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_gdp_data()
        return rest_response(data=result, symbol="GDP", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dragon-tiger", summary="龙虎榜数据")
async def get_dragon_tiger_list(
    days: int = Query(5, ge=1, le=30, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_dragon_tiger_list(days=days)
        return rest_response(data=result, symbol="龙虎榜", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/block-trade", summary="大宗交易数据")
async def get_block_trade(
    days: int = Query(10, ge=1, le=60, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_block_trade(days=days)
        return rest_response(data=result, symbol="大宗交易", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/etf-flow", summary="ETF 资金流")
async def get_etf_flow(
    symbol: str = Query("", description="ETF 代码"),
    days: int = Query(30, ge=5, le=120, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_etf_flow(symbol=symbol, days=days)
        return rest_response(data=result, symbol=symbol or "ETF", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/convertible-bond", summary="可转债数据")
async def get_convertible_bond(
    symbol: str = Query("", description="债券代码"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_convertible_bond(symbol=symbol)
        return rest_response(data=result, symbol=symbol or "可转债", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/futures-main", summary="期货主力合约")
async def get_futures_main(
    symbol: str = Query("", description="期货品种"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_futures_main(symbol=symbol)
        return rest_response(data=result, symbol=symbol or "期货", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/option-summary", summary="期权概要数据")
async def get_option_summary(
    symbol: str = Query("", description="期权品种"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_option_summary(symbol=symbol)
        return rest_response(data=result, symbol=symbol or "期权", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/commodity-inventory", summary="商品库存数据")
async def get_commodity_inventory(
    symbol: str = Query("", description="商品代码"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_commodity_inventory(symbol=symbol)
        return rest_response(data=result, symbol=symbol or "商品", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ggt-daily", summary="港股通每日数据")
async def get_ggt_daily(
    days: int = Query(30, ge=5, le=120, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_ggt_daily(days=days)
        return rest_response(data=result, symbol="港股通", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/bond-yield", summary="国债收益率曲线")
async def get_bond_yield(
    days: int = Query(30, ge=5, le=250, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_bond_yield(days=days)
        return rest_response(data=result, symbol="国债", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/northbound-holdings", summary="北向持股明细")
async def get_stock_northbound_holdings(
    symbol: str = Query(..., description="股票代码"),
    days: int = Query(30, ge=5, le=120, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_stock_northbound_holdings(symbol=symbol)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top10-shareholders", summary="前十大股东")
async def get_stock_top10_shareholders(
    symbol: str = Query(..., description="股票代码"),
    date: str = Query("", description="季度日期"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_stock_top10_shareholders(symbol=symbol, date=date)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/shareholder-changes", summary="股东户数变化")
async def get_stock_shareholder_changes(
    symbol: str = Query(..., description="股票代码"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_stock_shareholder_changes(symbol=symbol)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/institutional-research", summary="机构调研记录")
async def get_stock_institutional_research(
    symbol: str = Query("", description="股票代码"),
    days: int = Query(90, ge=5, le=365, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_stock_institutional_research(symbol=symbol, days=days)
        return rest_response(data=result, symbol=symbol or "机构调研", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fund-holdings", summary="基金持仓明细")
async def get_fund_holdings(
    symbol: str = Query("", description="基金代码"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_fund_holdings(symbol=symbol)
        return rest_response(data=result, symbol=symbol or "基金持仓", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fund-nav", summary="基金净值数据")
async def get_fund_nav(
    symbol: str = Query("", description="基金代码"),
    days: int = Query(30, ge=5, le=365, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_fund_nav(symbol=symbol, days=days)
        return rest_response(data=result, symbol=symbol or "基金净值", source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/index-constituents", summary="指数成分股列表")
async def get_index_constituents(
    symbol: str = Query(..., description="指数代码"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_index_constituents(symbol=symbol)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/index-weights", summary="指数成分权重")
async def get_index_constituent_weights(
    symbol: str = Query(..., description="指数代码"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_index_constituent_weights(symbol=symbol)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sector-pe-pb", summary="行业 PE/PB 历史百分位")
async def get_sector_pe_pb_historical(
    sector_name: str = Query(..., description="行业名称"),
    days: int = Query(250, ge=30, le=750, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_sector_pe_pb_historical(
            sector_name=sector_name, days=days,
        )
        return rest_response(data=result, symbol=sector_name, source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sector-valuation", summary="行业估值指标")
async def get_sector_valuation_metrics(
    sector_name: str = Query(..., description="行业名称"),
    days: int = Query(250, ge=30, le=750, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().get_sector_valuation_metrics(
            sector_name=sector_name, days=days,
        )
        return rest_response(data=result, symbol=sector_name, source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/risk-metrics", summary="风险指标计算")
async def calculate_risk_metrics(
    symbol: str = Query(..., description="股票代码"),
    days: int = Query(250, ge=30, le=750, description="天数"),
) -> Dict[str, Any]:
    try:
        result = await Container.market_gateway().calculate_risk_metrics(
            symbol=symbol, days=days,
        )
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
