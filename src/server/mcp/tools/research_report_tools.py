# src/server/mcp/tools/research_report_tools.py
"""MCP tools for research reports (proxied from news-mcp).

Tool list (2):
  - search_research_reports  — search by ticker/org/keyword/date
  - get_stock_research       — quick per-stock research report list
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastmcp import Context, FastMCP

from src.server.core.use_cases import research_reports as rr_uc
from src.server.mcp.tools.artifact_utils import (
    create_artifact_envelope,
    create_artifact_response,
)
from src.server.utils.logger import logger


def register_research_report_tools(mcp: FastMCP):
    """Register research report tools."""

    @mcp.tool(tags={"research-report", "evidence"})
    async def search_research_reports(
        ticker: str = "",
        organization: str = "",
        title: str = "",
        report_type: str = "",
        start_date: str = "",
        end_date: str = "",
        page: int = 1,
        page_size: int = 10,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """搜索研报(按股票/机构/标题/类型/日期).

        WHEN TO USE: 用户问"某某股票有什么研报""机构观点""行业研究""分析师评级".
          AI做投研分析时, 研报是最重要的证据层——提供机构观点、评级、目标价.
        CONCEPT: 研报是券商/研究机构发布的深度分析报告, 包含基本面分析、估值模型、
          投资建议. 是专业投研的核心信息源.
        DIFFERENTIATION: 机构研报/证据层; 新闻看 search_market_news; 财报看 get_financial_reports.
        next_recommended_tools: get_financial_reports -> get_valuation_metrics -> get_cn_pmi

        Args:
            ticker: 股票代码或名称(如 600519/贵州茅台)
            organization: 机构名称(如 中信证券)
            title: 标题关键词
            report_type: 研报类型(如 行业研究/个股研究/投资策略)
            start_date: 起始日期 YYYY-MM-DD
            end_date: 截止日期 YYYY-MM-DD
            page: 页码
            page_size: 每页条数
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"📄 搜索研报: {ticker or title or '全部'}")
        try:
            result = await rr_uc.search_research_reports(
                ticker=ticker or None,
                organization=organization or None,
                title=title or None,
                report_type=report_type or None,
                start_date=start_date or None,
                end_date=end_date or None,
                page=page,
                page_size=page_size,
                output_format="json",
            )
            count = result.get("count", 0)
            summary = f"研报搜索: {count}条结果"
            if ticker:
                summary += f" (股票={ticker})"
            if organization:
                summary += f" (机构={organization})"

            artifact = create_artifact_envelope(
                component_type="research_reports",
                name="研报搜索",
                content=result,
                description=summary,
                metadata={"type": "search_research_reports"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except ValueError as e:
            # Service not configured
            summary = f"研报服务未配置: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="research_reports",
                    name="研报搜索",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )
        except Exception as e:
            logger.error("search_research_reports error", error=str(e))
            summary = f"搜索研报失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="research_reports",
                    name="研报搜索",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    @mcp.tool(tags={"research-report", "evidence"})
    async def get_stock_research(
        ticker: str,
        page_size: int = 10,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取某只股票的最新研报.

        WHEN TO USE: 用户问"茅台有什么研报""XX股票分析师怎么说""最近有什么研报覆盖".
          快速获取单只股票的所有相关研报, 用于了解机构观点和评级共识.
        CONCEPT: 个股研报聚焦于单一股票, 包含业绩预测、估值分析、投资评级和目标价.
          多份研报的共识反映市场主流观点.
        DIFFERENTIATION: 单票研报快查; 高级搜索(按机构/类型)用 search_research_reports.
        next_recommended_tools: search_research_reports -> get_financial_reports -> get_valuation_metrics

        Args:
            ticker: 股票代码或名称(如 600519/贵州茅台)
            page_size: 返回条数 (default 10)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"📄 个股研报: {ticker}")
        try:
            result = await rr_uc.search_research_reports(
                ticker=ticker,
                page_size=page_size,
                output_format="json",
            )
            count = result.get("count", 0)
            summary = f"{ticker}研报: {count}条"

            artifact = create_artifact_envelope(
                component_type="stock_research",
                name=f"{ticker} 研报",
                content=result,
                description=summary,
                metadata={"type": "stock_research", "ticker": ticker},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except ValueError as e:
            summary = f"研报服务未配置: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="stock_research",
                    name=f"{ticker} 研报",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )
        except Exception as e:
            logger.error("get_stock_research error", error=str(e))
            summary = f"获取{ticker}研报失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="stock_research",
                    name=f"{ticker} 研报",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )
