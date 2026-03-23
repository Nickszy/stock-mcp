# src/server/api/routes/fundamental.py
"""Fundamental analysis API routes.

Provides RESTful HTTP endpoints for fundamental/financial data.
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import Dict, Any
from src.server.utils.logger import logger
from src.server.core.use_cases import fundamental as fundamental_use_cases

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
    - 利润表 (income_statement): 营收、净利润等
    - 资产负债表 (balance_sheet): 资产、负债等
    - 现金流量表 (cash_flow): 经营/投资/筹资现金流
    - 财务指标 (financial_indicators): EPS、ROE、ROA等
    - 市场指标 (market_metrics): PE、PB、市值等
    """,
)
async def get_financials(
    symbol: str = Query(..., description="股票代码 (格式: EXCHANGE:SYMBOL)")
) -> Dict[str, Any]:
    """获取财务报表数据（利润表、资产负债表、现金流量表等）"""
    try:
        logger.info("API: get_financials called", symbol=symbol)

        result = await fundamental_use_cases.get_financials(symbol)

        return result

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
        # 标准化 ticker
        logger.info(
            "API: get_financial_report called",
            symbol=symbol
        )
        
        result = await fundamental_use_cases.get_fundamental_analysis(symbol)
        
        return result
        
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
        
        # 获取完整分析并提取比率部分
        result = await fundamental_use_cases.get_fundamental_analysis(symbol)
        
        # 如果有比率数据，返回它；否则返回整体结果
        if "ratios" in result:
            return {
                "symbol": result.get("ticker", symbol),
                "ratios": result["ratios"]
            }
        
        return result
        
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

        return result

    except Exception as e:
        logger.error(f"API error in get_profit_forecast: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get profit forecast: {str(e)}"
        )
