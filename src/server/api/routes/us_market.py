# src/server/api/routes/us_market.py
"""US market data API routes.

Provides RESTful HTTP endpoints for US stock market data:
- Company profile, earnings, cash flow, valuation
- Institutional holdings, analyst recommendations
- Revenue segments, insider trading, share statistics, financial health
- Price history, volume analysis, market overview
- Sector ETF analysis
- US macro indicators (GDP, inflation, interest rates)
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any, Optional

from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/us", tags=["美股个股 US Stock"])


# ------------------------------------------------------------------
# US Fundamental endpoints
# ------------------------------------------------------------------

@router.get(
    "/profile",
    summary="美股公司档案",
    description="获取美股公司综合档案: 行业/描述/员工/CEO/市值/价格区间",
)
async def get_us_company_profile(
    ticker: str = Query(..., description="股票代码 (如 AAPL, MSFT)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_company_profile", ticker=ticker)
        result = await Container.market_gateway().get_us_company_profile(ticker)
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_company_profile: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get company profile: {str(e)}",
        )


@router.get(
    "/earnings",
    summary="美股EPS历史",
    description="获取美股EPS历史: 实际vs预估, 惊喜百分比",
)
async def get_earnings_history(
    ticker: str = Query(..., description="股票代码"),
    quarters: int = Query(8, ge=1, le=20, description="季度数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_earnings_history", ticker=ticker)
        result = await Container.market_gateway().get_earnings_history(
            ticker, quarters=quarters,
        )
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_earnings_history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get earnings history: {str(e)}",
        )


@router.get(
    "/cashflow-quality",
    summary="美股现金流质量",
    description="获取经营/自由现金流及FCF/净利润比率",
)
async def get_cash_flow_quality(
    ticker: str = Query(..., description="股票代码"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_cash_flow_quality", ticker=ticker)
        result = await Container.market_gateway().get_cash_flow_quality(ticker)
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_cash_flow_quality: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cash flow quality: {str(e)}",
        )


@router.get(
    "/valuation",
    summary="美股估值指标",
    description="获取PE/PS/PB/EV-EBITDA/PEG/市值/股息率",
)
async def get_us_valuation_metrics(
    ticker: str = Query(..., description="股票代码"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_valuation_metrics", ticker=ticker)
        result = await Container.market_gateway().get_us_valuation_metrics(ticker)
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_valuation_metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get valuation metrics: {str(e)}",
        )


@router.get(
    "/institutional",
    summary="美股机构持仓",
    description="获取前15大机构持仓及近期变动方向",
)
async def get_us_institutional_holdings(
    ticker: str = Query(..., description="股票代码"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_institutional_holdings", ticker=ticker)
        result = await Container.market_gateway().get_us_institutional_holdings(ticker)
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_institutional_holdings: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get institutional holdings: {str(e)}",
        )


@router.get(
    "/analyst",
    summary="美股分析师评级",
    description="获取一致评级(强买/买入/持有/卖出/强卖)及目标价",
)
async def get_us_analyst_recommendations(
    ticker: str = Query(..., description="股票代码"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_analyst_recommendations", ticker=ticker)
        result = await Container.market_gateway().get_us_analyst_recommendations(ticker)
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_analyst_recommendations: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get analyst recommendations: {str(e)}",
        )


@router.get(
    "/revenue-segments",
    summary="美股收入结构",
    description="获取按地区和业务板块的收入拆分",
)
async def get_us_revenue_segments(
    ticker: str = Query(..., description="股票代码"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_revenue_segments", ticker=ticker)
        result = await Container.market_gateway().get_us_revenue_segments(ticker)
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_revenue_segments: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get revenue segments: {str(e)}",
        )


@router.get(
    "/insider",
    summary="美股内部人交易",
    description="获取近期内部人买卖及净情绪方向",
)
async def get_us_insider_trading(
    ticker: str = Query(..., description="股票代码"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_insider_trading", ticker=ticker)
        result = await Container.market_gateway().get_us_insider_trading(ticker)
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_insider_trading: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get insider trading: {str(e)}",
        )


@router.get(
    "/share-stats",
    summary="美股股本统计",
    description="获取流通股/空头利息/机构持仓比例/内部人持仓比例",
)
async def get_us_share_statistics(
    ticker: str = Query(..., description="股票代码"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_share_statistics", ticker=ticker)
        result = await Container.market_gateway().get_us_share_statistics(ticker)
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_share_statistics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get share statistics: {str(e)}",
        )


@router.get(
    "/financial-health",
    summary="美股财务健康评分",
    description="综合评分0-100: 盈利/流动性/偿债/成长/估值五维",
)
async def get_us_financial_health(
    ticker: str = Query(..., description="股票代码"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_financial_health", ticker=ticker)
        result = await Container.market_gateway().get_us_financial_health(ticker)
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_financial_health: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get financial health: {str(e)}",
        )


# ------------------------------------------------------------------
# US Technical endpoints
# ------------------------------------------------------------------

@router.get(
    "/price-history",
    summary="美股K线历史",
    description="获取OHLCV价格历史 (日/周/月线)",
)
async def get_us_price_history(
    ticker: str = Query(..., description="股票代码"),
    days: int = Query(60, ge=5, le=365, description="天数"),
    interval: str = Query("1d", description="周期 (1d/1wk/1mo)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_price_history", ticker=ticker)
        result = await Container.market_gateway().get_us_price_history(
            ticker, days=days, interval=interval,
        )
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_price_history: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get price history: {str(e)}",
        )


@router.get(
    "/volume-analysis",
    summary="美股量价分析",
    description="获取平均成交量/相对成交量/OBV趋势",
)
async def get_us_volume_analysis(
    ticker: str = Query(..., description="股票代码"),
    days: int = Query(30, ge=5, le=120, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_volume_analysis", ticker=ticker)
        result = await Container.market_gateway().get_us_volume_analysis(
            ticker, days=days,
        )
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_volume_analysis: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get volume analysis: {str(e)}",
        )


@router.get(
    "/market-overview",
    summary="美股市场概览",
    description="主要指数表现/VIX/行业ETF表现/市场情绪",
)
async def get_us_market_overview() -> Dict[str, Any]:
    try:
        logger.info("API: get_us_market_overview")
        result = await Container.market_gateway().get_us_market_overview()
        return rest_response(data=result, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_market_overview: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get market overview: {str(e)}",
        )


# ------------------------------------------------------------------
# US Sector endpoint
# ------------------------------------------------------------------

@router.get(
    "/sector-etf",
    summary="美股行业ETF分析",
    description="按行业名称分析代表性ETF走势 (支持中英文行业名)",
)
async def get_us_sector_etf_analysis(
    sector_name: str = Query(..., description="行业名称 (如 Technology/科技, Healthcare/医疗)"),
    days: int = Query(30, ge=5, le=120, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_sector_etf_analysis", sector_name=sector_name)
        result = await Container.market_gateway().get_us_sector_etf_analysis(
            sector_name=sector_name, days=days,
        )
        return rest_response(data=result, symbol=sector_name, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_sector_etf_analysis: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get sector ETF analysis: {str(e)}",
        )


# ------------------------------------------------------------------
# US Macro endpoints (FRED)
# ------------------------------------------------------------------

@router.get(
    "/gdp",
    summary="美国GDP数据",
    description="美国实际GDP水平及增长率趋势",
)
async def get_us_economic_growth(
    quarters: int = Query(20, ge=4, le=80, description="季度数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_economic_growth")
        result = await Container.market_gateway().get_us_economic_growth(quarters=quarters)
        return rest_response(data=result, source="fred")
    except Exception as e:
        logger.error(f"API error in get_us_economic_growth: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get GDP data: {str(e)}",
        )


@router.get(
    "/inflation",
    summary="美国通胀与就业",
    description="CPI同比及失业率时序数据",
)
async def get_us_inflation_employment(
    months: int = Query(24, ge=6, le=120, description="月数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_inflation_employment")
        result = await Container.market_gateway().get_us_inflation_employment(months=months)
        return rest_response(data=result, source="fred")
    except Exception as e:
        logger.error(f"API error in get_us_inflation_employment: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get inflation data: {str(e)}",
        )


@router.get(
    "/interest-rates",
    summary="美国利率数据",
    description="2Y/10Y国债收益率/联邦基金利率/曲线利差",
)
async def get_us_interest_rates(
    days: int = Query(180, ge=30, le=365, description="天数"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_us_interest_rates")
        result = await Container.market_gateway().get_us_interest_rates(days=days)
        return rest_response(data=result, source="fred")
    except Exception as e:
        logger.error(f"API error in get_us_interest_rates: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get interest rates: {str(e)}",
        )
