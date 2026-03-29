# src/server/mcp/tools/factor_tools.py
"""MCP tools for quantitative factor analysis.

Tools:
  - get_stock_factors: Calculate momentum/volatility/turnover/liquidity factors
  - get_stock_correlation: Correlation matrix between stocks
  - get_factor_ranking: Market-wide factor ranking
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
    if value is None:
        return "-"
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return "-"
        return format(f, fmt)
    except (TypeError, ValueError):
        return "-"


def register_factor_tools(mcp: FastMCP):
    """Register factor analysis MCP tools."""

    # ------------------------------------------------------------------
    # get_stock_factors — 单股因子计算
    # ------------------------------------------------------------------
    @mcp.tool(tags={"factor", "quant"})
    async def get_stock_factors(
        symbol: str = "600519",
        days: int = 250,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取单只股票量化因子 (动量/波动率/换手率/Amihud非流动性).

        WHEN TO USE: 用户问"这只股票动量因子如何"、"波动率多少"、"Amihud非流动性指标".
        CONCEPT: 量化因子是构建alpha策略的基础输入, 包含动量、波动率、换手率、流动性等维度.
        DIFFERENTIATION: 单股因子画像; 多股相关性用 get_stock_correlation; 因子排名用 get_factor_ranking.
        next_recommended_tools: get_factor_ranking -> get_stock_correlation
        - "贵州茅台的动量和波动率因子"
        - "600519的1月/3月/6月/12月动量"
        - "比较宁德时代和比亚迪的因子"

        Args:
            symbol: 股票代码 (如 '600519'=贵州茅台, '000858'=五粮液)
            days: 计算窗口天数 (default 250 ≈ 1年)
            ctx: FastMCP Context.

        Returns:
            Factor values including momentum, volatility, turnover, liquidity.
        """
        if ctx:
            await ctx.info(f"计算因子: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_stock_factors", symbol=symbol)

            result = await Container.market_gateway().get_stock_factors(
                symbol=symbol, days=days,
            )

            elapsed = time.perf_counter() - t0
            factors = result.get("factors", {})
            summary = f"因子计算({symbol}): {len(factors)}个因子 ({elapsed:.1f}s)"

            md = f"## 量化因子: {symbol}\n\n"
            md += f"**窗口**: {days}天 | **数据天数**: {factors.get('data_days', '-')} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 因子 | 值 |\n|------|----|\n"
            for k, v in factors.items():
                md += f"| {k} | {v if v is not None else '-'} |\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.STOCK_SCREENER,
                name=f"量化因子: {symbol}",
                data=result,
                symbol=symbol,
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_stock_factors failed: {e}")
            return create_standard_artifact_response(
                summary=f"因子计算失败: {e}",
                component_type=ComponentType.TABLE,
                name="因子计算错误",
                data={"error": str(e)},
                source="akshare",
                description=f"因子计算失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_stock_correlation — 多股相关性矩阵
    # ------------------------------------------------------------------
    @mcp.tool(tags={"factor", "correlation"})
    async def get_stock_correlation(
        symbols: str = "600519,000858,000333",
        days: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取多只股票相关系数矩阵.

        WHEN TO USE: 用户问"这几只股票相关性高不高"、"组合分散度怎么样".
        CONCEPT: 相关系数矩阵衡量标的间线性相关程度, 是组合构建/对冲/配对交易的基础.
        DIFFERENTIATION: 多股相关性; 单股因子用 get_stock_factors; 因子排名用 get_factor_ranking.
        next_recommended_tools: get_stock_factors -> get_factor_ranking
        - "茅台、五粮液、美的之间的相关性"
        - "白酒板块股票的相关系数"
        - "组合内股票的分散化程度"

        Args:
            symbols: 逗号分隔的股票代码 (如 '600519,000858,000333')
            days: 计算窗口天数 (default 60)
            ctx: FastMCP Context.

        Returns:
            Correlation matrix with average correlation.
        """
        if ctx:
            await ctx.info(f"计算相关性: {symbols}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_stock_correlation", symbols=symbols)

            result = await Container.market_gateway().get_stock_correlation(
                symbols=symbols, days=days,
            )

            elapsed = time.perf_counter() - t0
            codes = result.get("symbols", [])
            avg_corr = result.get("avg_correlation")
            matrix = result.get("correlation_matrix", [])

            summary = f"相关性矩阵({len(codes)}只, {days}天): 平均相关={avg_corr} ({elapsed:.1f}s)"

            md = f"## 股票相关性矩阵\n\n"
            md += f"**标的**: {', '.join(codes)} | **窗口**: {days}天 | **平均相关**: {avg_corr or '-'}\n\n"

            # Table header
            header = "| 代码 |"
            sep = "|------|"
            for code in codes:
                header += f" {code} |"
                sep += "------|"
            md += header + "\n" + sep + "\n"

            for row in matrix:
                line = f"| {row['symbol']} |"
                for code in codes:
                    val = row.get(f"corr_{code}")
                    line += f" {_safe_fmt(val)} |"
                md += line + "\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="股票相关性矩阵",
                data=result,
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_stock_correlation failed: {e}")
            return create_standard_artifact_response(
                summary=f"相关性计算失败: {e}",
                component_type=ComponentType.TABLE,
                name="相关性错误",
                data={"error": str(e)},
                source="akshare",
                description=f"相关性计算失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_factor_ranking — 全市场因子排名
    # ------------------------------------------------------------------
    @mcp.tool(tags={"factor", "ranking"})
    async def get_factor_ranking(
        factor: str = "change_pct",
        direction: str = "desc",
        limit: int = 30,
        exchange: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股全市场因子排名.

        WHEN TO USE: 用户问"涨幅最大的股票"、"换手率排名"、"量比Top30"、"振幅最大".
        CONCEPT: 按单因子(涨跌幅/换手率/量比/振幅等)对全市场排名, 快速发现极端标的.
        DIFFERENTIATION: 全市场排名; 单股因子用 get_stock_factors; 多条件筛选用 quantitative screen_stocks.
        next_recommended_tools: get_stock_factors -> screen_stocks

        Args:
            factor: 因子名称 (change_pct=涨跌幅/turnover_rate=换手率/volume_ratio=量比/amplitude=振幅)
            direction: 排序方向 (desc=从高到低, asc=从低到高)
            limit: 返回数量 (default 30, max 100)
            exchange: 交易所 (SSE/SZSE/BSE, 空=全部)
            ctx: FastMCP Context.

        Returns:
            Ranked stock list by factor value.
        """
        if ctx:
            await ctx.info(f"因子排名: {factor} {direction}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_factor_ranking", factor=factor, direction=direction)

            result = await Container.market_gateway().get_factor_ranking(
                factor=factor, direction=direction, limit=limit, exchange=exchange,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"因子排名({factor}): 全市场{total}只, 返回{len(results)}只 ({elapsed:.1f}s)"

            md = f"## 因子排名: {factor} ({direction})\n\n"
            md += f"**全市场总数**: {total} | **返回**: {len(results)} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 排名 | 代码 | 名称 | 因子值 | 涨跌幅% | 换手率% | 量比 | 最新价 |\n"
            md += "|------|------|------|--------|---------|---------|------|--------|\n"
            for i, r in enumerate(results):
                md += (
                    f"| {i + 1} "
                    f"| {r.get('symbol', '')} "
                    f"| {r.get('name', '')} "
                    f"| {_safe_fmt(r.get('factor_value'))} "
                    f"| {_safe_fmt(r.get('涨跌幅'))} "
                    f"| {_safe_fmt(r.get('换手率'))} "
                    f"| {_safe_fmt(r.get('量比'))} "
                    f"| {_safe_fmt(r.get('最新价'))} |\n"
                )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.STOCK_SCREENER,
                name=f"因子排名: {factor}",
                data=results,
                source="akshare",
                description=summary,
                limit=limit,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_factor_ranking failed: {e}")
            return create_standard_artifact_response(
                summary=f"因子排名失败: {e}",
                component_type=ComponentType.TABLE,
                name="因子排名错误",
                data={"error": str(e)},
                source="akshare",
                description=f"因子排名失败: {e}",
            )
