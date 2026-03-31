# src/server/mcp/tools/earnings_forecast_tools.py
"""MCP tools for earnings forecast and analyst consensus.

Exposes:
  - get_earnings_preview: A股业绩预告 (earnings guidance)
  - get_analyst_consensus: 分析师一致预期 (EPS forecast)
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


def register_earnings_forecast_tools(mcp: FastMCP):
    """Register earnings forecast MCP tools."""

    # ------------------------------------------------------------------
    # get_earnings_preview — 业绩预告
    # ------------------------------------------------------------------
    @mcp.tool(tags={"earnings-forecast", "preview"})
    async def get_earnings_preview(
        period: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股业绩预告数据 (上市公司业绩预告/预盈/预亏).

        WHEN TO USE: 用户问"业绩预告"、"哪些公司预盈/预亏"、"业绩预告汇总".
        CONCEPT: 业绩预告是上市公司对即将发布财报的业绩区间预测, 是最早的业绩信号.
        DIFFERENTIATION: 业绩预告(预测); 已发财报用 get_financial_statements;
        分析师预期用 get_analyst_consensus.
        next_recommended_tools: get_financial_statements -> get_analyst_consensus

        Typical use cases:
        - "2025一季报有哪些公司业绩预告？"
        - "最近预增的公司有哪些？"
        - "查看某报告期业绩预告汇总"

        Args:
            period: 报告期 (如 20250331, 20241231), 为空自动推断
            ctx: FastMCP Context.

        Returns:
            业绩预告数据
        """
        if ctx:
            await ctx.info(f"获取业绩预告: period={period}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_earnings_preview", period=period)

            gateway = Container.market_gateway()
            result = await gateway.get_earnings_preview(period=period)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            resolved_period = result.get("period", period)

            summary = f"业绩预告({resolved_period}): 共{total}家 (耗时 {elapsed:.1f}s)"

            md = f"## 业绩预告 - {resolved_period}\n\n"
            md += f"**公司数**: {total} | **耗时**: {elapsed:.1f}s\n\n"

            if data:
                md += "| 代码 | 名称 | 预测指标 | 业绩变动 | 预测数值 | 预告类型 | 公告日期 |\n"
                md += "|------|------|---------|---------|---------|---------|----------|\n"
                for r in data[:50]:
                    code = r.get("stock_code", "")
                    name = r.get("stock_name", "")
                    indicator = r.get("forecast_indicator", "-")
                    change = r.get("performance_change", "-")
                    value = r.get("forecast_value", "-")
                    ptype = r.get("preview_type", "-")
                    adate = r.get("announce_date", "-")
                    md += (
                        f"| {code} | {name} | {str(indicator)[:20]} "
                        f"| {str(change)[:25]} | {value} | {ptype} | {adate} |\n"
                    )
                if total > 50:
                    md += f"\n*... 还有 {total - 50} 家*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"业绩预告: {resolved_period}",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_earnings_preview failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取业绩预告失败: {e}",
                component_type=ComponentType.TABLE,
                name="业绩预告错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取业绩预告失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_analyst_consensus — 分析师一致预期
    # ------------------------------------------------------------------
    @mcp.tool(tags={"earnings-forecast", "consensus"})
    async def get_analyst_consensus(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股分析师一致预期 (同花顺盈利预测/EPS).

        WHEN TO USE: 用户问"分析师预期"、"一致预期EPS"、"机构预测盈利".
        CONCEPT: 分析师一致预期是多个卖方分析师预测的汇总, 用于判断市场预期差.
        DIFFERENTIATION: 分析师预期(EPS预测); 业绩预告用 get_earnings_preview;
        实际财报用 get_financial_statements.
        next_recommended_tools: get_earnings_preview -> get_financial_statements

        Typical use cases:
        - "600519贵州茅台分析师一致预期是多少？"
        - "查看某只股票机构预测EPS"
        - "分析师预期eps最大值和最小值"

        Args:
            symbol: 股票代码 (如 600519), 必填
            ctx: FastMCP Context.

        Returns:
            分析师一致预期数据
        """
        if not symbol:
            return create_standard_artifact_response(
                summary="需要提供股票代码",
                component_type=ComponentType.TABLE,
                name="分析师预期",
                data={"error": "symbol参数必填"},
                source="akshare",
                description="请提供股票代码查询分析师预期",
            )

        if ctx:
            await ctx.info(f"获取分析师一致预期: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_analyst_consensus", symbol=symbol)

            gateway = Container.market_gateway()
            result = await gateway.get_analyst_consensus(symbol=symbol)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)

            summary = f"分析师一致预期: {symbol} 共{total}期 (耗时 {elapsed:.1f}s)"

            md = f"## 分析师一致预期 - {symbol}\n\n"
            md += f"**期数**: {total} | **耗时**: {elapsed:.1f}s\n\n"

            if data:
                md += "| 年份 | 机构数 | EPS最小值 | EPS均值 | EPS最大值 | 行业平均 |\n"
                md += "|------|--------|----------|--------|----------|----------|\n"
                for r in data:
                    year = r.get("year", "-")
                    count = r.get("analyst_count", "-")
                    eps_min = r.get("eps_min", "-")
                    eps_mean = r.get("eps_mean", "-")
                    eps_max = r.get("eps_max", "-")
                    ind_avg = r.get("industry_avg", "-")
                    md += f"| {year} | {count} | {eps_min} | {eps_mean} | {eps_max} | {ind_avg} |\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"分析师预期: {symbol}",
                data=data,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_analyst_consensus failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取分析师预期失败: {e}",
                component_type=ComponentType.TABLE,
                name="分析师预期错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取分析师预期失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_earnings_flash — 业绩快报
    # ------------------------------------------------------------------
    @mcp.tool(tags={"earnings-forecast", "flash"})
    async def get_earnings_flash(
        period: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股业绩快报数据 (比正式财报更早的核心经营快照).

        WHEN TO USE: 用户问"业绩快报"、"快报营收净利"、"哪些公司先披露快报".
        CONCEPT: 业绩快报通常早于正式财报, 提供营收、净利润、ROE、EPS 等关键指标的快速披露.
        DIFFERENTIATION: 业绩快报(初步披露); 业绩预告用 get_earnings_preview; 正式财报用 get_financial_statements.
        next_recommended_tools: get_earnings_preview -> get_financial_statements

        Args:
            period: 报告期 (如 20250331, 20241231), 为空自动推断
            ctx: FastMCP Context.

        Returns:
            业绩快报数据
        """
        if ctx:
            await ctx.info(f"获取业绩快报: period={period}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_earnings_flash", period=period)

            gateway = Container.market_gateway()
            result = await gateway.get_earnings_flash(period=period)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            resolved_period = result.get("period", period)

            summary = f"业绩快报({resolved_period}): 共{total}家 (耗时 {elapsed:.1f}s)"

            md = f"## 业绩快报 - {resolved_period}\n\n"
            md += f"**公司数**: {total} | **耗时**: {elapsed:.1f}s\n\n"

            if data:
                md += "| 代码 | 名称 | EPS | 营收同比 | 净利润同比 | ROE | 行业 | 公告日期 |\n"
                md += "|------|------|-----|---------|-----------|-----|------|----------|\n"
                for r in data[:50]:
                    md += (
                        f"| {r.get('stock_code', '')} | {r.get('stock_name', '')} "
                        f"| {r.get('eps', '-')} | {r.get('revenue_yoy', '-')} "
                        f"| {r.get('net_profit_yoy', '-')} | {r.get('roe', '-')} "
                        f"| {r.get('industry', '-')} | {r.get('announce_date', '-')} |\n"
                    )
                if total > 50:
                    md += f"\n*... 还有 {total - 50} 家*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"业绩快报: {resolved_period}",
                data=data[:200],
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_earnings_flash failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取业绩快报失败: {e}",
                component_type=ComponentType.TABLE,
                name="业绩快报错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取业绩快报失败: {e}",
            )
