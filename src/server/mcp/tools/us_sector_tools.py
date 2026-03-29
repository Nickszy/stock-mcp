# src/server/mcp/tools/us_sector_tools.py
"""MCP tools for US sector ETF analysis.
Supports output_format: markdown (default, human-readable) or json (structured).

Active Tools (1):
  - get_us_sector_etf_analysis: 美股行业ETF走势分析 (对齐竞品 get_us_sector_etf_analysis)

Sector → ETF mapping (内置，无需外部配置):
  technology → XLK, financials → XLF, healthcare → XLV,
  energy → XLE, consumer discretionary → XLY, utilities → XLU,
  industrials → XLI, materials → XLB, real estate → XLRE,
  communication → XLC, semiconductor → SOXX, biotech → XBI,
  software → IGV, cloud → SKYY, cybersecurity → HACK, ai → AIQ
"""

from typing import Any, Dict

from fastmcp import FastMCP, Context

from src.server.core.use_cases import technical as technical_use_cases
from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_artifact_envelope,
    create_artifact_response,
)
from src.server.mcp.tools.output_format_utils import (
    _format_table_markdown,
    OutputFormat,
)


def register_us_sector_tools(mcp: FastMCP):
    """Register US sector ETF analysis tools."""

    @mcp.tool(tags={"us-sector", "etf"})
    async def get_us_sector_etf_analysis(
        sector_name: str,
        days: int = 30,
        output_format: OutputFormat = "markdown",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取美股行业ETF分析.

        WHEN TO USE: 用户问"美国科技板块表现如何"、"哪个行业最强".
        CONCEPT: 通过行业ETF(XLK/XLF/XLE等)观察美股板块轮动与强弱.
        DIFFERENTIATION: 美股行业级视角; A股板块用 get_sector_trend / get_market_money_flow.
        next_recommended_tools: get_us_valuation_metrics -> get_earnings_history"""
        if ctx:
            await ctx.info(f"🏭 美股板块ETF分析: {sector_name} ({days}d)")
        try:
            logger.info(
                "MCP tool: get_us_sector_etf_analysis",
                sector=sector_name,
                days=days,
            )
            data = await technical_use_cases.get_us_sector_etf_analysis(
                sector_name, days=days
            )

            etf = data.get("etf_ticker", "SPY")
            total_chg = data.get("total_change_pct", 0.0)
            trend_summary = data.get("trend_summary", "")

            # Weekly aggregated change for LLM
            direction = "上涨" if total_chg > 0 else "下跌"
            strength = (
                "强势"
                if abs(total_chg) > 5
                else "温和" if abs(total_chg) > 2 else "震荡"
            )
            summary = (
                f"美股{sector_name}板块 ({etf}): "
                f"{days}日{direction}{abs(total_chg):.2f}% ({strength}). "
                f"{trend_summary}"
            )

            # For JSON format, return original artifact structure
            if output_format == "json":
                artifact = create_artifact_envelope(
                    component_type=ComponentType.US_SECTOR_ETF,
                    name=f"{sector_name} 板块ETF ({etf})",
                    content=data,
                    description=summary,
                    metadata={
                        "sector": sector_name,
                        "etf_ticker": etf,
                        "days": days,
                        "total_change_pct": total_chg,
                    },
                    visible_to_llm=False,
                    display_in_report=True,
                )
                return create_artifact_response(summary=summary, artifact=artifact)

            # For markdown format, render as readable text
            md_output = f"## {sector_name} 板块ETF分析 ({etf})\n\n"
            md_output += f"**摘要**: {summary}\n\n"

            # Add OHLCV table if available
            bars = data.get("bars", [])
            if bars:
                display_rows = []
                for bar in bars[-10:]:  # Show last 10 days
                    display_rows.append({
                        "trade_date": bar.get("trade_date"),
                        "open": bar.get("open"),
                        "high": bar.get("high"),
                        "low": bar.get("low"),
                        "close": bar.get("close"),
                        "volume": bar.get("volume"),
                    })
                md_output += _format_table_markdown(display_rows, f"近{len(display_rows)}日行情")

            artifact = create_artifact_envelope(
                component_type="us_sector_etf_markdown",
                name=f"板块ETF分析: {sector_name}",
                content={"markdown": md_output, "format": "markdown"},
                description=summary,
                metadata={"output_format": "markdown", "sector": sector_name},
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except Exception as e:
            logger.error(
                "get_us_sector_etf_analysis error",
                sector=sector_name,
                error=str(e),
            )
            summary = f"获取{sector_name}板块ETF数据失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_SECTOR_ETF,
                name=f"{sector_name} 板块ETF",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
