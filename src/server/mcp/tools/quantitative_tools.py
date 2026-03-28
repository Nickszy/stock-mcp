# src/server/mcp/tools/quantitative_tools.py
"""MCP tools for A-share quantitative analysis.

Tools:
  - screen_stocks: Quantitative stock screener with multi-criteria filtering
"""

from typing import Any, Dict, Optional
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
from src.server.mcp.tools.output_format_utils import (
    _format_table_markdown,
    OutputFormat,
)


def _fmt_cap(b: Optional[float]) -> str:
    """Format market cap in billions to readable string."""
    if b is None:
        return "-"
    if b >= 10000:
        return f"{b/10000:.1f}万亿"
    if b >= 100:
        return f"{b/100:.1f}千亿"
    return f"{b:.1f}亿"


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
        output_format: OutputFormat = "markdown",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Quantitative stock screener for all A-share stocks.

        Filters the entire A-share universe (~5000 stocks) by multiple criteria
        such as PE, PB, market cap, turnover rate, volume ratio, price change, etc.
        Returns ranked results sorted by any metric.

        Typical use cases:
        - "Find large-cap value stocks: PE < 15, market cap > 500亿"
        - "High turnover momentum stocks: turnover_rate > 8%, change_pct > 3%"
        - "Oversold large caps: 60d change < -20%, market cap > 1000亿"
        - "Low PE + low PB screener: PE 5-15, PB 0.5-1.5"

        Args:
            min_pe: Minimum PE (TTM). Filters out negative PE (loss-makers).
            max_pe: Maximum PE (TTM).
            min_pb: Minimum price-to-book ratio.
            max_pb: Maximum price-to-book ratio.
            min_market_cap: Minimum total market cap in CNY *billions* (e.g. 500 = 500亿).
            max_market_cap: Maximum total market cap in CNY billions.
            min_price: Minimum latest price.
            max_price: Maximum latest price.
            min_turnover_rate: Minimum turnover rate %.
            max_turnover_rate: Maximum turnover rate %.
            min_volume_ratio: Minimum volume ratio (量比).
            max_volume_ratio: Maximum volume ratio.
            min_change_pct: Minimum daily change %.
            max_change_pct: Maximum daily change %.
            min_ytd_change: Minimum year-to-date change %.
            max_ytd_change: Maximum year-to-date change %.
            min_60d_change: Minimum 60-day change %.
            max_60d_change: Maximum 60-day change %.
            min_amplitude: Minimum amplitude % (振幅).
            max_amplitude: Maximum amplitude %.
            exchange: Filter by exchange: "SSE" (Shanghai), "SZSE" (Shenzhen), "BSE" (Beijing).
            sort_by: Sort field. Options: market_cap, pe, pb, price, turnover_rate,
                volume_ratio, change_pct, ytd_change, change_60d, amplitude.
            sort_order: "desc" (default) or "asc".
            limit: Max results to return (default 50, max 200).
            output_format: "markdown" (default, human-readable) or "json".
            ctx: FastMCP Context.

        Returns:
            Filtered and ranked stock list with key metrics.
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

            if output_format == "json":
                return create_artifact_response(
                    summary=summary,
                    artifact=create_table_artifact(
                        component=ComponentType.STOCK_SCREENER,
                        data=results,
                        columns=["ticker", "name", "price", "change_pct", "pe", "pb",
                                 "market_cap_b", "turnover_rate", "volume_ratio"],
                    ),
                )

            # Markdown output
            md = f"## A股量化选股筛选结果\n\n"
            md += f"**筛选条件**: {filters or '无 (全市场)'}\n"
            md += f"**排序**: {sort_by} ({sort_order}) | **符合条件**: {total} 只 | **返回**: {len(results)} 只\n\n"

            md += "| 代码 | 名称 | 价格 | 涨跌幅% | PE(TTM) | PB | 市值 | 换手率% | 量比 |\n"
            md += "|------|------|------|---------|---------|-----|------|---------|------|\n"
            for s in results:
                cap_str = _fmt_cap(s.get("market_cap_b"))
                md += (
                    f"| {s.get('ticker', '')} | {s.get('name', '')} "
                    f"| {s.get('price', '-') or '-'} "
                    f"| {s.get('change_pct', 0):+.2f} "
                    f"| {s.get('pe', '-') or '-'} "
                    f"| {s.get('pb', '-') or '-'} "
                    f"| {cap_str} "
                    f"| {s.get('turnover_rate', 0):.2f} "
                    f"| {s.get('volume_ratio', 0):.2f} |\n"
                )

            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component=ComponentType.STOCK_SCREENER,
                    markdown=md,
                    data=results,
                ),
            )

        except Exception as e:
            logger.error(f"screen_stocks failed: {e}")
            return {"error": str(e), "results": []}
