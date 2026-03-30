# src/server/mcp/tools/asset_tools.py
"""MCP tools for asset search and management.
Provides asset search, price queries, and asset information retrieval.
Returns structured data (JSON).

Active Tools (4):
  - get_kline_data: 获取K线历史价格数据
  - get_asset_info: 获取资产基本信息 (名称/交易所/行业/市值等)
  - get_real_time_price: 获取实时价格
  - get_multiple_prices: 批量获取多个资产实时价格

Disabled Tools:
  - get_market_report: 🔇 聚合工具，应由 Agent 层调用原子工具组合
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP, Context

from src.server.core.use_cases import market as market_use_cases
from src.server.domain.types import AssetType
from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    create_artifact_envelope,
    create_artifact_response,
    create_symbol_error_response,
)
from src.server.domain.symbols.errors import SymbolResolutionError


# ============================================================
# MCP 工具注册 (保持原有接口不变)
# ============================================================


def register_asset_tools(mcp: FastMCP):
    """Register asset-related tools."""


    @mcp.tool(tags={"asset"})
    async def get_asset_info(ticker: str, ctx: Context = None) -> Dict[str, Any]:
        """获取资产详情 (名称/行业/上市日期等).

        WHEN TO USE: 用户已有确定代码, 想了解公司基本属性(行业/市值/上市日期).
        CONCEPT: 返回资产主数据的完整画像, 包含 name, exchange, industry, list_date, market_cap 等.
        DIFFERENTIATION: 比 search_assets 更详细; 不包含实时行情(用 get_real_time_price).
        next_recommended_tools: get_real_time_price -> get_multiple_prices"""
        if ctx:
            await ctx.info(f"🔧 获取资产信息: {ticker}", extra={"ticker": ticker})

        try:
            logger.info("MCP tool called: get_asset_info", ticker=ticker)
            asset = await market_use_cases.get_asset_info(ticker)
            if asset:
                result = asset
                result["component_type"] = "asset_info"
                
                if ctx:
                    await ctx.info(f"✅ 获取资产信息完成: {ticker}")
                
                # 构造 Artifact
                artifact = create_artifact_envelope(
                    component_type="asset_info",
                    name=f"{ticker} 资产信息",
                    content=result,
                    description=f"{result.get('name')} ({ticker}) 基本信息",
                )
                
                # 构造 Summary
                summary = (
                    f"已获取 {result.get('name')} ({ticker}) 的基本信息。\\n"
                    f"行业：{result.get('industry')}\\n"
                    f"市值：{result.get('market_cap')}"
                )
                
                return create_artifact_response(summary=summary, artifact=artifact)
            
            if ctx:
                await ctx.warning(f"⚠️ 未找到资产信息: {ticker}")

            return {
                "error": f"Asset not found: {ticker}",
                "component_type": "asset_info",
            }

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败: {ticker}", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="asset_info", name=f"{ticker} 资产信息"
            )
        except Exception as e:
            logger.error(f"Get asset info failed: {e}")
            if ctx:
                await ctx.error(
                    f"❌ 获取资产信息失败: {ticker}",
                    extra={"error": str(e)}
                )
            return {"error": str(e), "component_type": "asset_info"}

    @mcp.tool(tags={"asset"})
    async def get_real_time_price(ticker: str, ctx: Context = None) -> Dict[str, Any]:
        """获取单个资产实时行情.

        WHEN TO USE: 用户要当前最新价/涨跌幅/成交量, 且只查一只.
        CONCEPT: 返回最新 tick 数据: price, change_pct, volume, turnover 等.
        DIFFERENTIATION: 单个标的; 如需批量请用 get_multiple_prices.
        next_recommended_tools: get_multiple_prices -> search_assets"""
        if ctx:
            await ctx.info(f"🔧 获取实时价格: {ticker}", extra={"ticker": ticker})

        try:
            logger.info("MCP tool called: get_real_time_price", ticker=ticker)
            price = await market_use_cases.get_real_time_price(ticker)
            if price:
                result = price
                result["component_type"] = "real_time_price"
                
                if ctx:
                    await ctx.info(
                        f"✅ 获取实时价格完成: {ticker}",
                        extra={"price": result.get("price")}
                    )

                # 构造 Artifact
                artifact = create_artifact_envelope(
                    component_type="real_time_price",
                    name=f"{ticker} 实时报价",
                    content=result,
                    description=(
                        f"{ticker} 当前价格: {result.get('price')} {result.get('currency')}"
                    ),
                )
                
                # 构造 Summary
                summary = (
                    f"{ticker} 最新价 {result.get('price')} {result.get('currency')}，"
                    f"涨跌幅 {result.get('change_percent')}%"
                )

                return create_artifact_response(summary=summary, artifact=artifact)
            
            if ctx:
                await ctx.warning(f"⚠️ 未找到实时价格: {ticker}")

            return {
                "error": f"Price not found for {ticker}",
                "component_type": "real_time_price",
            }

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败: {ticker}", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="real_time_price", name=f"{ticker} 实时报价"
            )
        except Exception as e:
            logger.error(f"Get real-time price failed: {e}")
            if ctx:
                await ctx.error(
                    f"❌ 获取实时价格失败: {ticker}",
                    extra={"error": str(e)}
                )
            return {"error": str(e), "component_type": "real_time_price"}

    @mcp.tool(tags={"asset"})
    async def get_multiple_prices(tickers: list[str], ctx: Context = None) -> Dict[str, Any]:
        """批量获取多个资产实时行情.

        WHEN TO USE: 用户同时查多只股票/基金/ETF的实时价格.
        CONCEPT: 一次请求多个标的实时行情, 效率高于多次调用 get_real_time_price.
        DIFFERENTIATION: 批量版 get_real_time_price; 若只需一只用 get_real_time_price 更简单.
        next_recommended_tools: get_real_time_price -> get_asset_info"""
        if ctx:
            await ctx.info(
                f"🔧 批量获取价格: {len(tickers)}个资产",
                extra={"tickers": tickers}
            )

        try:
            result = await market_use_cases.get_multiple_prices(tickers)
            result["component_type"] = "multiple_prices"
            
            if ctx:
                await ctx.info(f"✅ 批量获取价格完成: {len(result)}个结果")

            # 构造 Artifact
            artifact = create_artifact_envelope(
                component_type="multiple_prices",
                name="批量实时报价",
                content=result,
                description=f"包含 {len(tickers)} 个资产的实时价格",
            )
            
            # 构造 Summary
            summary = f"已获取 {len(tickers)} 个资产的实时价格。"

            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="multiple_prices", name="批量实时报价"
            )
        except Exception as e:
            logger.error(f"MCP tool error in get_multiple_prices: {e}", exc_info=True)
            if ctx:
                await ctx.error(
                    f"❌ 批量获取价格失败",
                    extra={"error": str(e)}
                )
            return {"error": str(e), "component_type": "multiple_prices"}

    @mcp.tool(tags={"asset"})
    async def get_kline_data(
        ticker: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        interval: str = "1d",
        ctx: Context = None
    ) -> Dict[str, Any]:
        """Get K-line historical price data (daily by default).

        WHEN TO USE:
        - Need historical OHLCV candlestick data for charting or technical analysis
        - Backtesting trading strategies on historical price data
        - Computing technical indicators (MA, RSI, MACD) from raw price data

        CONCEPT:
        Returns historical K-line (candlestick) data: open, high, low, close, volume.
        Supports A-share, US stock, and crypto markets. Configurable interval and date range.

        DIFFERENTIATION:
        - vs get_real_time_price: This returns historical time-series; real_time returns current snapshot
        - vs get_us_price_history: This is multi-market; us_price_history is US-only
        - vs get_technical_indicators: This returns raw OHLCV; technical calculates derived indicators

        next_recommended_tools: get_real_time_price, get_technical_indicators, get_asset_info

        Args:
            ticker: Asset ticker. Format: EXCHANGE:SYMBOL
                - A股: SSE:600519 (上交所), SZSE:000001 (深交所)
                - 美股: NASDAQ:AAPL, NYSE:TSLA
                - 加密货币: CRYPTO:BTC, CRYPTO:ETH
            start_date: Start date (YYYY-MM-DD), optional. Defaults to 1 year ago.
            end_date: End date (YYYY-MM-DD), optional. Defaults to today.
            interval: Data interval (1d=daily, 1wk=weekly, 1mo=monthly). Default: 1d
            ctx: FastMCP Context for logging

        Returns:
            Dictionary containing historical price data list
        """
        # 设置默认日期：end_date 默认今天，start_date 默认一年前
        today = datetime.now()
        if end_date is None:
            end_date = today.strftime("%Y-%m-%d")
        if start_date is None:
            # 默认获取最近一年的数据
            one_year_ago = today.replace(year=today.year - 1)
            start_date = one_year_ago.strftime("%Y-%m-%d")

        if ctx:
            await ctx.info(
                f"🔧 获取历史价格: {ticker}",
                extra={"ticker": ticker, "start": start_date, "end": end_date, "interval": interval}
            )

        try:
            logger.info(
                "MCP tool called: get_kline_data",
                ticker=ticker,
                start=start_date,
                end=end_date,
            )

            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")

            prices = await market_use_cases.get_historical_prices(
                ticker=ticker, start_date=start, end_date=end, interval=interval
            )
            
            if ctx:
                await ctx.info(
                    f"✅ 获取历史价格完成: {ticker}",
                    extra={"count": len(prices)}
                )

            result = {
                "component_type": "price_chart",
                "symbol": ticker,
                "data": prices,
            }

            description = f"{ticker}历史价格: {start_date}至{end_date}, 共{len(prices)}条数据"

            artifact = create_artifact_envelope(
                component_type="price_chart",
                name=f"{ticker} 历史价格",
                content=result,
                description=description,
                visible_to_llm=False,
                display_in_report=True,
            )
            
            return create_artifact_response(summary=description, artifact=artifact)

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败: {ticker}", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="price_chart", name=f"{ticker} 历史价格"
            )
        except Exception as e:
            logger.error(f"Get historical prices failed: {e}")
            if ctx:
                await ctx.error(
                    f"❌ 获取历史价格失败: {ticker}",
                    extra={"error": str(e)}
                )
            return {"error": str(e), "component_type": "kline_chart"}
