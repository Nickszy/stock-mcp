# src/server/api/routes/research_reports.py
"""Research reports REST API routes (proxied from news-mcp)."""

from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from src.server.utils.logger import logger
from src.server.core.use_cases import research_reports as rr_uc
from src.server.domain.response_contract import rest_response

router = APIRouter(prefix="/api/v1/research-reports", tags=["研报 Research Reports"])


@router.get("/search", summary="搜索研报")
async def search_research_reports(
    organization: Optional[str] = Query(None, description="机构名称(如 中信证券)"),
    author: Optional[str] = Query(None, description="作者"),
    title: Optional[str] = Query(None, description="标题关键词"),
    content: Optional[str] = Query(None, description="内容关键词"),
    ticker: Optional[str] = Query(None, description="股票代码/名称"),
    report_type: Optional[str] = Query(None, description="研报类型(如 行业研究/个股研究)"),
    start_date: Optional[str] = Query(None, description="起始日期(YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="截止日期(YYYY-MM-DD)"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    output_format: str = Query("json", description="输出格式: json/markdown"),
) -> Dict[str, Any]:
    try:
        result = await rr_uc.search_research_reports(
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
        return rest_response(data=result, source="news-mcp")
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"API error in search_research_reports: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
