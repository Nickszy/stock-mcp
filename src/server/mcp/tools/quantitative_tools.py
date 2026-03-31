# src/server/mcp/tools/quantitative_tools.py
"""MCP tools for A-share quantitative analysis.

Tools:
  - screen_stocks: Quantitative stock screener with multi-criteria filtering
  - get_industry_ranking: Real-time industry board performance ranking
  - get_concept_ranking: Real-time concept/theme board performance ranking
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
    create_table_artifact,
)


def _safe_fmt(value: Any, fmt: str = ".2f") -> str:
    """Format a numeric value safely, handling NaN/inf/None."""
    if value is None:
        return "-"
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return "-"
        return format(f, fmt)
    except (TypeError, ValueError):
        return "-"


def _fmt_cap(b: Optional[float]) -> str:
    """Format market cap in billions to readable string."""
    if b is None:
        return "-"
    try:
        f = float(b)
        if math.isnan(f) or math.isinf(f):
            return "-"
    except (TypeError, ValueError):
        return "-"
    if f >= 10000:
        return f"{f/10000:.1f}万亿"
    if f >= 100:
        return f"{f/100:.1f}千亿"
    return f"{f:.1f}亿"


_SCREENER_COLUMNS: List[Dict[str, str]] = [
    {"key": "ticker", "label": "代码"},
    {"key": "name", "label": "名称"},
    {"key": "price", "label": "价格"},
    {"key": "change_pct", "label": "涨跌幅%"},
    {"key": "pe", "label": "PE(TTM)"},
    {"key": "pb", "label": "PB"},
    {"key": "market_cap_b", "label": "市值"},
    {"key": "turnover_rate", "label": "换手率%"},
    {"key": "volume_ratio", "label": "量比"},
]

_BOARD_COLUMNS: List[Dict[str, str]] = [
    {"key": "name", "label": "板块"},
    {"key": "change_pct", "label": "涨跌幅%"},
    {"key": "rise_count", "label": "上涨"},
    {"key": "fall_count", "label": "下跌"},
    {"key": "turnover_rate", "label": "换手率%"},
    {"key": "amplitude", "label": "振幅"},
    {"key": "top_stock", "label": "领涨股"},
    {"key": "top_stock_change", "label": "领涨涨幅"},
]


def register_quantitative_tools(mcp: FastMCP):
    """Register A-share quantitative analysis tools."""

    # ------------------------------------------------------------------
    # screen_stocks — A-share quantitative stock screener
    # ------------------------------------------------------------------
    @mcp.tool(tags={"quantitative", "screener"})
    async def screen_stocks(
        min_pe: Optional[float] = None,
        max_pe: Optional[float] = None,
        min_pb: Optional[float] = None,
        max_pb: Optional[float] = None,
        min_market_cap: Optional[float] = None,
        max_market_cap: Optional[float] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        min_turnover_rate: Optional[float] = None,
        max_turnover_rate: Optional[float] = None,
        min_volume_ratio: Optional[float] = None,
        max_volume_ratio: Optional[float] = None,
        min_change_pct: Optional[float] = None,
        max_change_pct: Optional[float] = None,
        min_ytd_change: Optional[float] = None,
        max_ytd_change: Optional[float] = None,
        min_60d_change: Optional[float] = None,
        max_60d_change: Optional[float] = None,
        min_amplitude: Optional[float] = None,
        max_amplitude: Optional[float] = None,
        exchange: Optional[str] = None,
        sort_by: str = "market_cap",
        sort_order: str = "desc",
        limit: int = 50,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """A股量化选股筛选(多条件过滤, 返回符合条件的股票列表).

        WHEN TO USE: 用户想按条件筛选A股股票时调用.
        典型触发: "PE<15且市值>100亿的股票" "低估值高增长筛选" "放量突破的股票".
        CONCEPT: 多维度条件筛选(估值PE/PB/成长涨跌幅/质量换手率量比/技术振幅),
        支持复合条件叠加, 按指定字段排序, 返回符合条件的股票列表.
        DIFFERENTIATION: 本工具是多条件筛选器, 返回符合条件的多只股票;
        单只股票估值分析用get_valuation_metrics(fundamental_tools),
        行业排名用get_industry_ranking或get_concept_ranking,
        因子分析用get_factor_analysis(money_flow_tools).
        next_recommended_tools: get_industry_ranking, get_concept_ranking
        """
        if ctx:
            await ctx.info(f"Running stock screener: {sort_by} {sort_order}, limit={limit}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: screen_stocks", sort_by=sort_by, sort_order=sort_order, limit=limit)

            result = await Container.market_gateway().screen_stocks(
                min_pe=min_pe,
                max_pe=max_pe,
                min_pb=min_pb,
                max_pb=max_pb,
                min_market_cap=min_market_cap,
                max_market_cap=max_market_cap,
                min_price=min_price,
                max_price=max_price,
                min_turnover_rate=min_turnover_rate,
                max_turnover_rate=max_turnover_rate,
                min_volume_ratio=min_volume_ratio,
                max_volume_ratio=max_volume_ratio,
                min_change_pct=min_change_pct,
                max_change_pct=max_change_pct,
                min_ytd_change=min_ytd_change,
                max_ytd_change=max_ytd_change,
                min_60d_change=min_60d_change,
                max_60d_change=max_60d_change,
                min_amplitude=min_amplitude,
                max_amplitude=max_amplitude,
                exchange=exchange,
                sort_by=sort_by,
                sort_order=sort_order,
                limit=limit,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)
            filters = result.get("filters_applied", {})

            if not results:
                summary = f"未找到符合条件的股票 (筛选条件: {filters})"
            else:
                summary = f"筛选结果: 共 {total} 只符合条件, 返回前 {len(results)} 只 (耗时 {elapsed:.1f}s)"

            # Sanitize results for table display (handle NaN/inf)
            clean_rows = []
            for s in results:
                row = {}
                for k, v in s.items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        row[k] = None
                    else:
                        row[k] = v
                clean_rows.append(row)

            # Markdown output
            md = f"## A股量化选股筛选结果\n\n"
            md += f"**筛选条件**: {filters or '无 (全市场)'}\n"
            md += f"**排序**: {sort_by} ({sort_order}) | **符合条件**: {total} 只 | **返回**: {len(results)} 只\n\n"
            md += "| 代码 | 名称 | 价格 | 涨跌幅% | PE(TTM) | PB | 市值 | 换手率% | 量比 |\n"
            md += "|------|------|------|---------|---------|-----|------|---------|------|\n"
            for s in clean_rows:
                cap_str = _fmt_cap(s.get("market_cap_b"))
                md += (
                    f"| {s.get('ticker', '')} "
                    f"| {s.get('name', '')} "
                    f"| {_safe_fmt(s.get('price'))} "
                    f"| {_safe_fmt(s.get('change_pct'), '+.2f')} "
                    f"| {_safe_fmt(s.get('pe'))} "
                    f"| {_safe_fmt(s.get('pb'))} "
                    f"| {cap_str} "
                    f"| {_safe_fmt(s.get('turnover_rate'))} "
                    f"| {_safe_fmt(s.get('volume_ratio'))} |\n"
                )

            artifact = create_artifact_envelope(
                component_type=ComponentType.STOCK_SCREENER,
                name="A股量化选股",
                content={"markdown": md, "data": clean_rows},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"screen_stocks failed: {e}")
            error_artifact = create_artifact_envelope(
                component_type=ComponentType.STOCK_SCREENER,
                name="选股错误",
                content={"error": str(e)},
                description=f"选股筛选失败: {e}",
            )
            return create_artifact_response(
                summary=f"选股筛选失败: {e}",
                artifact=error_artifact,
            )

    # ------------------------------------------------------------------
    # get_industry_ranking — A-share industry board ranking
    # ------------------------------------------------------------------
    @mcp.tool(tags={"quantitative", "sector", "industry"})
    async def get_industry_ranking(
        sort_by: str = "change_pct",
        sort_order: str = "desc",
        limit: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """A股行业板块实时排名(按涨跌幅/换手率等对约100个申万行业板块排名).

        WHEN TO USE: 用户想看今天哪些行业板块涨得好/跌得多, 或行业轮动热度排名时调用.
        典型触发: "今天哪些行业涨得好" "行业板块排名" "哪个板块最强最弱" "板块轮动".
        CONCEPT: 按涨跌幅/换手率/成交量等对约100个申万行业板块排名, 展示涨跌家数/振幅/领涨股,
        用于把握板块轮动和行业强弱.
        DIFFERENTIATION: 本工具是行业板块排名; 概念板块排名用get_concept_ranking;
        个股多条件筛选用screen_stocks; 行业深度分析用sector_research_tools中的工具.
        next_recommended_tools: get_concept_ranking, screen_stocks
        """
        if ctx:
            await ctx.info(f"获取行业板块排名: sort_by={sort_by}, limit={limit}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_industry_ranking", sort_by=sort_by, limit=limit)

            result = await Container.market_gateway().get_industry_ranking(
                sort_by=sort_by, sort_order=sort_order, limit=limit,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"行业板块排名: 共 {total} 个行业, 返回前 {len(results)} 个 (耗时 {elapsed:.1f}s)"

            # Sanitize results
            clean_rows = []
            for r in results:
                row = {}
                for k, v in r.items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        row[k] = None
                    else:
                        row[k] = v
                clean_rows.append(row)

            # Markdown output
            md = f"## A股行业板块排名 (按 {sort_by} {sort_order})\n\n"
            md += f"**行业总数**: {total} | **返回**: {len(results)} 个 | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 行业 | 涨跌幅% | 上涨 | 下跌 | 换手率% | 振幅 | 领涨股 | 领涨涨幅 |\n"
            md += "|------|---------|------|------|---------|------|--------|----------|\n"
            for r in clean_rows:
                md += (
                    f"| {r.get('name', '')} "
                    f"| {_safe_fmt(r.get('change_pct'), '+.2f')} "
                    f"| {r.get('rise_count', 0)} "
                    f"| {r.get('fall_count', 0)} "
                    f"| {_safe_fmt(r.get('turnover_rate'))} "
                    f"| {_safe_fmt(r.get('amplitude'))} "
                    f"| {r.get('top_stock', '')} "
                    f"| {_safe_fmt(r.get('top_stock_change'), '+.2f')} |\n"
                )

            artifact = create_artifact_envelope(
                component_type=ComponentType.STOCK_SCREENER,
                name="A股行业板块排名",
                content={"markdown": md, "data": clean_rows},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_industry_ranking failed: {e}")
            error_artifact = create_artifact_envelope(
                component_type=ComponentType.STOCK_SCREENER,
                name="行业排名错误",
                content={"error": str(e)},
                description=f"行业板块排名查询失败: {e}",
            )
            return create_artifact_response(
                summary=f"行业板块排名查询失败: {e}",
                artifact=error_artifact,
            )

    # ------------------------------------------------------------------
    # get_concept_ranking — A-share concept board ranking
    # ------------------------------------------------------------------
    @mcp.tool(tags={"quantitative", "sector", "concept"})
    async def get_concept_ranking(
        sort_by: str = "change_pct",
        sort_order: str = "desc",
        limit: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """A股概念板块实时排名(按涨跌幅等对约400个概念题材板块排名).

        WHEN TO USE: 用户想看今天哪些概念/题材板块活跃, 或追踪市场热点时调用.
        典型触发: "今天AI概念怎么样" "概念板块排名" "新能源题材" "热点题材" "概念轮动".
        CONCEPT: 按涨跌幅/换手率等对约400个概念板块(半导体/AI/碳中和/元宇宙等)排名,
        展示涨跌家数/振幅/领涨股, 用于追踪市场题材和热点轮动.
        DIFFERENTIATION: 本工具是概念/题材板块排名; 行业板块排名用get_industry_ranking;
        个股多条件筛选用screen_stocks; 美股板块表现用get_us_market_overview.
        next_recommended_tools: get_industry_ranking, screen_stocks
        """
        if ctx:
            await ctx.info(f"获取概念板块排名: sort_by={sort_by}, limit={limit}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_concept_ranking", sort_by=sort_by, limit=limit)

            result = await Container.market_gateway().get_concept_ranking(
                sort_by=sort_by, sort_order=sort_order, limit=limit,
            )

            elapsed = time.perf_counter() - t0
            results = result.get("results", [])
            total = result.get("total", 0)

            summary = f"概念板块排名: 共 {total} 个概念, 返回前 {len(results)} 个 (耗时 {elapsed:.1f}s)"

            # Sanitize results
            clean_rows = []
            for r in results:
                row = {}
                for k, v in r.items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        row[k] = None
                    else:
                        row[k] = v
                clean_rows.append(row)

            # Markdown output
            md = f"## A股概念板块排名 (按 {sort_by} {sort_order})\n\n"
            md += f"**概念总数**: {total} | **返回**: {len(results)} 个 | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 概念 | 涨跌幅% | 上涨 | 下跌 | 换手率% | 振幅 | 领涨股 | 领涨涨幅 |\n"
            md += "|------|---------|------|------|---------|------|--------|----------|\n"
            for r in clean_rows:
                md += (
                    f"| {r.get('name', '')} "
                    f"| {_safe_fmt(r.get('change_pct'), '+.2f')} "
                    f"| {r.get('rise_count', 0)} "
                    f"| {r.get('fall_count', 0)} "
                    f"| {_safe_fmt(r.get('turnover_rate'))} "
                    f"| {_safe_fmt(r.get('amplitude'))} "
                    f"| {r.get('top_stock', '')} "
                    f"| {_safe_fmt(r.get('top_stock_change'), '+.2f')} |\n"
                )

            artifact = create_artifact_envelope(
                component_type=ComponentType.STOCK_SCREENER,
                name="A股概念板块排名",
                content={"markdown": md, "data": clean_rows},
                description=summary,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(f"get_concept_ranking failed: {e}")
            error_artifact = create_artifact_envelope(
                component_type=ComponentType.STOCK_SCREENER,
                name="概念排名错误",
                content={"error": str(e)},
                description=f"概念板块排名查询失败: {e}",
            )
            return create_artifact_response(
                summary=f"概念板块排名查询失败: {e}",
                artifact=error_artifact,
            )
