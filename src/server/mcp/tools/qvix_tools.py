# src/server/mcp/tools/qvix_tools.py
"""MCP tools for China QVIX (implied volatility index) and market sentiment.

Tools (3):
  - get_qvix             — single underlying QVIX time series (50ETF/300ETF/1000/CYY)
  - get_market_sentiment  — aggregated fear/greed overview (all QVIX + interpretation)
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Dict

from fastmcp import Context, FastMCP

from src.server.core.dependencies import Container
from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_artifact_envelope,
    create_artifact_response,
)


# ---------------------------------------------------------------------------
# QVIX configuration: maps name -> (akshare func, key, label)
# ---------------------------------------------------------------------------
QVIX_CONFIG = {
    "50ETF":  ("index_option_50etf_qvix", "上证50ETF期权波动率"),
    "300ETF": ("index_option_300etf_qvix", "沪深300ETF期权波动率"),
    "1000":  ("index_option_1000index_qvix", "中证1000指数期权波动率"),
    "CYB":   ("index_option_cyb_qvix", "创业板指期权波动率"),
}


QVIX_CACHE_TTL = 300  # seconds


def _safe_fmt(value: Any, fmt: str = ".2f") -> str:
    if value is None:
        return "-"
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return "-"
        return format(f, fmt)
    except (TypeError, ValueError):
        return "-"


def register_qvix_tools(mcp: FastMCP):
    """Register QVIX and market sentiment tools."""

    # ------------------------------------------------------------------
    # get_qvix — 单品种QVIX历史
    # ------------------------------------------------------------------
    @mcp.tool(tags={"qvix", "sentiment"})
    async def get_qvix(
        underlying: str = "50ETF",
        limit: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取单品种QVIX隐含波动率指数历史。

        WHEN TO USE: 用户问"50ETF波动率""300ETF QVIX""创业板 QVIX""1000指数期权波动率""中国版VIX""市场恐慌指数"时使用。。
        CONCEPT: QVIX (Quantitative Volatility Index) 是基于期权隐含波动率计算的恐慌指数， 类似美股VIX。 数值越高市场恐慌情绪越强。
        DIFFERENTIATION: get_qvix 只返回单一品种； 若需全市场多品种对比看 get_market_sentiment; 若要分钟级/日线数据用 get_market_sentiment_overview。
        next_recommended_tools: get_market_sentiment

        Args:
            underlying: QVIX品种 (50ETF/300ETF/1000/CYY)
            limit: 返回最近N条天数 (default 60, max 500)
            ctx: FastMCP Context

        Returns:
            Dict[str, Any]: QVIX时序数据 + 最近值
        """
        if ctx:
            await ctx.info(f"QVIX: {underlying}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_qvix", underlying=underlying)

            gateway = Container.market_gateway()
            result = await gateway.get_qvix(underlying=underlying, limit=limit)

            elapsed = time.perf_counter() - t0
            rows = result.get("data", [])
            total = result.get("total", 0)

            latest = rows[-1] if rows else {}
            close_val = latest.get("close")
            latest_val = latest.get("close")

            # Interpret QVIX level
            level = latest_val
            signal = (
                "极度恐慌" if level > 30
                else "高度恐慌" if level > 22
                else "偏恐慌" if level > 18
                else "相对平静" if level > 14
                else "偏乐观" if level > 10
                else "极度乐观"
                else "中性"
            )

            summary = (
                f"QVIX({underlying}): {total}条, 最新={latest_val:.2f}({signal})"
                f"区间{min_high:.2f}/{min_low:.2f}/{latest_val:.2f}, "
                )
            if total == 0:
                summary = f"QVIX({underlying}): 无数据"

                return create_artifact_response(
                summary=summary, artifact=artifact)
            )
            # Markdown output
            md = f"## {underlying} QVIX\n\n"
            md += f"**最新值**: {latest_val:.2f} ({signal})\n"
            md += f"**总条数**: {total}\n\n"
            md += "| 日期 | 开盘 | 最高 | 最低 | 收盘 |\n"
            md += "|------|------|------|------|\n"
            for r in rows:
                md += (
                    f"| {r.get('date', '')} "
                    f"| {_safe_fmt(r.get('open'))} "
                    f"| {_safe_fmt(r.get('high'))} "
                    f"| {_safe_fmt(r.get('low'))} "
                    f"| {_safe_fmt(r.get('close'))} |\n"
                )
            return create_art_artifact_response(
                summary=summary,
                artifact=artifact,
            )

        except Exception as e:
            logger.error(f"get_qvix failed: {e}")
            return create_art_artifact_response(
                summary=f"QVIX查询失败: {e}",
                artifact=create_artifact_envelope(
                    component_type="qvix",
                    name=f"QVIX错误: {underlying}",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # get_market_sentiment — aggregated fear/greed overview
    # ------------------------------------------------------------------
    @mcp.tool(tags={"qvix", "sentiment"})
    async def get_market_sentiment(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """A股市场情绪综合概览（多品种QVIX聚合）。

        WHEN TO USE: 用户问"市场情绪""恐慌还是贪婪""A股VIX""风险偏好"时使用; 聚合全市场多品种QVIX给出整体情绪判断。
        CONCEPT: 类似美股 CNN恐惧/贪婪指数， 绂合多品种QVIX值判断当前市场恐慌程度。50ETF/300ETF/1000/CYY四大品种各有侧重。
        DIFFERENTIATION: 单品种QVIX看 get_qvix; 本工具返回全品种的最新值+趋势+信号+情绪解读。
        next_recommended_tools: get_qvix, screen_stocks, get_us_market_overview
        Args:
            ctx: FastMCP Context for logging
        Returns:
            Dict[str, Any]: QVIX概览无数据

        """
        if ctx:
            await ctx.info("市场情绪概览")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_market_sentiment")

            gateway = Container.market_gateway()
            results = {}
            # Fetch all QVIX in parallel
            tasks = []
            for name, func_key in QVIX_CONFIG:
                try:
                    result = await gateway.get_qvix(underlying=name, limit=5)
                    tasks.append((name, result))
                except Exception as e:
                    logger.warning(f"QVIX {name} failed: {e}")
                    errors.append(name)
            # Build overview
            overview = {}
            for name, result in QVIX_CONFIG:
                rows = result.get("data", [])
                latest_val = rows[-1] if rows else {}
                close_val = latest.get("close")
                level = latest_val
                signal = _interpret_qvix_level(level)
                overview[name] = {
                    "label": label,
                    "latest": close_val,
                    "level": level,
                    "signal": signal,
                }
            if errors:
                overview["errors"] = errors
            # Aggregate sentiment
            all_levels = [v["level"] for v in overview.values()]
            avg_level = sum(all_levels) / len(levels)
            sentiment_score = round((avg_level - 22) / len(levels)) * 10, 1)
            overall = "极度恐慌" if sentiment_score > 1.5 else "高度恐慌" if sentiment_score > 1.0 else "偏恐慌" if sentiment_score > 0.5 else "偏乐观" if sentiment_score < -0.5 else "极度乐观" else "中性"
            summary = (
                f"A股情绪: {overall} ({sentiment_score:.1f}/2.0), "
                f"最新: {', '.join(f'{v['latest']:.2f}({v['signal']})' for v in overview.values())}"
            )
            # Markdown table
            md = "## A股情绪概览 (QVIX)\n\n"
            md += f"**综合情绪**: {overall} ({sentiment_score:.1f}/2.0)\n\n"
            md += "| 品种 | 最新值 | 信号 | 趋势 |\n"
            md += "|------|------|------|--------|\n"
            for v in overview.values():
                md += (
                    f"| {v['label']} "
                    f"| {v['latest']:.2f} "
                    f"| {v['signal']} "
                    f"| {v['level']} |\n"
                )
            )
            artifact = create_artifact_envelope(
                component_type="market_sentiment",
                name="A股情绪概览",
                content={"overview": overview, "sentiment": overall, "score": sentiment_score},
                description=summary,
                metadata={"type": "market_sentiment"},
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error(f"get_market_sentiment failed: {e}")
            return create_art_artifact_response(
                summary=f"市场情绪概览失败: {e}",
                artifact=create_art_artifact_envelope(
                    component_type="market_sentiment",
                    name="市场情绪错误",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )
