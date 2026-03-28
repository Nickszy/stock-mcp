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
    create_artifact_envelope,
    create_artifact_response,
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

        Typical use cases:
        - "列出所有股票型ETF"
        - "成交额最大的ETF"
        - "债券型ETF有哪些"

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

            artifact = create_artifact_envelope(
                component_type=ComponentType.TABLE,
                name="ETF列表",
                content={"markdown": md, "data": results},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_etf_list failed: {e}")
            err = create_artifact_envelope(
                component_type=ComponentType.TABLE, name="ETF列表错误",
                content={"error": str(e)}, description=f"获取ETF列表失败: {e}",
            )
            return create_artifact_response(summary=f"获取ETF列表失败: {e}", artifact=err)

    # ------------------------------------------------------------------
    # get_etf_detail — ETF详情
    # ------------------------------------------------------------------
    @mcp.tool(tags={"etf", "detail"})
    async def get_etf_detail(
        symbol: str = "510300",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取单只ETF详情信息。

        Typical use cases:
        - "510300 沪深300ETF的详情"
        - "159919 嘉实300ETF的详细信息"

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

            artifact = create_artifact_envelope(
                component_type=ComponentType.TABLE,
                name=f"ETF详情: {symbol}",
                content={"markdown": md, "data": detail},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_etf_detail failed: {e}")
            err = create_artifact_envelope(
                component_type=ComponentType.TABLE, name="ETF详情错误",
                content={"error": str(e)}, description=f"获取ETF详情失败: {e}",
            )
            return create_artifact_response(summary=f"获取ETF详情失败: {e}", artifact=err)

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
        """获取ETF行情历史：开盘/收盘/最高/最低/成交量/涨跌幅。

        Typical use cases:
        - "沪深300ETF最近60个交易日走势"
        - "510300今年以来日K数据"
        - "纳指ETF月线数据"

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

            artifact = create_artifact_envelope(
                component_type=ComponentType.TABLE,
                name=f"ETF行情: {symbol}",
                content={"markdown": md, "data": results},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_etf_performance failed: {e}")
            err = create_artifact_envelope(
                component_type=ComponentType.TABLE, name="ETF行情错误",
                content={"error": str(e)}, description=f"获取ETF行情失败: {e}",
            )
            return create_artifact_response(summary=f"获取ETF行情失败: {e}", artifact=err)
