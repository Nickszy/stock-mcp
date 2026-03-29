# src/server/api/routes/fundamental.py
"""Fundamental analysis API routes.

Provides RESTful HTTP endpoints for fundamental/financial data.
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any
from src.server.utils.logger import logger
from src.server.core.use_cases import fundamental as fundamental_use_cases
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/fundamental", tags=["Fundamental Analysis"])


@router.post(
    "/financials",
    summary="获取财务报表数据",
    description="""
    获取指定股票的完整财务报表数据

    **支持的代码格式:**
    - A股: `600519` 或 `SSE:600519`
    - 美股: `AAPL` 或 `NASDAQ:AAPL`

    **返回数据:**
    - 利润表 (income_statement): 季度/年度含同比/环比
    - 资产负债表 (balance_sheet): 季度/年度含同比/环比
    - 现金流量表 (cash_flow): 季度/年度含同比/环比
    """,
)
async def get_financials(
    symbol: str = Query(..., description="股票代码 (格式: EXCHANGE:SYMBOL)"),
    period: str = Query("all", description="报告类型: quarterly | annual | all"),
    periods: int | None = Query(None, description="返回期数, None=全部"),
) -> Dict[str, Any]:
    """获取财务报表数据（利润表、资产负债表、现金流量表等）"""
    try:
        logger.info("API: get_financials called", symbol=symbol)

        result = await fundamental_use_cases.get_stock_financial_statements(
            symbol, period=period, periods=periods
        )

        return rest_response(data=result["data"], symbol=result.get("symbol"),
                             source=result.get("source", {}).get("provider"),
                             period=period, limit=periods)

    except Exception as e:
        logger.error(f"API error in get_financials: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get financials: {str(e)}"
        )


@router.post(
    "/report",
    summary="获取财务报告分析",
    description="""
    获取指定股票的财务报告分析

    **支持的代码格式:**
    - 美股: `AAPL` 或 `NASDAQ:AAPL`
    - A股: `600519` 或 `SSE:600519`

    **返回数据:**
    - 营收、利润、现金流等关键财务指标
    - 财务健康度评估
    """,
)
async def get_financial_report(
    symbol: str = Query(..., description="股票代码")
) -> Dict[str, Any]:
    """获取财务报告分析"""
    try:
        logger.info("API: get_financial_report called", symbol=symbol)

        result = await fundamental_use_cases.get_fundamental_analysis(symbol)

        return rest_response(data=result, symbol=symbol)

    except Exception as e:
        logger.error(f"API error in get_financial_report: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get financial report: {str(e)}"
        )


@router.post(
    "/ratios",
    summary="获取财务比率",
    description="获取关键财务比率（PE、PB、ROE等）",
)
async def get_financial_ratios(
    symbol: str = Query(..., description="股票代码")
) -> Dict[str, Any]:
    """获取财务比率"""
    try:
        logger.info("API: get_financial_ratios called", symbol=symbol)

        result = await fundamental_use_cases.get_fundamental_analysis(symbol)

        ratios_data = result.get("ratios", result)

        return rest_response(data=ratios_data, symbol=symbol)

    except Exception as e:
        logger.error(f"API error in get_financial_ratios: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get financial ratios: {str(e)}"
        )


@router.post(
    "/forecast",
    summary="获取盈利预测",
    description="获取机构对指定股票的盈利预测数据",
)
async def get_profit_forecast(
    symbol: str = Query(..., description="股票代码")
) -> Dict[str, Any]:
    """获取盈利预测"""
    try:
        logger.info("API: get_profit_forecast called", symbol=symbol)

        result = await fundamental_use_cases.get_profit_forecast(symbol)

        return rest_response(data=result, symbol=symbol)

    except Exception as e:
        logger.error(f"API error in get_profit_forecast: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get profit forecast: {str(e)}"
        )


# ------------------------------------------------------------------
# Gateway-based GET endpoints
# ------------------------------------------------------------------

@router.get(
    "/main-business",
    summary="主营业务构成",
    description="按产品/地区/板块拆分主营业务收入",
)
async def get_main_business(
    symbol: str = Query(..., description="股票代码 (如 600519)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_mainbz_info", symbol=symbol)
        result = await Container.market_gateway().get_mainbz_info(symbol)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_mainbz_info: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get main business: {str(e)}",
        )


@router.get(
    "/shareholders",
    summary="股东信息",
    description="前十大股东及高管持股变动",
)
async def get_shareholder_info(
    symbol: str = Query(..., description="股票代码 (如 600519)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_shareholder_info", symbol=symbol)
        result = await Container.market_gateway().get_shareholder_info(symbol)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_shareholder_info: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get shareholder info: {str(e)}",
        )


@router.get(
    "/dividends",
    summary="分红信息",
    description="分红历史/股息率/送配记录",
)
async def get_dividend_info(
    symbol: str = Query(..., description="股票代码 (如 600519)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_dividend_info", symbol=symbol)
        result = await Container.market_gateway().get_dividend_info(symbol)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_dividend_info: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get dividend info: {str(e)}",
        )


@router.get(
    "/valuation",
    summary="估值指标",
    description="PE/PB/PS/股息率等估值指标",
)
async def get_valuation_metrics(
    symbol: str = Query(..., description="股票代码 (如 600519)"),
) -> Dict[str, Any]:
    try:
        logger.info("API: get_valuation_metrics", symbol=symbol)
        result = await Container.market_gateway().get_valuation_metrics(symbol)
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_valuation_metrics: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get valuation metrics: {str(e)}",
        )
