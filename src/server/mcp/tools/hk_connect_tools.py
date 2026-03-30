# src/server/mcp/tools/hk_connect_tools.py
"""MCP tools for HK Connect / southbound flow data.

Tool list (4):
  - get_hk_connect_components
  - get_hsgt_fund_flow_summary
  - get_hsgt_hold_stock
  - get_hk_connect_overview
"""

from __future__ import annotations

from typing import Dict, Any

from fastmcp import Context, FastMCP

from src.server.core.use_cases import hk_connect as hc_uc
from src.server.mcp.tools.artifact_utils import create_artifact_envelope, create_artifact_response
from src.server.utils.logger import logger


def register_hk_connect_tools(mcp: FastMCP):
    @mcp.tool(tags={"hk-connect", "flow"})
    async def get_hk_connect_components(ctx: Context = None) -> Dict[str, Any]:
        """获取港股通成分股.

        WHEN TO USE: 用户问"港股通成分股""南向可买标的".
        CONCEPT: 港股通成分股是内地资金可通过互联互通交易的香港股票池。
        DIFFERENTIATION: 通道可交易范围；资金流看 get_hsgt_fund_flow_summary；持股看 get_hsgt_hold_stock。
        next_recommended_tools: get_hsgt_hold_stock -> get_hsgt_fund_flow_summary -> get_hk_market_overview
        """
        if ctx:
            await ctx.info("🔗 港股通成分股")
        try:
            result = await hc_uc.get_hk_connect_components()
            summary = f"港股通成分股: {len(result.get('data', []))}只"
            artifact = create_artifact_envelope(component_type="hk_connect_components", name="港股通成分股", content=result, description=summary, metadata={"type": "hk_connect_components"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_hk_connect_components error", error=str(e))
            return create_artifact_response(summary=f"获取港股通成分股失败: {e}", artifact=create_artifact_envelope(component_type="hk_connect_components", name="港股通成分股", content={"error": str(e)}, description=f"获取港股通成分股失败: {e}", visible_to_llm=True))

    @mcp.tool(tags={"hk-connect", "flow"})
    async def get_hsgt_fund_flow_summary(ctx: Context = None) -> Dict[str, Any]:
        """获取沪深港通资金流汇总."""
        if ctx:
            await ctx.info("🔗 互联互通资金流")
        try:
            result = await hc_uc.get_hsgt_fund_flow_summary()
            summary = f"互联互通资金流: {len(result.get('data', []))}条"
            artifact = create_artifact_envelope(component_type="hsgt_fund_flow", name="互联互通资金流", content=result, description=summary, metadata={"type": "hsgt_fund_flow"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_hsgt_fund_flow_summary error", error=str(e))
            return create_artifact_response(summary=f"获取互联互通资金流失败: {e}", artifact=create_artifact_envelope(component_type="hsgt_fund_flow", name="互联互通资金流", content={"error": str(e)}, description=f"获取互联互通资金流失败: {e}", visible_to_llm=True))

    @mcp.tool(tags={"hk-connect", "flow"})
    async def get_hsgt_hold_stock(
        market: str = "港股通",
        indicator: str = "5日排行",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取港股通持股排行/明细."""
        if ctx:
            await ctx.info("🔗 港股通持股排行")
        try:
            result = await hc_uc.get_hsgt_hold_stock(market=market, indicator=indicator)
            summary = f"{market}{indicator}: {len(result.get('data', []))}条"
            artifact = create_artifact_envelope(component_type="hsgt_hold_stock", name="港股通持股排行", content=result, description=summary, metadata={"type": "hsgt_hold_stock", "market": market, "indicator": indicator}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_hsgt_hold_stock error", error=str(e))
            return create_artifact_response(summary=f"获取港股通持股排行失败: {e}", artifact=create_artifact_envelope(component_type="hsgt_hold_stock", name="港股通持股排行", content={"error": str(e)}, description=f"获取港股通持股排行失败: {e}", visible_to_llm=True))

    @mcp.tool(tags={"hk-connect", "flow"})
    async def get_hk_connect_overview(ctx: Context = None) -> Dict[str, Any]:
        """获取港股通/南向资金概览.

        WHEN TO USE: 用户问"南向资金怎么样""港股通概览""互联互通资金与持股".
        CONCEPT: 聚合可买股票池、互联互通资金流和港股通持股排行，提供南向资金研究快照。
        DIFFERENTIATION: 港股通总览；单项看 get_hsgt_fund_flow_summary / get_hsgt_hold_stock / get_hk_connect_components。
        next_recommended_tools: get_hsgt_fund_flow_summary -> get_hsgt_hold_stock -> get_hk_market_overview
        """
        if ctx:
            await ctx.info("🔗 港股通概览")
        try:
            result = await hc_uc.get_hk_connect_overview()
            counts = result.get('data', {}).get('counts', {}) if isinstance(result, dict) else {}
            summary = f"港股通概览: 成分股={counts.get('components', 0)} 资金流={counts.get('fund_flow', 0)} 持股排行={counts.get('hold_rank', 0)}"
            artifact = create_artifact_envelope(component_type="hk_connect_overview", name="港股通概览", content=result, description=summary, metadata={"type": "hk_connect_overview"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_hk_connect_overview error", error=str(e))
            return create_artifact_response(summary=f"获取港股通概览失败: {e}", artifact=create_artifact_envelope(component_type="hk_connect_overview", name="港股通概览", content={"error": str(e)}, description=f"获取港股通概览失败: {e}", visible_to_llm=True))
