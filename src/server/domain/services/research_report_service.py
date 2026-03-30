# src/server/domain/services/research_report_service.py
"""Research report service — direct MySQL access to ifindyb table.

Previously proxied through news-mcp HTTP API. Now reads directly from the
ifindyb MySQL database (same iFinD research report data from 同花顺).

Configuration: NEWS_DB_URL env var (MySQL connection string)
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from src.server.config.settings import get_settings
from src.server.utils.logger import logger


class ResearchReportService:
    """Direct MySQL access to ifindyb research report data.

    Table structure (ifindyb):
    - SEQ: Primary key ID
    - DECLAREDATE: Publish date
    - F006V_YB003: Organization (机构名称)
    - F007V_YB003: Author (作者)
    - F009N_YB003: Page count
    - F010V_YB003: Content (正文/摘要)
    - F012V_YB003: Hash
    - RTIME: Record timestamp
    - TITLE: Title (标题)
    - hangye1-4: Industry tags (行业标签)
    - SECNAME: Stock name (股票名称)
    - code: Stock code (股票代码)
    """

    def __init__(self):
        settings = get_settings()
        self.db_url = getattr(settings, "news_db_url", "")
        self._engine: Optional[Engine] = None

    def _get_engine(self) -> Optional[Engine]:
        """Get or create SQLAlchemy engine lazily."""
        if not self.db_url:
            return None
        if self._engine is None:
            self._engine = create_engine(
                self.db_url,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=False,
            )
        return self._engine

    def is_available(self) -> bool:
        """Check if the database connection is available."""
        engine = self._get_engine()
        if not engine:
            return False
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.warning(f"Research report DB not available: {e}")
            return False

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
        """Search research reports from ifindyb table.

        Falls back to news-mcp proxy if DB is not configured.
        """
        engine = self._get_engine()

        if engine:
            return await self._search_direct(
                engine=engine,
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

        # Fallback: proxy to news-mcp
        return await self._search_via_proxy(
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

    async def _search_direct(
        self,
        engine: Engine,
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
        """Search directly from ifindyb MySQL table."""

        def _query():
            sql = """
                SELECT
                    SEQ, DECLAREDATE, F006V_YB003, F007V_YB003,
                    TITLE, F010V_YB003, SECNAME, code, hangye1, hangye2
                FROM ifindyb
                WHERE isvalid=1
            """
            params: Dict[str, Any] = {}

            if organization:
                sql += " AND F006V_YB003 = :organization"
                params["organization"] = organization

            if author:
                sql += " AND F007V_YB003 LIKE :author"
                params["author"] = f"%{author}%"

            if title:
                sql += " AND TITLE LIKE :title"
                params["title"] = f"%{title}%"

            if content:
                sql += " AND F010V_YB003 LIKE :content"
                params["content"] = f"%{content}%"

            if ticker:
                symbol = ticker.split(":", 1)[1] if ":" in ticker else ticker
                sql += " AND (code LIKE :ticker OR SECNAME LIKE :ticker)"
                params["ticker"] = f"%{symbol}%"

            if report_type:
                sql += " AND hangye1 LIKE :report_type"
                params["report_type"] = f"%{report_type}%"

            if start_date:
                sql += " AND DECLAREDATE >= :start_date"
                params["start_date"] = start_date

            if end_date:
                sql += " AND DECLAREDATE <= :end_date"
                params["end_date"] = end_date

            # Count query
            count_sql = sql.replace(
                "SELECT\n                    SEQ, DECLAREDATE, F006V_YB003, F007V_YB003,\n                    TITLE, F010V_YB003, SECNAME, code, hangye1, hangye2",
                "SELECT COUNT(*)",
            )
            offset = (page - 1) * page_size
            sql += " ORDER BY DECLAREDATE DESC LIMIT :limit OFFSET :offset"
            params["limit"] = page_size
            params["offset"] = offset

            results = []
            count = 0

            with engine.connect() as conn:
                # Get count
                row = conn.execute(text(count_sql), params).fetchone()
                if row:
                    count = row[0]

                # Get data
                rows = conn.execute(text(sql), params)
                for row in rows:
                    item = _row_to_dict(row)
                    if item:
                        results.append(item)

            return {"results": results, "count": count, "page": page, "page_size": page_size}

        loop = asyncio.get_event_loop()
        try:
            data = await asyncio.wait_for(
                loop.run_in_executor(None, _query),
                timeout=30,
            )
        except asyncio.TimeoutError:
            raise ValueError("Research report DB query timed out")
        except Exception as e:
            logger.error("Research report DB query failed", error=str(e), exc_info=True)
            raise

        if output_format == "markdown":
            data["markdown"] = _results_to_markdown(data["results"], page, page_size)

        data["source"] = "ifindyb"
        return data

    async def _search_via_proxy(
        self,
        **kwargs,
    ) -> Dict[str, Any]:
        """Fallback: proxy to news-mcp HTTP API."""
        import httpx

        output_format = kwargs.pop("output_format", "json")
        settings = get_settings()
        base_url = getattr(settings, "news_mcp_base_url", "").rstrip("/")

        if not base_url:
            raise ValueError("研报服务未配置: 需要设置 NEWS_DB_URL (直连) 或 NEWS_MCP_BASE_URL (代理)")

        params = {k: v for k, v in kwargs.items() if v not in (None, "")}

        url = f"{base_url}/api/v1/research/search"
        logger.info("ResearchReportService proxy fallback", url=url)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, dict):
            if output_format == "json":
                return {
                    "results": data.get("results", []),
                    "count": data.get("count", 0),
                    "page": data.get("page", kwargs.get("page", 1)),
                    "page_size": data.get("page_size", kwargs.get("page_size", 20)),
                    "source": "news-mcp",
                }
            return {
                "markdown": data.get("markdown", ""),
                "count": data.get("count", 0),
                "page": data.get("page", kwargs.get("page", 1)),
                "page_size": data.get("page_size", kwargs.get("page_size", 20)),
                "source": "news-mcp",
            }

        return {"results": [], "count": 0, "source": "news-mcp"}


def _row_to_dict(row: tuple) -> Optional[Dict[str, Any]]:
    """Convert a database row to a result dict."""
    try:
        seq, declare_date, org, author, title, content, secname, code, hangye1, hangye2 = row

        publish_time = ""
        if declare_date:
            if isinstance(declare_date, datetime):
                publish_time = declare_date.isoformat()
            else:
                publish_time = f"{declare_date}T00:00:00"

        # Truncate content for summary
        summary = ""
        if content:
            summary = content[:300] + "..." if len(content) > 300 else content

        return {
            "id": f"ifindyb-{seq}",
            "title": title or "",
            "content": content or "",
            "summary": summary,
            "publish_time": publish_time,
            "author": author or "",
            "organization": org or "",
            "stock_name": secname or "",
            "stock_code": code or "",
            "industry1": hangye1 or "",
            "industry2": hangye2 or "",
        }
    except Exception as e:
        logger.warning(f"Error converting research report row: {e}")
        return None


def _results_to_markdown(results: List[Dict], page: int, page_size: int) -> str:
    """Convert search results to a markdown summary."""
    if not results:
        return "未找到匹配的研报。"

    lines = [f"## 研报搜索结果 (第{page}页)\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"### {i}. {r.get('title', '无标题')}")
        lines.append(f"- **机构**: {r.get('organization', '未知')}")
        lines.append(f"- **作者**: {r.get('author', '未知')}")
        lines.append(f"- **日期**: {r.get('publish_time', '未知')[:10]}")
        if r.get("stock_name"):
            lines.append(f"- **标的**: {r.get('stock_name')} ({r.get('stock_code')})")
        if r.get("industry1"):
            lines.append(f"- **行业**: {r.get('industry1')}")
        if r.get("summary"):
            lines.append(f"- **摘要**: {r.get('summary')}")
        lines.append("")

    return "\n".join(lines)
