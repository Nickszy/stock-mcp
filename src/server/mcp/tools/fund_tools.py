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
    create_standard_artifact_response,
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
        """搜索基金 (按名称/类型/公司模糊匹配).

        WHEN TO USE: 用户想找某类基金, 如"新能源ETF有哪些"、"张坤管的基金".
        CONCEPT: 按名称、类型、基金公司等维度搜索公募基金, 返回候选列表.
        DIFFERENTIATION: 搜索入口; 确认后用 get_fund_detail 深入分析.
        next_recommended_tools: get_fund_detail -> get_fund_performance"""
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

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FUND_SEARCH,
                name="基金搜索",
                data=results,
                source="akshare",
                description=summary,
                limit=limit,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"search_funds failed: {e}")
            return create_standard_artifact_response(
                summary=f"基金搜索失败: {e}",
                component_type=ComponentType.FUND_SEARCH,
                name="基金搜索错误",
                data={"error": str(e)},
                source="akshare",
                description=f"基金搜索失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_fund_detail — 基金详情
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "detail"})
    async def get_fund_detail(
        fund_code: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取基金详情 (净值/规模/经理/费率等).

        WHEN TO USE: 用户选定了一只基金, 要看全面信息.
        CONCEPT: 返回基金主数据: 净值、规模、基金经理、成立日期、费率、跟踪指数(ETF)等.
        DIFFERENTIATION: 单只基金完整画像; 若要比较多只用 get_fund_ranking.
        next_recommended_tools: get_fund_performance -> get_fund_manager"""
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

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FUND_DETAIL,
                name=f"基金详情: {fund_code}",
                data=result,
                symbol=fund_code,
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_fund_detail failed: {e}")
            return create_standard_artifact_response(
                summary=f"基金详情查询失败: {e}",
                component_type=ComponentType.FUND_DETAIL,
                name="基金详情错误",
                data={"error": str(e)},
                source="akshare",
                description=f"基金详情查询失败: {e}",
            )

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
        """基金排名 (按收益/风险/规模排序).

        WHEN TO USE: 用户要同类基金排名, 如"近一年收益最高的偏股基金".
        CONCEPT: 按指定维度对同类基金排名比较.
        DIFFERENTIATION: 横向比较工具; 深入单只用 get_fund_detail.
        next_recommended_tools: get_fund_detail -> get_fund_performance"""
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

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FUND_RANKING,
                name="基金排行",
                data=results,
                source="akshare",
                description=summary,
                limit=limit,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_fund_ranking failed: {e}")
            return create_standard_artifact_response(
                summary=f"基金排行查询失败: {e}",
                component_type=ComponentType.FUND_RANKING,
                name="基金排行错误",
                data={"error": str(e)},
                source="akshare",
                description=f"基金排行查询失败: {e}",
            )

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
        """获取基金经理信息.

        WHEN TO USE: 用户关注某位基金经理, 如"张坤管理了哪些基金".
        CONCEPT: 返回基金经理的履历、管理规模、在管基金列表及任职回报.
        DIFFERENTIATION: 聚焦"人"的维度; 基金产品视角用 get_fund_detail.
        next_recommended_tools: get_fund_detail -> get_fund_performance"""
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

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FUND_MANAGER,
                name="基金经理",
                data=results,
                source="akshare",
                description=summary,
                limit=limit,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_fund_manager failed: {e}")
            return create_standard_artifact_response(
                summary=f"基金经理查询失败: {e}",
                component_type=ComponentType.FUND_MANAGER,
                name="基金经理错误",
                data={"error": str(e)},
                source="akshare",
                description=f"基金经理查询失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_fund_valuation — 基金实时估值
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "valuation"})
    async def get_fund_valuation(
        fund_code: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取基金估值 (PE/PB/股息率).

        WHEN TO USE: 用户问"这只指数基金现在贵不贵"、"PE百分位多少".
        CONCEPT: 指数/ETF基金的估值参考, 基于成分股加权PE/PB及历史百分位.
        DIFFERENTIATION: 基金级估值; 个股估值用 get_valuation_metrics.
        next_recommended_tools: get_fund_detail -> get_fund_performance"""
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

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FUND_VALUATION,
                name="基金实时估值",
                data=results,
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_fund_valuation failed: {e}")
            return create_standard_artifact_response(
                summary=f"基金估值查询失败: {e}",
                component_type=ComponentType.FUND_VALUATION,
                name="基金估值错误",
                data={"error": str(e)},
                source="akshare",
                description=f"基金估值查询失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_fund_performance — 基金业绩分析
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "performance"})
    async def get_fund_performance(
        fund_code: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取基金历史业绩 (收益率/净值曲线).

        WHEN TO USE: 用户要看基金过往表现, 如"近3年收益曲线".
        CONCEPT: 基金净值历史 + 区间收益率 + 基准对比.
        DIFFERENTIATION: 历史业绩视角; 当前估值用 get_fund_valuation.
        next_recommended_tools: get_fund_valuation -> get_fund_detail"""
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

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FUND_PERFORMANCE,
                name=f"基金业绩分析: {fund_code}",
                data=result,
                symbol=fund_code,
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_fund_performance failed: {e}")
            return create_standard_artifact_response(
                summary=f"基金业绩分析失败: {e}",
                component_type=ComponentType.FUND_PERFORMANCE,
                name="基金业绩错误",
                data={"error": str(e)},
                source="akshare",
                description=f"基金业绩分析失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_fund_scale — 全市场基金规模变动
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fund", "scale"})
    async def get_fund_scale(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取基金规模数据.

        WHEN TO USE: 用户问"这只基金规模多大"、"有没有清盘风险".
        CONCEPT: 基金规模(AUM)是流动性和运营稳定性的重要指标.
        DIFFERENTIATION: 只看规模; 全面信息用 get_fund_detail.
        next_recommended_tools: get_fund_detail -> get_fund_performance"""
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

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FUND_SCALE,
                name="全市场基金规模变动",
                data=results,
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_fund_scale failed: {e}")
            return create_standard_artifact_response(
                summary=f"基金规模变动查询失败: {e}",
                component_type=ComponentType.FUND_SCALE,
                name="基金规模错误",
                data={"error": str(e)},
                source="akshare",
                description=f"基金规模变动查询失败: {e}",
            )
