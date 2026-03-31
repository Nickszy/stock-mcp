# src/server/mcp/tools/market_activity_tools.py
"""MCP tools for A-share market activity monitoring.

Exposes:
  - get_limit_up_pool: 涨停池
  - get_limit_down_pool: 跌停池
  - get_hot_stock_rank: 个股热度榜
  - get_sector_change_alert: 板块异动
"""

import time
from typing import Any, Dict

from fastmcp import FastMCP, Context

from src.server.core.dependencies import Container
from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_standard_artifact_response,
)


def register_market_activity_tools(mcp: FastMCP):
    """Register market activity MCP tools."""

    @mcp.tool(tags={"market-activity", "limit-up"})
    async def get_limit_up_pool(
        date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股涨停池数据。"""
        if ctx:
            await ctx.info(f"获取涨停池: date={date or 'latest'}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_limit_up_pool", date=date)

            gateway = Container.market_gateway()
            result = await gateway.get_limit_up_pool(date=date)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            resolved_date = result.get("date", date)

            summary = f"涨停池({resolved_date}): 共{total}只 (耗时 {elapsed:.1f}s)"
            md = f"## 涨停池 - {resolved_date}\n\n"
            md += f"**股票数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            if data:
                md += "| 代码 | 名称 | 涨跌幅 | 连板数 | 首封时间 | 所属行业 |\n"
                md += "|------|------|--------|--------|----------|----------|\n"
                for r in data[:50]:
                    md += (
                        f"| {r.get('stock_code', '')} | {r.get('stock_name', '')} "
                        f"| {r.get('pct_change', '-')} | {r.get('limit_up_streak', '-')} "
                        f"| {r.get('first_limit_time', '-')} | {r.get('industry', '-')} |\n"
                    )
                if total > 50:
                    md += f"\n*... 还有 {total - 50} 只*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"涨停池: {resolved_date}",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
            )
        except Exception as e:
            logger.error(f"get_limit_up_pool failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取涨停池失败: {e}",
                component_type=ComponentType.TABLE,
                name="涨停池错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取涨停池失败: {e}",
            )

    @mcp.tool(tags={"market-activity", "limit-down"})
    async def get_limit_down_pool(
        date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股跌停池数据。"""
        if ctx:
            await ctx.info(f"获取跌停池: date={date or 'latest'}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_limit_down_pool", date=date)

            gateway = Container.market_gateway()
            result = await gateway.get_limit_down_pool(date=date)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            resolved_date = result.get("date", date)

            summary = f"跌停池({resolved_date}): 共{total}只 (耗时 {elapsed:.1f}s)"
            md = f"## 跌停池 - {resolved_date}\n\n"
            md += f"**股票数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            if data:
                md += "| 代码 | 名称 | 涨跌幅 | 连续跌停 | 开板次数 | 所属行业 |\n"
                md += "|------|------|--------|----------|----------|----------|\n"
                for r in data[:50]:
                    md += (
                        f"| {r.get('stock_code', '')} | {r.get('stock_name', '')} "
                        f"| {r.get('pct_change', '-')} | {r.get('limit_down_streak', '-')} "
                        f"| {r.get('open_board_count', '-')} | {r.get('industry', '-')} |\n"
                    )
                if total > 50:
                    md += f"\n*... 还有 {total - 50} 只*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"跌停池: {resolved_date}",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
            )
        except Exception as e:
            logger.error(f"get_limit_down_pool failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取跌停池失败: {e}",
                component_type=ComponentType.TABLE,
                name="跌停池错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取跌停池失败: {e}",
            )

    @mcp.tool(tags={"market-activity", "hot-rank"})
    async def get_hot_stock_rank(
        symbol: str = "全部股票",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股个股热度榜。"""
        if ctx:
            await ctx.info(f"获取个股热度榜: symbol={symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_hot_stock_rank", symbol=symbol)

            gateway = Container.market_gateway()
            result = await gateway.get_hot_stock_rank(symbol=symbol)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            resolved_symbol = result.get("symbol", symbol)

            summary = f"个股热度榜({resolved_symbol}): 共{total}条 (耗时 {elapsed:.1f}s)"
            md = f"## 个股热度榜 - {resolved_symbol}\n\n"
            md += f"**条数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            if data:
                md += "| 排名 | 代码 | 名称 | 最新价 | 涨跌幅 |\n"
                md += "|------|------|------|--------|--------|\n"
                for r in data[:50]:
                    md += (
                        f"| {r.get('rank', '-')} | {r.get('stock_code', '')} | {r.get('stock_name', '')} "
                        f"| {r.get('latest_price', '-')} | {r.get('pct_change', '-')} |\n"
                    )
                if total > 50:
                    md += f"\n*... 还有 {total - 50} 条*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"个股热度榜: {resolved_symbol}",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
                symbol=resolved_symbol,
            )
        except Exception as e:
            logger.error(f"get_hot_stock_rank failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取个股热度榜失败: {e}",
                component_type=ComponentType.TABLE,
                name="个股热度榜错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取个股热度榜失败: {e}",
            )

    @mcp.tool(tags={"market-activity", "sector-change"})
    async def get_sector_change_alert(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股板块异动数据。"""
        if ctx:
            await ctx.info("获取板块异动")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_sector_change_alert")

            gateway = Container.market_gateway()
            result = await gateway.get_sector_change_alert()

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)

            summary = f"板块异动: 共{total}条 (耗时 {elapsed:.1f}s)"
            md = "## 板块异动\n\n"
            md += f"**条数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            if data:
                md += "| 时间 | 板块 | 涨跌幅 | 主力净流入 | 异动次数 |\n"
                md += "|------|------|--------|------------|----------|\n"
                for r in data[:50]:
                    md += (
                        f"| {r.get('time', '-')} | {r.get('sector_name', '')} | {r.get('pct_change', '-')} "
                        f"| {r.get('main_net_inflow', '-')} | {r.get('change_count', '-')} |\n"
                    )
                if total > 50:
                    md += f"\n*... 还有 {total - 50} 条*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="板块异动",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
            )
        except Exception as e:
            logger.error(f"get_sector_change_alert failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取板块异动失败: {e}",
                component_type=ComponentType.TABLE,
                name="板块异动错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取板块异动失败: {e}",
            )
