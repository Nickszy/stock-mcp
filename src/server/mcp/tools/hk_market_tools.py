# src/server/mcp/tools/hk_market_tools.py
"""MCP tools for Hong Kong market data.

Tool list (4):
  - get_hk_market_spot
  - get_hk_hot_rank
  - get_hk_main_board
  - get_hk_market_overview
"""

from __future__ import annotations

from typing import Dict, Any

from fastmcp import Context, FastMCP

from src.server.core.use_cases import hk_market as hk_uc
from src.server.mcp.tools.artifact_utils import create_artifact_envelope, create_artifact_response
from src.server.utils.logger import logger


def register_hk_market_tools(mcp: FastMCP):
    @mcp.tool(tags={"hk", "market"})
    async def get_hk_market_spot(ctx: Context = None) -> Dict[str, Any]:
        """获取港股全市场实时行情.

        WHEN TO USE: 用户问"港股市场行情""港股全市场""香港股票列表".
        CONCEPT: 提供港股市场全量实时行情快照，适合做筛选、排序、横截面分析。
        DIFFERENTIATION: 全市场快照；主板看 get_hk_main_board；热度看 get_hk_hot_rank。
        next_recommended_tools: get_hk_hot_rank -> get_hk_market_overview -> get_hk_main_board
        """
        if ctx:
            await ctx.info("🇭🇰 港股全市场")
        try:
            result = await hk_uc.get_hk_market_spot()
            summary = f"港股全市场: {len(result.get('data', []))}只"
            artifact = create_artifact_envelope(component_type="hk_market_spot", name="港股全市场", content=result, description=summary, metadata={"type": "hk_market_spot"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_hk_market_spot error", error=str(e))
            return create_artifact_response(summary=f"获取港股全市场失败: {e}", artifact=create_artifact_envelope(component_type="hk_market_spot", name="港股全市场", content={"error": str(e)}, description=f"获取港股全市场失败: {e}", visible_to_llm=True))

    @mcp.tool(tags={"hk", "market"})
    async def get_hk_hot_rank(ctx: Context = None) -> Dict[str, Any]:
        """获取港股热度排行."""
        if ctx:
            await ctx.info("🇭🇰 港股热度榜")
        try:
            result = await hk_uc.get_hk_hot_rank()
            summary = f"港股热度榜: {len(result.get('data', []))}只"
            artifact = create_artifact_envelope(component_type="hk_hot_rank", name="港股热度榜", content=result, description=summary, metadata={"type": "hk_hot_rank"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_hk_hot_rank error", error=str(e))
            return create_artifact_response(summary=f"获取港股热度榜失败: {e}", artifact=create_artifact_envelope(component_type="hk_hot_rank", name="港股热度榜", content={"error": str(e)}, description=f"获取港股热度榜失败: {e}", visible_to_llm=True))

    @mcp.tool(tags={"hk", "market"})
    async def get_hk_main_board(ctx: Context = None) -> Dict[str, Any]:
        """获取港股主板实时行情."""
        if ctx:
            await ctx.info("🇭🇰 港股主板")
        try:
            result = await hk_uc.get_hk_main_board()
            summary = f"港股主板: {len(result.get('data', []))}只"
            artifact = create_artifact_envelope(component_type="hk_main_board", name="港股主板", content=result, description=summary, metadata={"type": "hk_main_board"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_hk_main_board error", error=str(e))
            return create_artifact_response(summary=f"获取港股主板失败: {e}", artifact=create_artifact_envelope(component_type="hk_main_board", name="港股主板", content={"error": str(e)}, description=f"获取港股主板失败: {e}", visible_to_llm=True))

    @mcp.tool(tags={"hk", "market"})
    async def get_hk_market_overview(ctx: Context = None) -> Dict[str, Any]:
        """获取港股市场概览.

        WHEN TO USE: 用户问"港股市场怎么样""港股概览""香港市场热度和广度".
        CONCEPT: 聚合港股全市场、主板和热度榜，提供一屏式市场快照。
        DIFFERENTIATION: 港股总览；细分看 get_hk_market_spot / get_hk_main_board / get_hk_hot_rank。
        next_recommended_tools: get_hk_market_spot -> get_hk_hot_rank -> get_hk_main_board
        """
        if ctx:
            await ctx.info("🇭🇰 港股市场概览")
        try:
            result = await hk_uc.get_hk_market_overview()
            counts = result.get('data', {}).get('counts', {}) if isinstance(result, dict) else {}
            summary = f"港股概览: 全市场={counts.get('spot', 0)} 主板={counts.get('main_board', 0)} 热榜={counts.get('hot_rank', 0)}"
            artifact = create_artifact_envelope(component_type="hk_market_overview", name="港股概览", content=result, description=summary, metadata={"type": "hk_market_overview"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_hk_market_overview error", error=str(e))
            return create_artifact_response(summary=f"获取港股概览失败: {e}", artifact=create_artifact_envelope(component_type="hk_market_overview", name="港股概览", content={"error": str(e)}, description=f"获取港股概览失败: {e}", visible_to_llm=True))
