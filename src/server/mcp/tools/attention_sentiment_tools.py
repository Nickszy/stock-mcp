# src/server/mcp/tools/attention_sentiment_tools.py
"""MCP tools for multi-source A-share attention and sentiment signals."""

import time
from typing import Any, Dict

from fastmcp import FastMCP, Context

from src.server.core.dependencies import Container
from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_standard_artifact_response,
)


def register_attention_sentiment_tools(mcp: FastMCP):
    """Register attention and sentiment MCP tools."""

    @mcp.tool(tags={"attention-sentiment", "baidu"})
    async def get_baidu_hot_search(
        symbol: str = "A股",
        date: str = "",
        time_period: str = "今日",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取百度股市热搜。"""
        if ctx:
            await ctx.info(f"获取百度热搜: symbol={symbol}, date={date or 'latest'}, time={time_period}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_baidu_hot_search", symbol=symbol, date=date, time_period=time_period)
            gateway = Container.market_gateway()
            result = await gateway.get_baidu_hot_search(symbol=symbol, date=date, time_period=time_period)
            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            summary = f"百度热搜({symbol}/{time_period}): 共{total}条 (耗时 {elapsed:.1f}s)"

            md = f"## 百度热搜 - {symbol} / {time_period}\n\n"
            md += f"**条数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            if data:
                md += "| 关键词 | 排名变化 | 热度 |\n|--------|----------|------|\n"
                for r in data[:50]:
                    md += f"| {r.get('keyword', '')} | {r.get('rank_change', '-')} | {r.get('heat', '-')} |\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="百度热搜",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
                date=result.get("date", date),
                time_period=time_period,
            )
        except Exception as e:
            logger.error(f"get_baidu_hot_search failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取百度热搜失败: {e}",
                component_type=ComponentType.TABLE,
                name="百度热搜错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取百度热搜失败: {e}",
            )

    @mcp.tool(tags={"attention-sentiment", "xueqiu"})
    async def get_xueqiu_tweet_hotness(
        symbol: str = "最热门",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取雪球讨论热度榜。"""
        if ctx:
            await ctx.info(f"获取雪球讨论热度榜: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_xueqiu_tweet_hotness", symbol=symbol)
            gateway = Container.market_gateway()
            result = await gateway.get_xueqiu_tweet_hotness(symbol=symbol)
            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            summary = f"雪球讨论热度榜({symbol}): 共{total}条 (耗时 {elapsed:.1f}s)"

            md = f"## 雪球讨论热度榜 - {symbol}\n\n"
            md += f"**条数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            if data:
                md += "| 代码 | 名称 | 热度 | 最新价 |\n|------|------|------|--------|\n"
                for r in data[:50]:
                    md += f"| {r.get('stock_code', '')} | {r.get('stock_name', '')} | {r.get('heat', '-')} | {r.get('latest_price', '-')} |\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="雪球讨论热度榜",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
            )
        except Exception as e:
            logger.error(f"get_xueqiu_tweet_hotness failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取雪球讨论热度榜失败: {e}",
                component_type=ComponentType.TABLE,
                name="雪球讨论热度榜错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取雪球讨论热度榜失败: {e}",
            )

    @mcp.tool(tags={"attention-sentiment", "xueqiu"})
    async def get_xueqiu_follow_hotness(
        symbol: str = "最热门",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取雪球关注热度榜。"""
        if ctx:
            await ctx.info(f"获取雪球关注热度榜: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_xueqiu_follow_hotness", symbol=symbol)
            gateway = Container.market_gateway()
            result = await gateway.get_xueqiu_follow_hotness(symbol=symbol)
            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            summary = f"雪球关注热度榜({symbol}): 共{total}条 (耗时 {elapsed:.1f}s)"

            md = f"## 雪球关注热度榜 - {symbol}\n\n"
            md += f"**条数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            if data:
                md += "| 代码 | 名称 | 热度 | 最新价 |\n|------|------|------|--------|\n"
                for r in data[:50]:
                    md += f"| {r.get('stock_code', '')} | {r.get('stock_name', '')} | {r.get('heat', '-')} | {r.get('latest_price', '-')} |\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="雪球关注热度榜",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
            )
        except Exception as e:
            logger.error(f"get_xueqiu_follow_hotness failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取雪球关注热度榜失败: {e}",
                component_type=ComponentType.TABLE,
                name="雪球关注热度榜错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取雪球关注热度榜失败: {e}",
            )

    @mcp.tool(tags={"attention-sentiment", "xueqiu"})
    async def get_xueqiu_deal_hotness(
        symbol: str = "最热门",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取雪球交易热度榜。"""
        if ctx:
            await ctx.info(f"获取雪球交易热度榜: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_xueqiu_deal_hotness", symbol=symbol)
            gateway = Container.market_gateway()
            result = await gateway.get_xueqiu_deal_hotness(symbol=symbol)
            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            summary = f"雪球交易热度榜({symbol}): 共{total}条 (耗时 {elapsed:.1f}s)"

            md = f"## 雪球交易热度榜 - {symbol}\n\n"
            md += f"**条数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            if data:
                md += "| 代码 | 名称 | 热度 | 最新价 |\n|------|------|------|--------|\n"
                for r in data[:50]:
                    md += f"| {r.get('stock_code', '')} | {r.get('stock_name', '')} | {r.get('heat', '-')} | {r.get('latest_price', '-')} |\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="雪球交易热度榜",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
            )
        except Exception as e:
            logger.error(f"get_xueqiu_deal_hotness failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取雪球交易热度榜失败: {e}",
                component_type=ComponentType.TABLE,
                name="雪球交易热度榜错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取雪球交易热度榜失败: {e}",
            )

    @mcp.tool(tags={"attention-sentiment", "dragon-tiger"})
    async def get_dragon_tiger_statistics(
        symbol: str = "近一月",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取龙虎榜上榜统计，量化短线动量与席位驱动活跃度。"""
        if ctx:
            await ctx.info(f"获取龙虎榜上榜统计: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_dragon_tiger_statistics", symbol=symbol)
            gateway = Container.market_gateway()
            result = await gateway.get_dragon_tiger_statistics(symbol=symbol)
            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            resolved_symbol = result.get("symbol", symbol)
            summary = f"龙虎榜上榜统计({resolved_symbol}): 共{total}只 (耗时 {elapsed:.1f}s)"

            md = f"## 龙虎榜上榜统计 - {resolved_symbol}\n\n"
            md += f"**股票数**: {total} | **耗时**: {elapsed:.1f}s\n\n"
            if data:
                md += "| 排名 | 代码 | 名称 | 上榜次数 | 净买额 | 买入额 | 卖出额 | 近1月涨幅 |\n"
                md += "|------|------|------|----------|--------|--------|--------|-----------|\n"
                for r in data[:50]:
                    md += (
                        f"| {r.get('rank', '-')} | {r.get('stock_code', '')} | {r.get('stock_name', '')} "
                        f"| {r.get('list_count', '-')} | {r.get('net_buy', '-')} | {r.get('buy_amount', '-')} "
                        f"| {r.get('sell_amount', '-')} | {r.get('rise_1m', '-')} |\n"
                    )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="龙虎榜上榜统计",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
                symbol=resolved_symbol,
            )
        except Exception as e:
            logger.error(f"get_dragon_tiger_statistics failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取龙虎榜上榜统计失败: {e}",
                component_type=ComponentType.TABLE,
                name="龙虎榜上榜统计错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取龙虎榜上榜统计失败: {e}",
                symbol=symbol,
            )
