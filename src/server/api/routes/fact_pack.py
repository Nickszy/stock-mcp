# src/server/api/routes/fact_pack.py
"""Fact pack API routes.

Provides RESTful HTTP endpoints for aggregated fact pack data:
- Stock fact pack (COL-148)
- Fund fact pack (COL-150)
- Market fact pack (COL-152)
- US Stock fact pack (COL-164)
- ETF fact pack (COL-170)
- Index fact pack (COL-171)

Supports content negotiation:
  - JSON (default): standard REST envelope
  - Markdown: ?format=markdown or Accept: text/markdown
"""

from fastapi import APIRouter, HTTPException, Header, Query, status
from fastapi.responses import Response
from typing import Any, Dict, Optional

from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.domain.response_contract import rest_response, maybe_markdown_response

router = APIRouter(prefix="/api/v1/fact-pack")


def _wants_md(fmt: str, accept: str) -> bool:
    return fmt.lower() == "markdown" or "text/markdown" in accept


# ------------------------------------------------------------------
# get_stock_fact_pack
# ------------------------------------------------------------------
@router.get(
    "/stock/{symbol}",
    summary="获取股票事实包",
    tags=["A股个股 A-Share"],
    description=(
        "聚合全维度股票结构化事实数据: 证券主档、财务、市场估值、公司治理、"
        "事件(分红/回购/解禁)、业务结构。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_stock_fact_pack(
    symbol: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_stock_fact_pack", symbol=symbol)
        result = await Container.market_gateway().get_stock_fact_pack(symbol=symbol)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
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
    tags=["基金 Fund"],
    description=(
        "聚合全维度基金结构化事实数据: 基金主档、净值收益、持仓穿透、基金经理、"
        "规模份额、资产配置、费率分红、同类比较。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_fund_fact_pack(
    fund_code: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_fund_fact_pack", fund_code=fund_code)
        result = await Container.market_gateway().get_fund_fact_pack(fund_code=fund_code)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
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
    tags=["A股个股 A-Share"],
    description=(
        "聚合全维度行情结构化事实数据: 标的估值、技术快照、K线因子、资金流、"
        "市场广度、指数板块、衍生行情、相对强弱。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_market_fact_pack(
    symbol: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_market_fact_pack", symbol=symbol)
        result = await Container.market_gateway().get_market_fact_pack(symbol=symbol)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_market_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get market fact pack: {str(e)}",
        )


# ------------------------------------------------------------------
# get_us_stock_fact_pack (COL-164)
# ------------------------------------------------------------------
@router.get(
    "/us-stock/{ticker}",
    summary="获取美股事实包",
    tags=["美股个股 US Stock"],
    description=(
        "聚合全维度美股结构化事实数据: 公司档案、估值指标、财务健康、"
        "机构持仓与内部人交易、分析师评级与收入结构、量价技术分析。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_us_stock_fact_pack(
    ticker: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_us_stock_fact_pack", ticker=ticker)
        result = await Container.market_gateway().get_us_stock_fact_pack(ticker=ticker)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, symbol=ticker, source="yahoo")
    except Exception as e:
        logger.error(f"API error in get_us_stock_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get US stock fact pack: {str(e)}",
        )


# ------------------------------------------------------------------
# get_etf_fact_pack (COL-170)
# ------------------------------------------------------------------
@router.get(
    "/etf/{symbol}",
    summary="获取ETF事实包",
    tags=["指数与ETF Index & ETF"],
    description=(
        "聚合全维度ETF结构化事实数据: ETF主档、实时行情、历史表现、"
        "资金流/申赎、技术信号(RSI/MACD/BOLL)。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_etf_fact_pack(
    symbol: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_etf_fact_pack", symbol=symbol)
        result = await Container.market_gateway().get_etf_fact_pack(symbol=symbol)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_etf_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get ETF fact pack: {str(e)}",
        )


# ------------------------------------------------------------------
# get_index_fact_pack (COL-171)
# ------------------------------------------------------------------
@router.get(
    "/index/{symbol}",
    summary="获取指数事实包",
    tags=["指数与ETF Index & ETF"],
    description=(
        "聚合全维度指数结构化事实数据: 指数主档、PE/PB估值与历史分位、"
        "行情表现、成分股、技术信号(RSI/MACD/BOLL)。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_index_fact_pack(
    symbol: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_index_fact_pack", symbol=symbol)
        result = await Container.market_gateway().get_index_fact_pack(symbol=symbol)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, symbol=symbol, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_index_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get index fact pack: {str(e)}",
        )


@router.get(
    "/sector/{sector_name}",
    summary="获取行业事实包",
    tags=["行业 Sector"],
    description=(
        "聚合全维度行业结构化事实数据: 行业定位、成分股、结构快照、同业对比、"
        "证据摘要(资金流/PE-PB历史)。"
        "\n\n**Content negotiation**: `?format=markdown` 返回 Markdown 格式。"
    ),
)
async def get_sector_fact_pack(
    sector_name: str,
    format: str = Query("json", description="输出格式: json | markdown"),
    accept: Optional[str] = Header(default="", alias="Accept"),
):
    try:
        logger.info("API: get_sector_fact_pack", sector_name=sector_name)
        result = await Container.market_gateway().get_sector_fact_pack(sector_name=sector_name)
        md = maybe_markdown_response(result, format, accept or "")
        if md is not None:
            return md
        return rest_response(data=result, source="akshare")
    except Exception as e:
        logger.error(f"API error in get_sector_fact_pack: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get sector fact pack: {str(e)}",
        )
