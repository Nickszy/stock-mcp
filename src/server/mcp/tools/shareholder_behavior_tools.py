# src/server/mcp/tools/shareholder_behavior_tools.py
"""MCP tools for shareholder behavior analysis (institutional research + pledge).

Exposes adapter-level shareholder behavior data as unified MCP tools:
  - get_institutional_research: 机构调研统计
  - get_stock_pledge: 股票质押比例
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


def register_shareholder_behavior_tools(mcp: FastMCP):
    """Register shareholder behavior MCP tools."""

    # ------------------------------------------------------------------
    # get_institutional_research — 机构调研统计
    # ------------------------------------------------------------------
    @mcp.tool(tags={"shareholder-behavior", "institutional-research"})
    async def get_institutional_research(
        date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股机构调研统计 (机构来访/调研热度).

        WHEN TO USE: 用户问"哪些公司被机构调研"、"机构调研热度"、"哪些股票被机构关注".
        CONCEPT: 机构调研是机构投资者对上市公司进行实地或线上调研的记录,
        调研密度是判断机构关注度的重要先行指标.
        DIFFERENTIATION: 机构调研统计; 股东增减持用 get_shareholder_holding_detail;
        质押数据用 get_stock_pledge.
        next_recommended_tools: get_shareholder_holding_detail -> get_stock_pledge

        Typical use cases:
        - "最近哪些公司被机构密集调研？"
        - "查看某段时间机构调研最多的公司"
        - "机构调研热度排行"

        Args:
            date: 日期 (如 20240630), 为空返回最新数据
            ctx: FastMCP Context.

        Returns:
            机构调研统计数据
        """
        if ctx:
            await ctx.info(f"获取机构调研统计: date={date}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_institutional_research", date=date)

            gateway = Container.market_gateway()
            result = await gateway.get_stock_institutional_research(date=date)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            resolved_date = result.get("date", date)

            summary = f"机构调研统计({resolved_date or '最新'}): 共{total}条 (耗时 {elapsed:.1f}s)"

            md = f"## 机构调研统计{' - ' + resolved_date if resolved_date else ''}\n\n"
            md += f"**记录数**: {total} | **耗时**: {elapsed:.1f}s\n\n"

            if data:
                md += "| 代码 | 名称 | 调研机构数 | 接待次数 | 调研日期 |\n"
                md += "|------|------|-----------|---------|----------|\n"
                for r in data[:40]:
                    code = r.get("代码", r.get("stock_code", ""))
                    name = r.get("名称", r.get("stock_name", ""))
                    inst_count = r.get("调研机构数", r.get("institution_count", "-"))
                    visits = r.get("接待次数", r.get("visit_count", "-"))
                    rdate = r.get("调研日期", r.get("research_date", "-"))
                    md += f"| {code} | {name} | {inst_count} | {visits} | {rdate} |\n"
                if total > 40:
                    md += f"\n*... 还有 {total - 40} 条*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"机构调研: {resolved_date or '最新'}",
                data=data[:100],
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_institutional_research failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取机构调研统计失败: {e}",
                component_type=ComponentType.TABLE,
                name="机构调研错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取机构调研统计失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_stock_pledge — 股票质押比例
    # ------------------------------------------------------------------
    @mcp.tool(tags={"shareholder-behavior", "pledge"})
    async def get_stock_pledge(
        date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股股票质押比例数据 (股东质押风险).

        WHEN TO USE: 用户问"股票质押"、"质押比例"、"质押风险"、"哪些股票质押高".
        CONCEPT: 股票质押是股东以股票为质押物进行融资的行为, 质押比例过高
        意味着股东资金链紧张, 平仓风险较大, 是重要的风险指标.
        DIFFERENTIATION: 质押比例概览; 股东增减持用 get_shareholder_holding_detail;
        机构调研用 get_institutional_research.
        next_recommended_tools: get_shareholder_holding_detail -> get_institutional_research

        Typical use cases:
        - "最近股票质押比例最高的公司有哪些？"
        - "查看全市场质押风险概览"
        - "哪些行业质押比例较高？"

        Args:
            date: 日期 (如 20250328), 为空使用最近交易日
            ctx: FastMCP Context.

        Returns:
            股票质押比例数据
        """
        if ctx:
            await ctx.info(f"获取股票质押数据: date={date}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_stock_pledge", date=date)

            gateway = Container.market_gateway()
            result = await gateway.get_stock_pledge(date=date)

            elapsed = time.perf_counter() - t0
            data = result.get("data", [])
            total = result.get("total", 0)
            resolved_date = result.get("date", date)

            summary = f"股票质押({resolved_date}): 共{total}家 (耗时 {elapsed:.1f}s)"

            md = f"## 股票质押比例 - {resolved_date}\n\n"
            md += f"**公司数**: {total} | **耗时**: {elapsed:.1f}s\n\n"

            if data:
                md += "| 代码 | 名称 | 质押比例(%) | 质押数量(万股) | 质押市值(万元) | 行业 |\n"
                md += "|------|------|------------|--------------|--------------|------|\n"
                for r in data[:50]:
                    code = r.get("stock_code", "")
                    name = r.get("stock_name", "")
                    ratio = r.get("pledge_ratio", "-")
                    shares = r.get("pledged_shares", "-")
                    mval = r.get("pledged_market_value", "-")
                    industry = r.get("industry", "-")
                    md += (
                        f"| {code} | {name} | {ratio} "
                        f"| {shares} | {mval} | {industry} |\n"
                    )
                if total > 50:
                    md += f"\n*... 还有 {total - 50} 家*\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"股票质押: {resolved_date}",
                data=data[:100],
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_stock_pledge failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取股票质押数据失败: {e}",
                component_type=ComponentType.TABLE,
                name="质押数据错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取股票质押数据失败: {e}",
            )
