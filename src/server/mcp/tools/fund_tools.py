# src/server/mcp/tools/fund_tools.py
"""MCP tools for Chinese fund (基金) data.

Tools:
  - search_funds: Fund search with multi-period performance data
  - get_fund_detail: Fund profile, asset allocation, fees
  - get_fund_ranking: Fund ranking by type and performance period
  - get_fund_manager: Fund manager info (tenure, AUM, best return)
  - get_fund_valuation: Real-time fund NAV estimation
  - get_fund_performance: Fund performance analysis (ranking, drawdown, profit probability)
  - get_fund_scale: Fund scale changes (subscription/redemption/shares/NAV)
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
    """Format a numeric value safely,"""
    if value is None:
        return "-"
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return "-"
        return format(f, fmt)
    except (TypeError, ValueError):
        return "-"


def _fmt_return(value: Any) -> str:
    """Format a return percentage with sign."""
    if value is None:
        return "-"
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return "-"
        return f"{f:+.2f}%"
    except (TypeError, ValueError):
        return "-"


def register_fund_tools(mcp: FastMCP):
    """Register fund data MCP tools."""

    # ------------------------------------------------------------------
    # search_funds — 基金搜索
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "search"})
    async def search_funds(
        keyword: str = "",
        sort_by: str = "近1年",
        sort_order: str = "desc",
        limit: int = 20,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """搜索公募基金，支持按名称/代码模糊搜索，返回多周期业绩数据。

        可按不同维度排序：近1周/近1月/近3月/近6月/近1年/近3年/今年来/成立来。
        支持模糊搜索基金名称和代码。

        Typical use cases:
        - "搜索名称包含'沪深300'的基金"
        - "找近1年收益最高的混合型基金"
        - "搜索代码包含'1100'的基金"

        Args:
            keyword: 搜索关键词 (名称或代码模糊匹配, 如 '沪深300', '易方达')
            sort_by: 排序维度 (近1周/近1月/近3月/近6月/近1年/近3年/今年来/成立来, 默认近1年)
            sort_order: "desc" or "asc"
            limit: 返回数量 (default 20, max 50)
            ctx: FastMCP Context.

        Returns:
            基金列表 with NAV and multi-period returns.
        """
        if ctx:
            await ctx.info(f"搜索基金: keyword={keyword}, sort_by={sort_by}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: search_funds", keyword=keyword, sort_by=sort_by)

            result = await Container.market_gateway().search_funds(
                keyword=keyword, sort_by=sort_by,
                sort_order=sort_order, limit=limit,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"基金搜索: 关键词='{keyword}', 找到 {total} 只, 返回 {len(results)} 只 (耗时 {elapsed:.1f}s)"

            # Markdown output
            md = f"## 基金搜索结果\n\n"
            md += f"**关键词**: {keyword or '全市场'} | **排序**: {sort_by} ({sort_order}) | **结果**: {total} 只\n\n"
            md += "| 代码 | 名称 | 最新净值 | 近1月 | 近3月 | 近1年 | 近3年 | 成立来 | 手续费 |\n"
            md += "|------|------|--------|------|------|------|------|------|------|\n"
            for r in results:
                md += (
                    f"| {r.get('fund_code', '')} "
                    f"| {r.get('fund_name', '')} "
                    f"| {_safe_fmt(r.get('nav'))} "
                    f"| {_fmt_return(r.get('return_1m'))} "
                    f"| {_fmt_return(r.get('return_3m'))} "
                    f"| {_fmt_return(r.get('return_1y'))} "
                    f"| {_fmt_return(r.get('return_3y'))} "
                    f"| {_fmt_return(r.get('return_since_inception'))} "
                    f"| {_safe_fmt(r.get('fee'))} |\n"
                )

            artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_SEARCH,
                name="基金搜索",
                content={"markdown": md, "data": results},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"search_funds failed: {e}")
            err_artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_SEARCH,
                name="基金搜索错误",
                content={"error": str(e)},
                description=f"基金搜索失败: {e}",
            )
            return create_artifact_response(summary=f"基金搜索失败: {e}", artifact=err_artifact)

    # ------------------------------------------------------------------
    # get_fund_detail — 基金详情
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "detail"})
    async def get_fund_detail(
        fund_code: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取基金详情：基本信息、费率、资产配置比例。

        Typical use cases:
        - "查看易方达中小盘(110011)的详细信息"
        - "查看基金005827的资产配置"

        Args:
            fund_code: 基金代码 (如 110011, 005827, 510300)
            ctx: FastMCP Context.

        Returns:
            Fund detail with basic info, fees, asset allocation.
        """
        if ctx:
            await ctx.info(f"获取基金详情: {fund_code}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_fund_detail", fund_code=fund_code)

            result = await Container.market_gateway().get_fund_detail(fund_code=fund_code)

            elapsed = time.perf_counter() - t0
            summary = f"基金详情: {fund_code} (耗时 {elapsed:.1f}s)"

            # Build markdown from the key-value detail
            md = f"## 基金详情: {fund_code}\n\n"

            # Extract key fields
            skip_keys = {"fund_code", "source", "error", "asset_allocation"}
            for k, v in result.items():
                if k in skip_keys:
                    continue
                if v is not None:
                    md += f"- **{k}**: {v}\n"

            # Asset allocation table
            alloc = result.get("asset_allocation", [])
            if alloc:
                md += "\n### 资产配置\n\n"
                md += "| 资产类别 | 占比 |\n|------|------|\n"
                for a in alloc:
                    md += f"| {a.get('资产类别', '')} | {a.get('单位占比', '-')}% |\n"

            artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_DETAIL,
                name=f"基金详情: {fund_code}",
                content={"markdown": md, "data": result},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_fund_detail failed: {e}")
            err_artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_DETAIL,
                name="基金详情错误",
                content={"error": str(e)},
                description=f"基金详情查询失败: {e}",
            )
            return create_artifact_response(summary=f"基金详情查询失败: {e}", artifact=err_artifact)

    # ------------------------------------------------------------------
    # get_fund_ranking — 基金排行
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "ranking"})
    async def get_fund_ranking(
        fund_type: str = "全部",
        sort_by: str = "近1年",
        sort_order: str = "desc",
        limit: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """基金排行：按类型和业绩周期筛选排序。

        Typical use cases:
        - "近1年收益最高的股票型基金"
        - "近3月表现最好的混合型基金"
        - "今年来收益最差的指数型基金"

        Args:
            fund_type: 基金类型 (全部/股票型/混合型/债券型/指数型/QDII/FOF/货币型, 默认全部)
            sort_by: 排序维度 (近1周/近1月/近3月/近6月/近1年/近3年/今年来/成立来)
            sort_order: "desc" (默认, 最佳在前) or "asc"
            limit: 返回数量 (default 30, max 100)
            ctx: FastMCP Context.

        Returns:
            Ranked fund list with multi-period performance.
        """
        if ctx:
            await ctx.info(f"获取基金排行: type={fund_type}, sort_by={sort_by}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_fund_ranking", fund_type=fund_type, sort_by=sort_by)

            result = await Container.market_gateway().get_fund_ranking(
                fund_type=fund_type, sort_by=sort_by,
                sort_order=sort_order, limit=limit,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"基金排行: {fund_type}, 按{sort_by}{sort_order}, 共{total}只, 返回{len(results)}只 ({elapsed:.1f}s)"

            md = f"## 基金排行 ({fund_type}, 按{sort_by} {sort_order})\n\n"
            md += f"**总数**: {total} | **返回**: {len(results)} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 代码 | 名称 | 净值 | 近1月 | 近3月 | 近1年 | 近3年 | 成立来 | 手续费 |\n"
            md += "|------|------|------|------|------|------|------|------|------|\n"
            for r in results:
                md += (
                    f"| {r.get('fund_code', '')} "
                    f"| {r.get('fund_name', '')} "
                    f"| {_safe_fmt(r.get('nav'))} "
                    f"| {_fmt_return(r.get('return_1m'))} "
                    f"| {_fmt_return(r.get('return_3m'))} "
                    f"| {_fmt_return(r.get('return_1y'))} "
                    f"| {_fmt_return(r.get('return_3y'))} "
                    f"| {_fmt_return(r.get('return_since_inception'))} "
                    f"| {_safe_fmt(r.get('fee'))} |\n"
                )

            artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_RANKING,
                name="基金排行",
                content={"markdown": md, "data": results},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_fund_ranking failed: {e}")
            err_artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_RANKING,
                name="基金排行错误",
                content={"error": str(e)},
                description=f"基金排行查询失败: {e}",
            )
            return create_artifact_response(summary=f"基金排行查询失败: {e}", artifact=err_artifact)

    # ------------------------------------------------------------------
    # get_fund_manager — 基金经理
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "manager"})
    async def get_fund_manager(
        manager_name: str = "",
        fund_company: str = "",
        limit: int = 20,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """基金经理信息：从业时间、管理规模、最佳回报、任职基金列表。

        Typical use cases:
        - "查看张坤管理的基金"
        - "搜索易方达基金公司的经理"
        - "查找管理规模最大的基金经理"

        Args:
            manager_name: 经理姓名 (模糊匹配, 如 '张坤', '刘彦春')
            fund_company: 基金公司 (模糊匹配, 如 '易方达', '华夏')
            limit: 返回数量 (default 20)
            ctx: FastMCP Context.

        Returns:
            Fund manager list with tenure, AUM. best return. managed funds.
        """
        if ctx:
            await ctx.info(f"获取基金经理: {manager_name}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_fund_manager", manager_name=manager_name)

            result = await Container.market_gateway().get_fund_manager(
                manager_name=manager_name, fund_company=fund_company, limit=limit,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"基金经理: 找到 {total} 条, 返回 {len(results)} 条 (耗时 {elapsed:.1f}s)"

            md = f"## 基金经理\n\n"
            md += f"**筛选**: {manager_name or '全部'} @ {fund_company or '全部公司'} | **结果**: {total}\n\n"
            md += "| 姓名 | 公司 | 基金代码 | 基金名称 | 从业(天) | 规模(亿) | 最佳回报 |\n"
            md += "|------|------|--------|--------|--------|--------|--------|\n"
            for r in results:
                md += (
                    f"| {r.get('manager_name', '')} "
                    f"| {r.get('fund_company', '')} "
                    f"| {r.get('fund_code', '')} "
                    f"| {r.get('fund_name', '')} "
                    f"| {r.get('tenure_days', '-')} "
                    f"| {_safe_fmt(r.get('aum'))} "
                    f"| {_fmt_return(r.get('best_return'))} |\n"
                )

            artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_MANAGER,
                name="基金经理",
                content={"markdown": md, "data": results},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_fund_manager failed: {e}")
            err_artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_MANAGER,
                name="基金经理错误",
                content={"error": str(e)},
                description=f"基金经理查询失败: {e}",
            )
            return create_artifact_response(summary=f"基金经理查询失败: {e}", artifact=err_artifact)

    # ------------------------------------------------------------------
    # get_fund_valuation — 基金实时估值
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "valuation"})
    async def get_fund_valuation(
        fund_code: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """基金实时估值：估算净值、估算涨跌幅、实际净值、偏差。

        实时数据，5分钟刷新。不指定fund_code返回全市场估值排行前20。

        Typical use cases:
        - "查看110011的实时估值"
        - "今天估算涨幅最大的基金"
        - "全市场基金估值排行"

        Args:
            fund_code: 基金代码 (如 110011, 为空返回全市场前20)
            ctx: FastMCP Context.

        Returns:
            Fund NAV estimation with actual NAV and deviation.
        """
        if ctx:
            await ctx.info(f"获取基金估值: {fund_code or '全市场'}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_fund_valuation", fund_code=fund_code)

            result = await Container.market_gateway().get_fund_valuation(fund_code=fund_code)

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"基金估值: {fund_code or '全市场'}, {len(results)}条 (耗时 {elapsed:.1f}s)"

            md = f"## 基金实时估值\n\n"
            md += f"**代码**: {fund_code or '全市场'} | **总数**: {total}\n\n"
            md += "| 代码 | 名称 | 估算净值 | 估算涨跌 | 实际净值 | 实际涨跌 | 偏差 |\n"
            md += "|------|------|--------|--------|--------|--------|------|\n"
            for r in results:
                md += (
                    f"| {r.get('fund_code', '')} "
                    f"| {r.get('fund_name', '')} "
                    f"| {_safe_fmt(r.get('estimated_nav'))} "
                    f"| {_fmt_return(r.get('estimated_change_pct'))} "
                    f"| {_safe_fmt(r.get('actual_nav'))} "
                    f"| {_fmt_return(r.get('actual_change_pct'))} "
                    f"| {_safe_fmt(r.get('estimation_deviation'))} |\n"
                )

            artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_VALUATION,
                name="基金实时估值",
                content={"markdown": md, "data": results},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_fund_valuation failed: {e}")
            err_artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_VALUATION,
                name="基金估值错误",
                content={"error": str(e)},
                description=f"基金估值查询失败: {e}",
            )
            return create_artifact_response(summary=f"基金估值查询失败: {e}", artifact=err_artifact)

    # ------------------------------------------------------------------
    # get_fund_performance — 基金业绩分析
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "performance"})
    async def get_fund_performance(
        fund_code: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """基金业绩分析：各周期排名、超额收益、最大回撤、盈利概率。

        Typical use cases:
        - "分析110011的历史业绩"
        - "查看005827的回撤和盈利概率"

        Args:
            fund_code: 基金代码 (如 110011, 005827)
            ctx: FastMCP Context.

        Returns:
            Fund performance analysis with achievement, analysis, profit probability.
        """
        if ctx:
            await ctx.info(f"分析基金业绩: {fund_code}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_fund_performance", fund_code=fund_code)

            result = await Container.market_gateway().get_fund_performance(fund_code=fund_code)

            elapsed = time.perf_counter() - t0
            summary = f"基金业绩分析: {fund_code} (耗时 {elapsed:.1f}s)"

            md = f"## 基金业绩分析: {fund_code}\n\n"

            # Achievement section
            ach = result.get("achievement", [])
            if ach:
                md += "### 业绩排名\n\n"
                md += "| 周期 | 名称 | 同类排名 | 同类回报率 | 近一年同类排名 |\n"
                md += "|------|------|--------|----------|------------|\n"
                for a in ach:
                    vals = [str(a.get(k, "-")) for k in ("业绩维度", "名称", "同类平均排名", "同类平均回报率", "同类平均近一年同类排名")]
                    md += f"| {' | '.join(vals)} |\n"

            # Analysis section
            ana = result.get("analysis", [])
            if ana:
                md += "\n### 风险分析\n\n"
                md += "| 周期 | 收益概率 | 超额比率 | 最大回撤 |\n"
                md += "|------|--------|--------|--------|\n"
                for a in ana:
                    md += (
                        f"| {a.get('周期', '-')} "
                        f"| {_safe_fmt(a.get('收益概率'))} "
                        f"| {_safe_fmt(a.get('收益概率超额比率'))} "
                        f"| {_safe_fmt(a.get('最大回撤'))} |\n"
                    )

            # Profit probability section
            prof = result.get("profit_probability", [])
            if prof:
                md += "\n### 盈利概率\n\n"
                md += "| 持有时间 | 盈利概率 | 平均收益 |\n"
                md += "|--------|--------|--------|\n"
                for p in prof:
                    md += (
                        f"| {p.get('持有时间', '-')} "
                        f"| {p.get('盈利概率', '-')}% "
                        f"| {_safe_fmt(p.get('平均收益'))}% |\n"
                    )

            artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_PERFORMANCE,
                name=f"基金业绩分析: {fund_code}",
                content={"markdown": md, "data": result},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_fund_performance failed: {e}")
            err_artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_PERFORMANCE,
                name="基金业绩错误",
                content={"error": str(e)},
                description=f"基金业绩分析失败: {e}",
            )
            return create_artifact_response(summary=f"基金业绩分析失败: {e}", artifact=err_artifact)

    # ------------------------------------------------------------------
    # get_fund_scale — 全市场基金规模变动
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "scale"})
    async def get_fund_scale(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """全市场基金规模变动：基金家数/申购/赎回/净资产的历史变化趋势。

        Typical use cases:
        - "查看全市场基金规模变化趋势"
        - "分析最近几个季度基金申购赎回对比"

        Args:
            ctx: FastMCP Context.

        Returns:
            Market-wide fund scale history with subscription, redemption, NAV.
        """
        if ctx:
            await ctx.info("获取全市场基金规模变动")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_fund_scale")

            result = await Container.market_gateway().get_fund_scale()

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"全市场基金规模变动: {total}期 (耗时 {elapsed:.1f}s)"

            md = f"## 全市场基金规模变动\n\n"
            md += f"**期数**: {total}\n\n"
            md += "| 截止日期 | 基金家数 | 期间申购 | 期间赎回 | 期末份额 | 期末净资产 |\n"
            md += "|--------|--------|--------|--------|--------|--------|\n"
            for r in results:
                md += (
                    f"| {r.get('date', '')} "
                    f"| {r.get('fund_count', '-')} "
                    f"| {_safe_fmt(r.get('subscription'))} "
                    f"| {_safe_fmt(r.get('redemption'))} "
                    f"| {_safe_fmt(r.get('total_shares'))} "
                    f"| {_safe_fmt(r.get('total_nav'))} |\n"
                )

            artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_SCALE,
                name="全市场基金规模变动",
                content={"markdown": md, "data": results},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_fund_scale failed: {e}")
            err_artifact = create_artifact_envelope(
                component_type=ComponentType.FUND_SCALE,
                name="基金规模错误",
                content={"error": str(e)},
                description=f"基金规模变动查询失败: {e}",
            )
            return create_artifact_response(summary=f"基金规模变动查询失败: {e}", artifact=err_artifact)
