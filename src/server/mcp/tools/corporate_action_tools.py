# src/server/mcp/tools/corporate_action_tools.py
"""MCP tools for A-share corporate action data (COL-147).

Tools:
  - get_shareholder_holding_detail: 股东增减持明细
  - get_ipo_calendar: 新股IPO日历
  - get_ipo_info: 个股IPO详情
"""

import math
from typing import Any, Dict
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


def register_corporate_action_tools(mcp: FastMCP):
    """Register corporate action MCP tools."""

    # ------------------------------------------------------------------
    # get_shareholder_holding_detail — 股东增减持明细
    # ------------------------------------------------------------------
    @mcp.tool(tags={"corporate-action", "shareholder"})
    async def get_shareholder_holding_detail(
        symbol: str = "",
        date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取股东增减持明细数据（十大流通股东维度）。

        查询个股或全市场股东持股变动明细，包括股东名称、持股数量、变动方向、变动数量等。

        Typical use cases:
        - "查看688235最新的股东增减持明细"
        - "查询2024Q3全市场流通股东持股变动"
        - "查看某只股票机构股东最新持仓变化"

        Args:
            symbol: 股票代码 (如 688235, 600519), 为空返回全市场
            date: 季度日期 (如 20240930, 20240630)
            ctx: FastMCP Context.

        Returns:
            股东增减持明细数据
        """
        if ctx:
            await ctx.info(f"获取股东增减持明细: symbol={symbol}, date={date}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_shareholder_holding_detail", symbol=symbol, date=date)

            gateway = Container.market_gateway()
            result = await gateway.get_shareholder_holding_detail(
                symbol=symbol, date=date,
            )

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)

            summary = f"股东增减持明细{': ' + symbol if symbol else '(全市场)'}"
            summary += f" 共{total}条 (耗时 {elapsed:.1f}s)"

            md = f"## 股东增减持明细{' - ' + symbol if symbol else ' - 全市场'}\n\n"
            md += f"**日期**: {date or '最新'} | **记录数**: {total} | **耗时**: {elapsed:.1f}s\n\n"

            if data:
                md += "| 股东名称 | 类型 | 股票代码 | 股票名称 | 持股数量 | 变动方向 | 变动比例 |\n"
                md += "|---------|------|---------|---------|---------|---------|----------|\n"
                for r in data[:30]:
                    md += (
                        f"| {r.get('holder_name', '')} "
                        f"| {r.get('holder_type', '')} "
                        f"| {r.get('stock_code', '')} "
                        f"| {r.get('stock_name', '')} "
                        f"| {r.get('hold_qty', '-')} "
                        f"| {r.get('hold_direction', '-')} "
                        f"| {_safe_fmt(r.get('hold_change_pct'))} |\n"
                    )
                if total > 30:
                    md += f"\n*... 还有 {total - 30} 条*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"股东增减持: {symbol or '全市场'}",
                data=data,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
                date=date,
            )

        except Exception as e:
            logger.error(f"get_shareholder_holding_detail failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取股东增减持明细失败: {e}",
                component_type=ComponentType.TABLE,
                name="股东增减持错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取股东增减持明细失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_ipo_calendar — 新股IPO日历
    # ------------------------------------------------------------------
    @mcp.tool(tags={"corporate-action", "ipo"})
    async def get_ipo_calendar(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取近期新股IPO/申购/上市日历。

        查询近期新股申购日期、发行价格、中签率、上市日期等信息。

        Typical use cases:
        - "最近有哪些新股申购？"
        - "查看近期IPO上市日历"
        - "下周有哪些新股申购？"

        Returns:
            IPO日历数据
        """
        if ctx:
            await ctx.info("获取新股IPO日历")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_ipo_calendar")

            gateway = Container.market_gateway()
            result = await gateway.get_ipo_calendar()

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)

            summary = f"IPO日历: 共{total}只新股 (耗时 {elapsed:.1f}s)"

            md = f"## 新股IPO日历\n\n"
            md += f"**总数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 代码 | 名称 | 申购日期 | 发行价 | 中签率 | 上市日期 |\n"
            md += "|------|------|---------|--------|--------|----------|\n"
            for r in data:
                md += (
                    f"| {r.get('stock_code', '')} "
                    f"| {r.get('stock_name', '')} "
                    f"| {r.get('subscribe_date', '-')} "
                    f"| {_safe_fmt(r.get('issue_price'))} "
                    f"| {_safe_fmt(r.get('online_win_rate'), '.4f')} "
                    f"| {r.get('listing_date', '-')} |\n"
                )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="新股IPO日历",
                data=data,
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_ipo_calendar failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取IPO日历失败: {e}",
                component_type=ComponentType.TABLE,
                name="IPO日历错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取IPO日历失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_ipo_info — 个股IPO详情
    # ------------------------------------------------------------------
    @mcp.tool(tags={"corporate-action", "ipo"})
    async def get_ipo_info(
        stock: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取个股IPO详情：发行价、市盈率、中签率、上市日期等。

        Typical use cases:
        - "查看贵州茅台(600519)的IPO信息"
        - "查看宁德时代(300750)上市时的发行价"

        Args:
            stock: 股票代码 (如 600519, 300750)
            ctx: FastMCP Context.

        Returns:
            IPO详情数据
        """
        if ctx:
            await ctx.info(f"获取IPO详情: {stock}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_ipo_info", stock=stock)

            gateway = Container.market_gateway()
            result = await gateway.get_ipo_info(stock=stock)

            elapsed = time.perf_counter() - t0
            info = result.get("data", {})
            summary = f"IPO详情: {stock} (耗时 {elapsed:.1f}s)"

            md = f"## IPO详情: {stock}\n\n"
            for k, v in info.items():
                md += f"- **{k}**: {v}\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"IPO详情: {stock}",
                data=info,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=stock,
            )

        except Exception as e:
            logger.error(f"get_ipo_info failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取IPO详情失败: {e}",
                component_type=ComponentType.TABLE,
                name="IPO详情错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取IPO详情失败: {e}",
            )
