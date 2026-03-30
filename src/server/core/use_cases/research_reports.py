# src/server/core/use_cases/research_reports.py
"""Use cases for research report data (proxied from news-mcp)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.server.domain.services.research_report_service import ResearchReportService
from src.server.utils.logger import logger

_service = ResearchReportService()


async def search_research_reports(
    organization: Optional[str] = None,
    author: Optional[str] = None,
    title: Optional[str] = None,
    content: Optional[str] = None,
    ticker: Optional[str] = None,
    report_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    output_format: str = "json",
) -> Dict[str, Any]:
    """Search research reports from news-mcp."""
    logger.info("UseCase: search_research_reports", ticker=ticker, page=page)
    return await _service.search_reports(
        organization=organization,
        author=author,
        title=title,
        content=content,
        ticker=ticker,
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
        output_format=output_format,
    )
