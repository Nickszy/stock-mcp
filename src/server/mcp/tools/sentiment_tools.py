# src/server/mcp/tools/sentiment_tools.py
"""MCP tools for market sentiment / QVIX data.

Tool list (5):
  - get_qvix_50etf
  - get_qvix_300etf
  - get_qvix_1000index
  - get_qvix_cyb
  - get_market_sentiment_overview
"""

from __future__ import annotations

from typing import Any, Dict

from fastmcp import Context, FastMCP

from src.server.core.use_cases import sentiment as sent_uc
from src.server.mcp.tools.artifact_utils import create_artifact_envelope, create_artifact_response
from src.server.utils.logger import logger


def _fmt_num(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.2f}"
    except Exception:
        return "N/A"


def _latest_qvix(result: Dict[str, Any]) -> Any:
    rows = result.get("data", []) if isinstance(result, dict) else []
    if not rows:
        return None
    latest = rows[-1]
    for key in latest:
        if str(key).lower() in {"close", "收盘", "收盘价", "qvix", "value"}:
            return latest.get(key)
    for value in latest.values():
        try:
            float(value)
            return value
        except Exception:
            continue
    return None


def register_sentiment_tools(mcp: FastMCP):
    @mcp.tool(tags={"sentiment", "qvix"})
    async def get_qvix_50etf(ctx: Context = None) -> Dict[str, Any]:
        """获取50ETF QVIX(中国版VIX).

        WHEN TO USE: 用户问"市场恐慌指数""50ETF波动率指数""A股VIX".
        CONCEPT: QVIX 是中国版 VIX，衡量期权隐含波动率，值越高通常代表恐慌越强。
        DIFFERENTIATION: 50ETF 情绪；宽基看 get_qvix_300etf / get_qvix_1000index；总览看 get_market_sentiment_overview.
        next_recommended_tools: get_qvix_300etf -> get_market_sentiment_overview -> get_option_summary
        """
        if ctx:
            await ctx.info("😨 QVIX 50ETF")
        try:
            result = await sent_uc.get_qvix_50etf()
            summary = f"50ETF QVIX: 最新={_fmt_num(_latest_qvix(result))}"
            artifact = create_artifact_envelope(component_type="qvix_50etf", name="50ETF QVIX", content=result, description=summary, metadata={"type": "qvix_50etf"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_qvix_50etf error", error=str(e))
            return create_artifact_response(summary=f"获取50ETF QVIX失败: {e}", artifact=create_artifact_envelope(component_type="qvix_50etf", name="50ETF QVIX", content={"error": str(e)}, description=f"获取50ETF QVIX失败: {e}", visible_to_llm=True))

    @mcp.tool(tags={"sentiment", "qvix"})
    async def get_qvix_300etf(ctx: Context = None) -> Dict[str, Any]:
        """获取300ETF QVIX."""
        if ctx:
            await ctx.info("😨 QVIX 300ETF")
        try:
            result = await sent_uc.get_qvix_300etf()
            summary = f"300ETF QVIX: 最新={_fmt_num(_latest_qvix(result))}"
            artifact = create_artifact_envelope(component_type="qvix_300etf", name="300ETF QVIX", content=result, description=summary, metadata={"type": "qvix_300etf"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_qvix_300etf error", error=str(e))
            return create_artifact_response(summary=f"获取300ETF QVIX失败: {e}", artifact=create_artifact_envelope(component_type="qvix_300etf", name="300ETF QVIX", content={"error": str(e)}, description=f"获取300ETF QVIX失败: {e}", visible_to_llm=True))

    @mcp.tool(tags={"sentiment", "qvix"})
    async def get_qvix_1000index(ctx: Context = None) -> Dict[str, Any]:
        """获取中证1000 QVIX."""
        if ctx:
            await ctx.info("😨 QVIX 中证1000")
        try:
            result = await sent_uc.get_qvix_1000index()
            summary = f"中证1000 QVIX: 最新={_fmt_num(_latest_qvix(result))}"
            artifact = create_artifact_envelope(component_type="qvix_1000index", name="中证1000 QVIX", content=result, description=summary, metadata={"type": "qvix_1000index"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_qvix_1000index error", error=str(e))
            return create_artifact_response(summary=f"获取中证1000 QVIX失败: {e}", artifact=create_artifact_envelope(component_type="qvix_1000index", name="中证1000 QVIX", content={"error": str(e)}, description=f"获取中证1000 QVIX失败: {e}", visible_to_llm=True))

    @mcp.tool(tags={"sentiment", "qvix"})
    async def get_qvix_cyb(ctx: Context = None) -> Dict[str, Any]:
        """获取创业板 QVIX."""
        if ctx:
            await ctx.info("😨 QVIX 创业板")
        try:
            result = await sent_uc.get_qvix_cyb()
            summary = f"创业板 QVIX: 最新={_fmt_num(_latest_qvix(result))}"
            artifact = create_artifact_envelope(component_type="qvix_cyb", name="创业板 QVIX", content=result, description=summary, metadata={"type": "qvix_cyb"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_qvix_cyb error", error=str(e))
            return create_artifact_response(summary=f"获取创业板 QVIX失败: {e}", artifact=create_artifact_envelope(component_type="qvix_cyb", name="创业板 QVIX", content={"error": str(e)}, description=f"获取创业板 QVIX失败: {e}", visible_to_llm=True))

    @mcp.tool(tags={"sentiment", "qvix"})
    async def get_market_sentiment_overview(ctx: Context = None) -> Dict[str, Any]:
        """获取市场情绪概览(QVIX 聚合).

        WHEN TO USE: 用户问"市场情绪怎么样""现在是恐慌还是贪婪""波动率 regime".
        CONCEPT: 聚合 50ETF/300ETF/中证1000/创业板 QVIX，给出 fear/neutral/greed 判断。
        DIFFERENTIATION: 情绪总览；单市场看 get_qvix_50etf / get_qvix_300etf 等。
        next_recommended_tools: get_qvix_50etf -> get_option_summary -> get_cn_credit_spread
        """
        if ctx:
            await ctx.info("😨 市场情绪总览")
        try:
            result = await sent_uc.get_market_sentiment_overview()
            data = result.get("data", {}) if isinstance(result, dict) else {}
            summary = f"市场情绪: regime={data.get('regime', 'unknown')}, avg_qvix={_fmt_num(data.get('avg_qvix'))}"
            artifact = create_artifact_envelope(component_type="market_sentiment", name="市场情绪概览", content=result, description=summary, metadata={"type": "market_sentiment"}, visible_to_llm=False, display_in_report=True)
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_market_sentiment_overview error", error=str(e))
            return create_artifact_response(summary=f"获取市场情绪概览失败: {e}", artifact=create_artifact_envelope(component_type="market_sentiment", name="市场情绪概览", content={"error": str(e)}, description=f"获取市场情绪概览失败: {e}", visible_to_llm=True))
