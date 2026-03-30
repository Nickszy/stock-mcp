# src/server/domain/services/research_report_service.py
"""Research report service proxying sibling news-mcp research APIs."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from src.server.config.settings import get_settings
from src.server.utils.logger import logger


class ResearchReportService:
    """Thin client for research report data from sibling news-mcp service."""

    def __init__(self):
        settings = get_settings()
        self.base_url = getattr(settings, "news_mcp_base_url", "").rstrip("/")
        self.logger = logger

    async def search_reports(
        self,
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
        """Search research reports via news-mcp REST API."""
        if not self.base_url:
            raise ValueError("NEWS_MCP_BASE_URL is not configured")

        params = {
            "organization": organization,
            "author": author,
            "title": title,
            "content": content,
            "ticker": ticker,
            "report_type": report_type,
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": page_size,
            "output_format": output_format,
        }
        params = {k: v for k, v in params.items() if v not in (None, "")}

        url = f"{self.base_url}/api/v1/research/search"
        self.logger.info("ResearchReportService.search_reports", url=url, ticker=ticker, page=page)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        # news-mcp returns raw result, not stock-mcp rest_response envelope
        if isinstance(data, dict):
            if output_format == "json":
                return {
                    "results": data.get("results", []),
                    "count": data.get("count", 0),
                    "page": data.get("page", page),
                    "page_size": data.get("page_size", page_size),
                    "source": "news-mcp",
                }
            return {
                "markdown": data.get("markdown", ""),
                "count": data.get("count", 0),
                "page": data.get("page", page),
                "page_size": data.get("page_size", page_size),
                "source": "news-mcp",
            }

        return {"results": [], "count": 0, "page": page, "page_size": page_size, "source": "news-mcp"}
