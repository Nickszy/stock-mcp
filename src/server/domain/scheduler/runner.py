# src/server/domain/scheduler/runner.py
"""Scheduler runner — executes a job by collecting data from existing services."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from src.server.domain.scheduler.models import (
    ScheduledAnalysisJob,
    AnalysisRun,
    AnalysisRunItem,
    AnalysisRunStatus,
    AnalysisType,
)
from src.server.domain.scheduler.repository import RedisSchedulerRepository
from src.server.domain.watchlist.repository import RedisWatchlistRepository
from src.server.utils.logger import logger


class SchedulerRunner:
    """Execute a scheduled analysis job: read watchlist, collect data for each ticker."""

    def __init__(
        self,
        scheduler_repo: RedisSchedulerRepository,
        watchlist_repo: RedisWatchlistRepository,
        gateway=None,
        news_service=None,
        filings_service=None,
        research_report_service=None,
    ):
        self._scheduler_repo = scheduler_repo
        self._watchlist_repo = watchlist_repo
        self._gateway = gateway
        self._news_service = news_service
        self._filings_service = filings_service
        self._research_report_service = research_report_service

    async def run_job(self, job: ScheduledAnalysisJob) -> AnalysisRun:
        """Execute a single job: iterate tickers, collect data, persist run result."""
        run = AnalysisRun(
            job_id=job.job_id,
            status=AnalysisRunStatus.running,
        )
        run = await self._scheduler_repo.save_run(run)

        logger.info(
            "Starting analysis run",
            run_id=run.run_id,
            job_id=job.job_id,
        )

        # Load watchlist
        watchlist = await self._watchlist_repo.get_watchlist(
            job.user_id, job.watchlist_id,
        )
        if watchlist is None:
            run.status = AnalysisRunStatus.failed
            run.error = f"Watchlist {job.watchlist_id} not found"
            run.finished_at = datetime.now(UTC)
            await self._scheduler_repo.save_run(run)
            return run

        items: List[AnalysisRunItem] = []
        errors: List[str] = []

        for position in watchlist.positions:
            try:
                item = await self._collect_for_ticker(
                    ticker=position.ticker,
                    analysis_types=job.analysis_types,
                )
                items.append(item)
            except Exception as e:
                errors.append(f"{position.ticker}: {e}")
                logger.warning(
                    "Failed to collect data for ticker",
                    ticker=position.ticker,
                    error=str(e),
                )

        # Determine final status
        if errors and items:
            run.status = AnalysisRunStatus.partial
        elif errors and not items:
            run.status = AnalysisRunStatus.failed
        else:
            run.status = AnalysisRunStatus.success

        run.items = items
        run.error = "; ".join(errors) if errors else None
        run.finished_at = datetime.now(UTC)
        run.summary = self._build_summary(items, errors)
        await self._scheduler_repo.save_run(run)

        # Update job timestamps
        job.last_run_at = run.started_at
        job.updated_at = datetime.now(UTC)
        await self._scheduler_repo.save_job(job)

        logger.info(
            "Analysis run completed",
            run_id=run.run_id,
            job_id=job.job_id,
            status=run.status,
            items_count=len(items),
        )
        return run

    async def _collect_for_ticker(
        self,
        ticker: str,
        analysis_types: List[str],
    ) -> AnalysisRunItem:
        """Collect all requested data for a single ticker."""
        item = AnalysisRunItem(ticker=ticker)
        type_set = set(analysis_types)

        tasks: List[asyncio.Task] = []

        if AnalysisType.news in type_set and self._news_service:
            tasks.append(self._collect_news(ticker, item))
        if AnalysisType.filings in type_set and self._filings_service:
            tasks.append(self._collect_filings(ticker, item))
        if AnalysisType.research_reports in type_set and self._research_report_service:
            tasks.append(self._collect_reports(ticker, item))
        if AnalysisType.fact_pack in type_set and self._gateway:
            tasks.append(self._collect_fact_pack(ticker, item))

        # Run collections concurrently, each updates `item` in-place
        await asyncio.gather(*tasks, return_exceptions=True)
        return item

    async def _collect_news(self, ticker: str, item: AnalysisRunItem) -> None:
        """Collect news for ticker, best-effort."""
        try:
            result = await self._news_service.fetch_latest_news(ticker, days_back=3)
            if isinstance(result, dict) and "news" in result:
                item.news_items = result["news"][:10]
        except Exception as e:
            logger.warning("News collection failed", ticker=ticker, error=str(e))

    async def _collect_filings(self, ticker: str, item: AnalysisRunItem) -> None:
        """Collect recent filings for ticker, best-effort."""
        try:
            filings = await self._filings_service.fetch_ashare_filings(
                ticker, limit=5,
            )
            if isinstance(filings, list):
                item.filing_items = filings[:5]
        except Exception as e:
            logger.warning("Filings collection failed", ticker=ticker, error=str(e))

    async def _collect_reports(self, ticker: str, item: AnalysisRunItem) -> None:
        """Collect research reports for ticker, best-effort."""
        try:
            symbol = ticker.split(":", 1)[1] if ":" in ticker else ticker
            result = await self._research_report_service.search_reports(
                ticker=symbol, page_size=5,
            )
            if isinstance(result, dict) and "results" in result:
                item.report_items = result["results"][:5]
        except Exception as e:
            logger.warning("Reports collection failed", ticker=ticker, error=str(e))

    async def _collect_fact_pack(self, ticker: str, item: AnalysisRunItem) -> None:
        """Collect fact-pack snapshot for ticker, best-effort."""
        try:
            facts = await self._gateway.get_stock_fact_pack(ticker)
            if isinstance(facts, dict):
                item.fact_snapshot = facts
        except Exception as e:
            logger.warning("Fact pack collection failed", ticker=ticker, error=str(e))

    @staticmethod
    def _build_summary(items: List[AnalysisRunItem], errors: List[str]) -> str:
        """Build a short human-readable summary of the run."""
        parts: List[str] = []
        if items:
            parts.append(f"Analyzed {len(items)} ticker(s)")
        for it in items[:5]:
            tags = []
            if it.news_items:
                tags.append(f"{len(it.news_items)} news")
            if it.filing_items:
                tags.append(f"{len(it.filing_items)} filings")
            if it.report_items:
                tags.append(f"{len(it.report_items)} reports")
            if tags:
                parts.append(f"  {it.ticker}: {', '.join(tags)}")
        if errors:
            parts.append(f"{len(errors)} error(s)")
        return "\n".join(parts) if parts else "No data collected"
