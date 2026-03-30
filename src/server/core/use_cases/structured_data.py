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
# Financial statements fetcher
# ---------------------------------------------------------------------------

async def financial_statements_fetcher(
    dataset_key: str,
    source: str,
    business_key: Optional[str] = None,
    **kwargs,
) -> Optional[Dict[str, Any]]:
    """Fetcher that bridges MarketGateway → structured data pipeline.

    Calls the existing gateway to get financial data, then wraps it
    in a format suitable for the raw repository.

    When source is specified (e.g. "akshare" or "tushare"), attempts to
    call the matching adapter directly for more accurate field mapping.
    """
    from src.server.core.dependencies import Container
    gateway = Container.market_gateway()
    if gateway is None:
        logger.warning("Gateway not available for structured data fetch")
        return None

    # business_key should be a symbol like "600519" or "SSE:600519"
    symbol = business_key or kwargs.get("symbol")
    if not symbol:
        return None

    try:
        # Try source-specific adapter when source is explicitly provided
        result = None
        if source in ("akshare", "tushare"):
            result = await _fetch_from_adapter(gateway, source, symbol)

        # Fallback to generic gateway call
        if result is None:
            result = await gateway.get_financial_statements(
                ticker=symbol,
                report_type="all",
                periods=4,
            )

        if not result:
            return None

        # The gateway returns data with income/balance/cashflow sections
        # Build the business key from normalized symbol
        from src.server.domain.symbols.resolver import SymbolResolver
        resolved = await SymbolResolver.resolve(symbol)
        exchange = resolved.exchange if resolved else ""
        clean_symbol = resolved.symbol if resolved else symbol

        # Find the latest report period
        report_period = ""
        for section_key in ["income_statement", "balance_sheet", "cash_flow", "income", "balance", "cashflow"]:
            section = result.get(section_key)
            if isinstance(section, list) and section:
                for row in section:
                    if isinstance(row, dict):
                        period = row.get("end_date") or row.get("报告期") or ""
                        if period and (not report_period or period > report_period):
                            report_period = str(period).replace("-", "")[:8]

        biz_key = f"{exchange}:{clean_symbol}:{report_period}:all"

        return {
            "business_key": biz_key,
            "source": source,
            "data": result,
            "symbol": clean_symbol,
            "exchange": exchange,
        }

    except Exception as e:
        logger.error(
            "Financial statements fetcher failed",
            symbol=symbol,
            source=source,
            error=str(e),
        )
        return None


async def _fetch_from_adapter(gateway, source: str, symbol: str) -> Optional[Dict[str, Any]]:
    """Call a specific adapter directly for source-routed fetching."""
    try:
        adapter = gateway.get_adapter_by_provider(source)
        if adapter and hasattr(adapter, "get_financial_statements"):
            return await adapter.get_financial_statements(
                ticker=symbol,
                report_type="all",
                periods=4,
            )
    except Exception as e:
        logger.debug("Source-specific adapter fetch failed", source=source, error=str(e))
    return None


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

    # Register normalizers
    from src.server.domain.structured_data.normalize.financial_statements import (
        FinancialStatementsNormalizer,
    )
    fs_normalizer = FinancialStatementsNormalizer()
    registry.register_normalizer("financial_statements", fs_normalizer)

    # Register validators
    from src.server.domain.structured_data.validate.engine import ValidationEngine
    from src.server.domain.structured_data.validate.financial_statements import (
        register_financial_statement_rules,
    )
    validation_engine = ValidationEngine()
    register_financial_statement_rules(validation_engine)
    # Wrap validation_engine to have a validate() method compatible with orchestrator
    registry.register_validator("financial_statements", _ValidatorAdapter(validation_engine))

    # Register fetchers
    registry.register_fetcher("financial_statements", financial_statements_fetcher)

    # Create runner
    runner = TaskRunner(
        registry=registry,
        raw_repo=raw_repo,
        gateway=gateway,
    )

    # Create orchestrator
    orchestrator = Orchestrator(
        registry=registry,
        raw_repo=raw_repo,
        candidate_repo=candidate_repo,
        canonical_repo=canonical_repo,
        issue_repo=issue_repo,
    )

    # Store orchestrator reference for API routes
    from src.server.api.routes.structured_data import set_structured_data_components
    set_structured_data_components(runner=runner, orchestrator=orchestrator)

    logger.info(
        "Structured data subsystem initialized",
        datasets=len(registry.dataset_keys),
    )

    return runner


class _ValidatorAdapter:
    """Adapter to make ValidationEngine compatible with orchestrator's validator interface.

    The orchestrator expects a validator with a validate(normalized_data, config) method
    that returns a list of issue dicts.
    """

    def __init__(self, engine: "ValidationEngine"):
        self._engine = engine

    async def validate(self, normalized_data: dict, config: Any = None) -> list:
        """Validate normalized data and return list of issue dicts."""
        dataset_key = config.dataset_key if config else "financial_statements"
        business_key = normalized_data.get("business_key", "unknown")

        result = await self._engine.validate(
            dataset_key=dataset_key,
            business_key=business_key,
            data=normalized_data,
        )

        return [
            {
                "rule_name": issue.rule_name,
                "severity": issue.severity,
                "field_path": issue.field_path,
                "expected_value": issue.expected_value,
                "actual_value": issue.actual_value,
                "message": issue.message,
            }
            for issue in result.issues
        ]
