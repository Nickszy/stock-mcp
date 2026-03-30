# src/server/core/use_cases/structured_data.py
"""Use cases for structured data operations.

These are the high-level entry points used by both MCP tools and REST API routes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.server.domain.structured_data.registry import (
    DatasetConfig,
    DatasetRegistry,
    build_default_registry,
)
from src.server.domain.structured_data.orchestrator import Orchestrator
from src.server.domain.structured_data.scheduler.runner import TaskRunner
from src.server.utils.logger import logger


# ---------------------------------------------------------------------------
# Singleton registry
# ---------------------------------------------------------------------------

_registry: Optional[DatasetRegistry] = None


def get_registry() -> DatasetRegistry:
    """Get or create the singleton dataset registry."""
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry


def reset_registry() -> None:
    """Reset the registry (for testing)."""
    global _registry
    _registry = None


# ---------------------------------------------------------------------------
# Use cases
# ---------------------------------------------------------------------------

async def refresh_dataset(
    dataset_key: str,
    business_key: Optional[str] = None,
    source: Optional[str] = None,
    force: bool = False,
    runner: Optional[TaskRunner] = None,
) -> Dict[str, Any]:
    """Refresh a dataset on demand.

    Used by MCP tools and REST API when a user requests fresh data.
    """
    registry = get_registry()
    config = registry.require(dataset_key)

    if runner is None:
        raise RuntimeError("TaskRunner not initialized — call init_structured_data() first")

    return await runner.refresh_on_demand(
        dataset_key=dataset_key,
        business_key=business_key,
        source=source,
        force=force,
    )


async def list_datasets(
    active_only: bool = True,
) -> List[Dict[str, Any]]:
    """List available datasets with their configuration."""
    registry = get_registry()
    configs = registry.list_active() if active_only else registry.list_all()
    return [
        {
            "dataset_key": c.dataset_key,
            "display_name": c.display_name,
            "description": c.description,
            "sources": [s.source_name for s in c.sorted_sources],
            "soft_ttl_hours": c.ttl.soft_ttl_hours,
            "hard_ttl_hours": c.ttl.hard_ttl_hours,
            "auto_publish_threshold": c.auto_publish_threshold,
            "tags": c.tags,
            "is_active": c.is_active,
        }
        for c in configs
    ]


async def get_dataset_info(dataset_key: str) -> Dict[str, Any]:
    """Get detailed info about a specific dataset."""
    registry = get_registry()
    config = registry.require(dataset_key)
    return {
        "dataset_key": config.dataset_key,
        "display_name": config.display_name,
        "description": config.description,
        "primary_key_template": config.primary_key_template,
        "sources": [
            {
                "name": s.source_name,
                "priority": s.priority,
                "enabled": s.enabled,
                "max_retries": s.max_retries,
            }
            for s in config.sources
        ],
        "ttl": {
            "soft_hours": config.ttl.soft_ttl_hours,
            "hard_hours": config.ttl.hard_ttl_hours,
        },
        "cron_schedule": config.cron_schedule,
        "validation_rules": config.validation_rules,
        "auto_publish_threshold": config.auto_publish_threshold,
        "requires_approval": config.requires_approval,
        "tags": config.tags,
    }


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

async def init_structured_data(
    postgres_conn=None,
    gateway=None,
) -> TaskRunner:
    """Initialize the structured data subsystem.

    Call once at startup. Returns a TaskRunner for use in MCP/API handlers.
    """
    from src.server.domain.structured_data.repositories import (
        CanonicalRepository,
        CandidateRepository,
        IssueRepository,
        RawRepository,
    )

    registry = get_registry()

    # Create repositories (they handle their own schema)
    raw_repo = RawRepository(postgres_conn) if postgres_conn else None
    candidate_repo = CandidateRepository(postgres_conn) if postgres_conn else None
    canonical_repo = CanonicalRepository(postgres_conn) if postgres_conn else None
    issue_repo = IssueRepository(postgres_conn) if postgres_conn else None

    # Ensure schemas
    if raw_repo:
        await raw_repo.ensure_schema()
    if candidate_repo:
        await candidate_repo.ensure_schema()
    if canonical_repo:
        await canonical_repo.ensure_schema()
    if issue_repo:
        await issue_repo.ensure_schema()

    # Create runner
    runner = TaskRunner(
        registry=registry,
        raw_repo=raw_repo,
        gateway=gateway,
    )

    logger.info(
        "Structured data subsystem initialized",
        datasets=len(registry.dataset_keys),
    )

    return runner
