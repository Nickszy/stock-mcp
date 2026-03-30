# src/server/domain/structured_data/scheduler/runner.py
"""Task runner — creates and executes dataset refresh jobs.

The runner is the single entry point for both on-demand and scheduled refreshes.
It creates a DatasetJob, fetches data from sources (via adapters), and hands
results to the raw repository for storage.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from src.server.utils.logger import logger

from ..enums import JobStatus, PipelineState
from ..registry import DatasetConfig, DatasetRegistry, RefreshTrigger
from ..repositories.raw_repository import RawRepository
from .policies import RefreshPolicyChain


class TaskRunner:
    """Unified task runner for dataset refresh jobs.

    Handles: on-demand refresh, scheduled refresh, retry logic.
    Does NOT handle normalization/validation (that's the orchestrator).
    """

    def __init__(
        self,
        registry: DatasetRegistry,
        raw_repo: RawRepository,
        gateway=None,  # MarketGateway for fetching data
        policy_chain: Optional[RefreshPolicyChain] = None,
    ):
        self._registry = registry
        self._raw_repo = raw_repo
        self._gateway = gateway
        self._policies = policy_chain or RefreshPolicyChain()
        self._running_jobs: Dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # On-demand refresh
    # ------------------------------------------------------------------
    async def refresh_on_demand(
        self,
        dataset_key: str,
        business_key: Optional[str] = None,
        source: Optional[str] = None,
        force: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """Trigger an on-demand refresh for a dataset.

        Args:
            dataset_key: Which dataset to refresh
            business_key: Optional specific entity (e.g. "SSE:600519")
            source: Optional specific source to use
            force: Force refresh even if TTL not expired

        Returns:
            Job result dict with job_id, status, counts
        """
        config = self._registry.require(dataset_key)

        # Check if refresh is needed (unless forced)
        if not force:
            decision = await self._policies.should_refresh(
                config, force=False, **kwargs,
            )
            if not decision:
                return {
                    "status": "skipped",
                    "reason": decision.reason,
                    "dataset_key": dataset_key,
                }

        # Create and run the job
        return await self._execute_job(
            config=config,
            trigger=RefreshTrigger.ON_DEMAND,
            business_key=business_key,
            source_override=source,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Scheduled refresh
    # ------------------------------------------------------------------
    async def refresh_scheduled(self, dataset_key: str) -> Dict[str, Any]:
        """Run a scheduled refresh for a dataset (called by cron)."""
        config = self._registry.require(dataset_key)

        if not config.is_active:
            return {"status": "skipped", "reason": "dataset_inactive"}

        return await self._execute_job(
            config=config,
            trigger=RefreshTrigger.SCHEDULED,
        )

    async def run_all_scheduled(self) -> List[Dict[str, Any]]:
        """Run all scheduled datasets. Returns list of results."""
        scheduled = self._registry.list_scheduled()
        results = []
        for config in scheduled:
            try:
                result = await self.refresh_scheduled(config.dataset_key)
                results.append(result)
            except Exception as e:
                logger.error(
                    "Scheduled refresh failed",
                    dataset_key=config.dataset_key,
                    error=str(e),
                )
                results.append({
                    "dataset_key": config.dataset_key,
                    "status": "error",
                    "error": str(e),
                })
        return results

    # ------------------------------------------------------------------
    # Core job execution
    # ------------------------------------------------------------------
    async def _execute_job(
        self,
        config: DatasetConfig,
        trigger: RefreshTrigger,
        business_key: Optional[str] = None,
        source_override: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Create a job, fetch data, store raw snapshots."""
        # Create job record
        source = source_override or (
            config.primary_source.source_name if config.primary_source else None
        )
        job_id = await self._raw_repo.create_job(
            dataset_key=config.dataset_key,
            triggered_by=trigger.value,
            source=source,
        )

        logger.info(
            "Starting dataset job",
            job_id=job_id,
            dataset_key=config.dataset_key,
            trigger=trigger.value,
            source=source,
        )

        await self._raw_repo.start_job(job_id)
        t0 = time.perf_counter()

        success_count = 0
        fail_count = 0
        total_records = 0
        error_message = None

        try:
            # Fetch data from configured source(s)
            results = await self._fetch_from_sources(
                config=config,
                business_key=business_key,
                source_override=source_override,
                **kwargs,
            )

            # Store raw snapshots
            for result in results:
                total_records += 1
                try:
                    biz_key = result.get("business_key", business_key or "unknown")
                    raw_data = result.get("data", result)
                    src = result.get("source", source or "unknown")

                    await self._raw_repo.insert_snapshot(
                        job_id=job_id,
                        dataset_key=config.dataset_key,
                        source=src,
                        business_key=biz_key,
                        raw_data=raw_data if isinstance(raw_data, dict) else {"data": raw_data},
                    )
                    success_count += 1
                except Exception as e:
                    fail_count += 1
                    logger.warning(
                        "Failed to store raw snapshot",
                        job_id=job_id,
                        error=str(e),
                    )

            elapsed = time.perf_counter() - t0
            await self._raw_repo.complete_job(
                job_id=job_id,
                success_count=success_count,
                fail_count=fail_count,
                total_records=total_records,
            )

            return {
                "job_id": job_id,
                "dataset_key": config.dataset_key,
                "status": "completed" if fail_count == 0 else "partial",
                "total_records": total_records,
                "success_count": success_count,
                "fail_count": fail_count,
                "elapsed_seconds": round(elapsed, 2),
                "trigger": trigger.value,
            }

        except Exception as e:
            error_message = str(e)
            elapsed = time.perf_counter() - t0
            logger.error(
                "Dataset job failed",
                job_id=job_id,
                dataset_key=config.dataset_key,
                error=error_message,
            )
            await self._raw_repo.complete_job(
                job_id=job_id,
                success_count=success_count,
                fail_count=fail_count,
                total_records=total_records,
                error_message=error_message,
            )
            return {
                "job_id": job_id,
                "dataset_key": config.dataset_key,
                "status": "failed",
                "error": error_message,
                "elapsed_seconds": round(elapsed, 2),
                "trigger": trigger.value,
            }

    async def _fetch_from_sources(
        self,
        config: DatasetConfig,
        business_key: Optional[str] = None,
        source_override: Optional[str] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Fetch data from sources using the registry's fetcher or gateway."""
        fetcher = self._registry.get_fetcher(config.dataset_key)

        if fetcher:
            # Use registered fetcher
            sources = config.sorted_sources
            if source_override:
                sources = [s for s in sources if s.source_name == source_override]
                if not sources:
                    sources = config.sorted_sources

            for source_cfg in sources:
                try:
                    result = await fetcher(
                        dataset_key=config.dataset_key,
                        source=source_cfg.source_name,
                        business_key=business_key,
                        **kwargs,
                    )
                    if result:
                        if isinstance(result, list):
                            return result
                        return [result]
                except Exception as e:
                    logger.warning(
                        "Fetcher failed for source",
                        dataset_key=config.dataset_key,
                        source=source_cfg.source_name,
                        error=str(e),
                    )
                    continue
            return []

        # Fallback: if no fetcher registered, return empty
        logger.warning(
            "No fetcher registered for dataset",
            dataset_key=config.dataset_key,
        )
        return []
