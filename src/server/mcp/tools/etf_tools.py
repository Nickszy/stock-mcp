# src/server/mcp/tools/etf_tools.py
"""MCP tools for A-share ETF data.

Tools:
  - get_etf_list: ETF list with real-time quotes
  - get_etf_detail: Single ETF detail info
  - get_etf_performance: ETF price history with OHLCV
"""

import math
from typing import Any, Dict, List, Optional
import time

from fastmcp import FastMCP, Context

from src.server.core.dependencies import Container
from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_standard_artifact_response,
)


def _safe_fmt(value: Any, fmt: str = ".2f") -> str:
    """Format a numeric value safely."""
    if value is None:
        return "-"
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return "-"
        return format(f, fmt)
    except (TypeError, ValueError):
        return "-"


def _fmt_pct(value: Any) -> str:
    """Format a percentage with sign."""
    if value is None:
        return "-"
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return "-"
        return f"{f:+.2f}%"
    except (TypeError, ValueError):
        return "-"


def register_etf_tools(mcp: FastMCP):
    """Register ETF data MCP tools."""

    # ------------------------------------------------------------------
    # get_etf_list — ETF列表（实时行情）
    # ------------------------------------------------------------------
    @mcp.tool(tags={"etf", "list"})
    async def get_etf_list(
        etf_type: str = "",
        limit: int = 50,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股ETF列表及实时行情。

        WHEN TO USE:
        - Browse or filter ETFs (types, top volume, sector ETF codes)
        - Find sector ETF codes for sector/industry analysis
        - Screen ETFs by type for portfolio construction

        CONCEPT:
        ETF list tool returning real-time quotes filtered by type
        (stock/bond/commodity/cross-border). Returns price, change%, amount, turnover.

        DIFFERENTIATION:
        - vs get_etf_detail: This returns ETF list overview; detail returns single ETF info
        - vs get_index_constituents: This returns ETF funds; index returns index constituents

        next_recommended_tools: get_etf_detail, get_etf_performance, get_index_fact_pack

        Args:
            etf_type: ETF类型筛选 (股票型/债券型/商品型/跨境型, 空=全部)
            limit: 返回数量 (default 50, max 500)
            ctx: FastMCP Context.

        Returns:
            ETF list with real-time price/volume/change data.
        """
        if ctx:
            await ctx.info(f"获取ETF列表: type={etf_type}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_etf_list", etf_type=etf_type)

            result = await Container.market_gateway().get_etf_list(
                etf_type=etf_type, limit=limit,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"ETF列表: 共{total}只, 返回{len(results)}只 (耗时 {elapsed:.1f}s)"

            md = f"## ETF列表 ({etf_type or '全部'})\n\n"
            md += f"**总数**: {total} | **返回**: {len(results)} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 代码 | 名称 | 最新价 | 涨跌幅% | 成交额 | 换手率 |\n"
            md += "|------|------|--------|--------|--------|--------|\n"
            for r in results:
                md += (
                    f"| {r.get('etf_code', '')} "
                    f"| {r.get('etf_name', '')} "
                    f"| {_safe_fmt(r.get('price'))} "
                    f"| {_fmt_pct(r.get('change_pct'))} "
                    f"| {_safe_fmt(r.get('amount'), '.0f')} "
                    f"| {_safe_fmt(r.get('turnover'))} |\n"
                )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="ETF列表",
                data=results,
                source="akshare",
                description=summary,
                markdown=md,
                limit=limit,
            )

        except Exception as e:
            logger.error(f"get_etf_list failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取ETF列表失败: {e}",
                component_type=ComponentType.TABLE,
                name="ETF列表错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取ETF列表失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_etf_detail — ETF详情
    # ------------------------------------------------------------------
    @mcp.tool(tags={"etf", "detail"})
    async def get_etf_detail(
        symbol: str = "510300",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取单只ETF详情信息。

        WHEN TO USE:
        - User has identified an ETF code and wants full details
        - Compare ETF fees, size, tracking error across candidates
        - Evaluate ETF liquidity and premium/discount levels

        CONCEPT:
        Single ETF detail query returning NAV, cumulative NAV, premium/discount,
        IOPV, management fee, custody fee, inception date, fund size, tracking index.

        DIFFERENTIATION:
        - vs get_etf_list: This returns full detail for one ETF; list returns overview of many
        - vs get_etf_performance: This returns fund attributes; performance returns price K-line
        - vs get_fund_detail: This is ETF-specific; fund_detail is for open-end mutual funds

        next_recommended_tools: get_etf_performance, get_etf_list, get_index_fact_pack

        Args:
            symbol: ETF代码 (如 '510300'=华泰柏瑞沪深300ETF)
            ctx: FastMCP Context.

        Returns:
            ETF detail info including NAV, cumulative NAV, daily change.
        """
        if ctx:
            await ctx.info(f"获取ETF详情: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_etf_detail", symbol=symbol)

            result = await Container.market_gateway().get_etf_detail(symbol=symbol)

            elapsed = time.perf_counter() - t0
            detail = result.get("detail", {})

            summary = f"ETF详情({symbol}): 获取成功 ({elapsed:.1f}s)"

            md = f"## ETF详情: {symbol}\n\n"
            md += f"**耗时**: {elapsed:.1f}s\n\n"
            md += "| 字段 | 值 |\n|------|----|\n"
            for k, v in detail.items():
                if v is not None:
                    md += f"| {k} | {v} |\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"ETF详情: {symbol}",
                data=detail,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_etf_detail failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取ETF详情失败: {e}",
                component_type=ComponentType.TABLE,
                name="ETF详情错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取ETF详情失败: {e}",
                symbol=symbol,
            )

    # ------------------------------------------------------------------
    # get_etf_performance — ETF行情历史
    # ------------------------------------------------------------------
    @mcp.tool(tags={"etf", "performance"})
    async def get_etf_performance(
        symbol: str = "510300",
        period: str = "daily",
        start_date: str = "",
        end_date: str = "",
        limit: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取ETF行情历史.

        WHEN TO USE:
        - Analyze ETF price trends over time
        - Calculate technical indicators (MA, RSI, MACD) from raw OHLCV data
        - Backtest ETF strategies or compare performance across periods

        CONCEPT:
        ETF price history returning OHLCV (Open/High/Low/Close/Volume) K-line data.
        Supports daily/weekly/monthly periods. Fields: date, open, close, high,
        low, volume, amount, change_pct. Suitable for technical analysis.

        DIFFERENTIATION:
        - vs get_etf_detail: This returns time-series data; detail returns fund snapshot
        - vs get_us_price_history: This is for A-share ETFs; us_price_history is for US stocks
        - vs get_kline_data: get_kline_data is for individual stocks; this is ETF-specific

        next_recommended_tools: get_etf_detail, get_us_technical_indicators, get_etf_list

        Args:
            symbol: ETF代码 (如 '510300'=沪深300ETF, '513100'=纳指ETF)
            period: 周期 (daily/weekly/monthly, 默认daily)
            start_date: 开始日期 (如 '20260101', 可选)
            end_date: 结束日期 (如 '20260328', 可选)
            limit: 返回最近N条 (default 60, max 500)
            ctx: FastMCP Context.

        Returns:
            ETF price history with OHLCV and change_pct.
        """
        if ctx:
            await ctx.info(f"获取ETF行情: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_etf_performance", symbol=symbol)

            result = await Container.market_gateway().get_etf_performance(
                symbol=symbol, period=period,
                start_date=start_date, end_date=end_date, limit=limit,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"ETF行情({symbol}): {total}条, 返回{len(results)}条 ({elapsed:.1f}s)"

            md = f"## ETF行情: {symbol}\n\n"
            md += f"**周期**: {period} | **总数**: {total} | **返回**: {len(results)} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 日期 | 开盘 | 收盘 | 最高 | 最低 | 涨跌幅% | 成交量 | 成交额 |\n"
            md += "|------|------|------|------|------|--------|--------|--------|\n"
            for r in results:
                md += (
                    f"| {r.get('date', '')} "
                    f"| {_safe_fmt(r.get('open'))} "
                    f"| {_safe_fmt(r.get('close'))} "
                    f"| {_safe_fmt(r.get('high'))} "
                    f"| {_safe_fmt(r.get('low'))} "
                    f"| {_fmt_pct(r.get('change_pct'))} "
                    f"| {_safe_fmt(r.get('volume'), '.0f')} "
                    f"| {_safe_fmt(r.get('amount'), '.0f')} |\n"
                )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"ETF行情: {symbol}",
                data=results,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
            )

        except Exception as e:
            logger.error(f"get_etf_performance failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取ETF行情失败: {e}",
                component_type=ComponentType.TABLE,
                name="ETF行情错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取ETF行情失败: {e}",
                symbol=symbol,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
            )
