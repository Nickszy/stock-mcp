# src/server/mcp/tools/index_tools.py
"""MCP tools for A-share index data.

Tools:
  - get_index_list: List all A-share indices
  - get_index_pe_pb: Index PE/PB valuation history
  - get_index_performance: Index price history with returns
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


# Common indices for reference
MAJOR_INDICES = {
    "000001": "上证指数", "000300": "沪深300", "000905": "中证500",
    "000852": "中证1000", "399006": "创业板指", "000688": "科创50",
    "000016": "上证50", "399673": "创业板50",
}


def register_index_tools(mcp: FastMCP):
    """Register index data MCP tools."""

    # ------------------------------------------------------------------
    # get_index_list — A股指数列表
    # ------------------------------------------------------------------
    @mcp.tool(tags={"index", "list"})
    async def get_index_list(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股全部指数列表：代码、名称、发布日期。

        Typical use cases:
        - "有哪些A股指数？"
        - "查找代码包含'000'的指数"

        Returns:
            List of all A-share indices with code, name, publish date.
        """
        if ctx:
            await ctx.info("获取A股指数列表")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_index_list")

            result = await Container.market_gateway().get_index_list()

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"A股指数列表: 共 {total} 个指数 (耗时 {elapsed:.1f}s)"

            # Markdown output — show first 30
            md = f"## A股指数列表\n\n"
            md += f"**总数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 代码 | 名称 | 发布日期 |\n|------|------|--------|\n"
            for r in results[:30]:
                md += f"| {r.get('index_code', '')} | {r.get('index_name', '')} | {r.get('publish_date', '')} |\n"
            if total > 30:
                md += f"\n*... 还有 {total - 30} 个指数*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="A股指数列表",
                data=results,
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_index_list failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取指数列表失败: {e}",
                component_type=ComponentType.TABLE,
                name="指数列表错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取指数列表失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_index_pe_pb — 指数估值PE/PB历史
    # ------------------------------------------------------------------
    @mcp.tool(tags={"index", "valuation"})
    async def get_index_pe_pb(
        symbol: str = "沪深300",
        limit: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取指数估值(PE/PB)历史数据。

        Typical use cases:
        - "沪深300最近的PE/PB是多少？"
        - "创业板指估值历史趋势"

        Args:
            symbol: 指数名称 (如 '沪深300', '上证50', '中证500', '创业板指')
            limit: 返回最近N条 (default 30, max 100)
            ctx: FastMCP Context.

        Returns:
            Index PE/PB time series data.
        """
        if ctx:
            await ctx.info(f"获取指数估值: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_index_pe_pb", symbol=symbol)

            result = await Container.market_gateway().get_index_pe_pb(
                symbol=symbol, limit=limit,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"指数估值({symbol}): {total}条历史, 返回{len(results)}条 ({elapsed:.1f}s)"

            md = f"## 指数估值: {symbol}\n\n"
            md += f"**历史总数**: {total} | **返回**: {len(results)} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 日期 | PE | PB |\n|------|-----|-----|\n"
            for r in results:
                md += f"| {r.get('date', '')} | {_safe_fmt(r.get('pe'))} | {_safe_fmt(r.get('pb'))} |\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"指数估值: {symbol}",
                data=results,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
                limit=limit,
            )

        except Exception as e:
            logger.error(f"get_index_pe_pb failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取指数估值失败: {e}",
                component_type=ComponentType.TABLE,
                name="指数估值错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取指数估值失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_index_performance — 指数行情历史
    # ------------------------------------------------------------------
    @mcp.tool(tags={"index", "performance"})
    async def get_index_performance(
        symbol: str = "000300",
        period: str = "daily",
        start_date: str = "",
        end_date: str = "",
        limit: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取指数行情历史：开盘/收盘/最高/最低/成交量/涨跌幅。

        Typical use cases:
        - "沪深300最近60个交易日走势"
        - "上证指数2025年以来的日K数据"
        - "创业板指月线数据"

        Args:
            symbol: 指数代码 (如 '000300'=沪深300, '000001'=上证指数, '399006'=创业板指)
            period: 周期 (daily/weekly/monthly, 默认daily)
            start_date: 开始日期 (如 '20250101', 可选)
            end_date: 结束日期 (如 '20260328', 可选)
            limit: 返回最近N条 (default 60, max 500)
            ctx: FastMCP Context.

        Returns:
            Index price history with OHLCV and change_pct.
        """
        # Resolve friendly name to code if needed
        resolved_symbol = symbol
        for code, name in MAJOR_INDICES.items():
            if symbol == name or symbol == code:
                resolved_symbol = code
                break

        if ctx:
            await ctx.info(f"获取指数行情: {resolved_symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_index_performance", symbol=resolved_symbol)

            result = await Container.market_gateway().get_index_performance(
                symbol=resolved_symbol, period=period,
                start_date=start_date, end_date=end_date, limit=limit,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            idx_name = MAJOR_INDICES.get(resolved_symbol, resolved_symbol)
            summary = f"指数行情({idx_name}): {total}条, 返回{len(results)}条 ({elapsed:.1f}s)"

            md = f"## 指数行情: {idx_name} ({resolved_symbol})\n\n"
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
                name=f"指数行情: {idx_name}",
                data=results,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=resolved_symbol,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
            )

        except Exception as e:
            logger.error(f"get_index_performance failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取指数行情失败: {e}",
                component_type=ComponentType.TABLE,
                name="指数行情错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取指数行情失败: {e}",
            )
