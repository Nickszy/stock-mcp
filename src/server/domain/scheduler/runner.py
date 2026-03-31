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
                    requested_sources=set(job.analysis_types),
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
        run.requested_analysis_types = list(job.analysis_types)
        run.watchlist_size = len(watchlist.positions)
        run.completed_tickers = len(items)
        run.failed_tickers = len(errors)
        self._populate_run_metadata(run)
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
        requested_sources: Optional[set] = None,
    ) -> AnalysisRunItem:
        """Collect all requested data for a single ticker."""
        item = AnalysisRunItem(ticker=ticker)
        # Normalize to string values to ensure consistent comparisons,
        # since analysis_types may contain enum members or strings.
        type_set = {t.value if isinstance(t, AnalysisType) else t for t in analysis_types}
        if requested_sources is None:
            requested_sources = set(type_set)
        else:
            requested_sources = {
                s.value if isinstance(s, AnalysisType) else s for s in requested_sources
            }

        tasks: List[asyncio.Task] = []

        if AnalysisType.news.value in type_set and self._news_service:
            tasks.append(self._collect_news(ticker, item))
        if AnalysisType.filings.value in type_set and self._filings_service:
            tasks.append(self._collect_filings(ticker, item))
        if AnalysisType.research_reports.value in type_set and self._research_report_service:
            tasks.append(self._collect_reports(ticker, item))
        if AnalysisType.fact_pack.value in type_set and self._gateway:
            tasks.append(self._collect_fact_pack(ticker, item))

        # Run collections concurrently, each updates `item` in-place
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any silent failures
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.warning(
                    "Collection task failed silently",
                    ticker=ticker,
                    error=str(r),
                )

        # Populate AI-friendly metadata
        self._populate_item_metadata(item, requested_sources)
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

    # ── Item-level AI-friendly metadata ──────────────────────────
    @staticmethod
    def _populate_item_metadata(
        item: AnalysisRunItem,
        requested_sources: set,
    ) -> None:
        """Compute coverage / quality / key-points for a single ticker."""
        # Use string keys consistently — matches AnalysisType.validate_list() output
        source_map: Dict[str, Any] = {
            AnalysisType.news.value: item.news_items,
            AnalysisType.filings.value: item.filing_items,
            AnalysisType.research_reports.value: item.report_items,
            AnalysisType.fact_pack.value: item.fact_snapshot,
        }

        counts: Dict[str, int] = {}
        available: List[str] = []
        missing: List[str] = []

        for src_type in requested_sources:
            key = src_type if isinstance(src_type, str) else src_type.value
            data = source_map.get(key)
            if isinstance(data, list):
                n = len(data)
            elif isinstance(data, dict):
                n = 1 if data else 0
            else:
                n = 0
            counts[key] = n
            if n > 0:
                available.append(key)
            else:
                missing.append(key)

        item.source_counts = counts
        item.available_sources = available
        item.missing_sources = missing

        total_requested = len(requested_sources)
        item.coverage_ratio = (
            round(len(available) / total_requested, 2)
            if total_requested > 0
            else 0.0
        )

        # Quality: high ≥3 sources OR 2+fact_pack; medium 1-2; low 0
        hit = len(available)
        has_fact_pack = "fact_pack" in available
        if hit >= 3 or (hit >= 2 and has_fact_pack):
            item.data_quality = "high"
        elif hit >= 1:
            item.data_quality = "medium"
        else:
            item.data_quality = "low"

        # Key points — deterministic, non-LLM
        kp: List[str] = []
        if item.news_items:
            kp.append(f"{len(item.news_items)} news article(s) in last 3 days")
        if item.filing_items:
            kp.append(f"{len(item.filing_items)} recent filing(s)")
        if item.report_items:
            kp.append(f"{len(item.report_items)} research report(s)")
        if item.fact_snapshot:
            kp.append("fact-pack snapshot available")
        if missing:
            kp.append(f"missing: {', '.join(missing)}")
        item.key_points = kp

    # ── Run-level AI-friendly metadata ─────────────────────────
    @staticmethod
    def _populate_run_metadata(run: AnalysisRun) -> None:
        """Aggregate item-level metadata into run-level summaries."""
        # Coverage summary: how many tickers hit each source type
        coverage: Dict[str, int] = {}
        for item in run.items:
            for src in item.available_sources:
                coverage[src] = coverage.get(src, 0) + 1
        run.coverage_summary = coverage

        # Data quality distribution
        quality_dist: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for item in run.items:
            quality_dist[item.data_quality] = (
                quality_dist.get(item.data_quality, 0) + 1
            )
        run.data_quality_summary = quality_dist

        # AI summary — concise paragraph for agent first-screen read
        parts: List[str] = []
        total = run.watchlist_size
        ok = run.completed_tickers
        fail = run.failed_tickers
        parts.append(
            f"Analyzed {ok}/{total} ticker(s)"
            + (f", {fail} failed" if fail else "")
            + "."
        )
        if run.requested_analysis_types:
            parts.append(
                f"Requested sources: {', '.join(run.requested_analysis_types)}."
            )
        if coverage:
            cov_desc = ", ".join(
                f"{src}: {cnt}/{ok}" for src, cnt in sorted(coverage.items())
            )
            parts.append(f"Coverage: {cov_desc}.")
        q_hi = quality_dist.get("high", 0)
        q_md = quality_dist.get("medium", 0)
        q_lo = quality_dist.get("low", 0)
        parts.append(
            f"Quality: {q_hi} high, {q_md} medium, {q_lo} low."
        )
        run.ai_summary = " ".join(parts)

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
