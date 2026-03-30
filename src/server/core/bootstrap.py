# src/server/core/bootstrap.py
"""Application bootstrap helpers.

Provides a single initialization entrypoint for connections/adapters to avoid
duplicate registration across FastAPI and FastMCP lifespans.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from src.server.core.dependencies import Container
from src.server.utils.logger import logger


_bootstrap_lock = asyncio.Lock()
_initialized: bool = False


async def init_adapters() -> None:
    """Initialize connections and register adapters exactly once."""
    global _initialized

    if _initialized:
        return

    async with _bootstrap_lock:
        if _initialized:
            return

        logger.info("🚀 Bootstrapping application dependencies")

        redis = Container.redis()
        await redis.connect()
        logger.info("✅ Redis connection established")

        # Initialize PostgreSQL (Security Master) with adaptive fallback
        postgres = Container.postgres()
        postgres_ok = await postgres.connect()
        if postgres_ok:
            logger.info("✅ PostgreSQL connection established")
        else:
            logger.warning("⚠️ PostgreSQL not available, will use fallback storage")

        security_master_repo = Container.security_master_repo()
        await security_master_repo.ensure_schema()
        await _load_alias_seeds(security_master_repo)

        config = Container.config()

        # Initialize Tushare (optional)
        tushare_available = False
        if config.tushare.is_available:
            tushare = Container.tushare()
            tushare_available = await tushare.connect()
            if tushare_available:
                logger.info("✅ Tushare connection established")
            else:
                logger.warning("⚠️ Tushare connection failed - will use fallback adapters")
        else:
            logger.info(
                "ℹ️  Tushare disabled (set TUSHARE_ENABLED=True and provide token to enable)"
            )

        # Initialize FinnHub (optional)
        finnhub_available = False
        if config.finnhub.is_available:
            finnhub = Container.finnhub()
            await finnhub.connect()
            finnhub_available = True
            logger.info("✅ FinnHub connection established")
        else:
            logger.info(
                "ℹ️  FinnHub disabled (set FINNHUB_ENABLED=True and provide API key to enable)"
            )

        # Initialize Baostock
        baostock = Container.baostock()
        await baostock.connect()
        logger.info("✅ Baostock connection established")

        # Register adapters with MarketGateway
        logger.info("📦 Registering data adapters...")
        gateway = Container.market_gateway()

        # A股数据源 - 按优先级注册
        if tushare_available:
            gateway.register_adapter(Container.tushare_adapter())
        gateway.register_adapter(Container.akshare_adapter())
        gateway.register_adapter(Container.baostock_adapter())

        # 加密货币数据源
        gateway.register_adapter(Container.crypto_adapter())
        gateway.register_adapter(Container.ccxt_adapter())

        # 期货数据源（优先于 Yahoo）
        gateway.register_adapter(Container.futures_adapter())

        # Twelve Data（现货/FX/部分股票）
        gateway.register_adapter(Container.twelve_data_adapter())

        # 现货贵金属数据源（Alpha Vantage）
        gateway.register_adapter(Container.alpha_vantage_adapter())

        # US macro 数据源（FRED）
        if config.api_keys.fred:
            gateway.register_adapter(Container.fred_adapter())
            logger.info("✅ FRED adapter registered")
        else:
            logger.info("ℹ️  FRED disabled (set FRED_API_KEY to enable US macro tools)")

        # 美股数据源
        gateway.register_adapter(Container.yahoo_adapter())
        if finnhub_available:
            gateway.register_adapter(Container.finnhub_adapter())

        # Create and inject MarketRouter into gateway
        router = Container.market_router()
        gateway._router = router

        logger.info(
            "✅ All adapters registered (A-share: %sAkshare > Baostock)",
            "Tushare > " if tushare_available else "",
        )

        # Initialize Structured Data subsystem (requires PostgreSQL)
        if postgres_ok:
            await _init_structured_data(postgres)
        else:
            logger.info("ℹ️  Structured data subsystem skipped (PostgreSQL required)")

        _initialized = True


async def _load_alias_seeds(security_master_repo) -> None:
    """Load alias seeds into security master (best-effort)."""
    try:
        seed_path = os.getenv(
            "ALIASES_SEED_PATH",
            str(Path(__file__).resolve().parents[1] / "config" / "aliases_seed.json"),
        )
        if not seed_path or not Path(seed_path).exists():
            return
        with open(seed_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return
        for item in data:
            alias = item.get("alias")
            normalized = item.get("normalized")
            if not alias or not normalized:
                continue
            await security_master_repo.upsert_alias_for_listing(
                normalized=normalized,
                alias=alias,
                asset_type=item.get("asset_type") or "stock",
                source=item.get("source") or "seed",
                confidence=item.get("confidence"),
                locale=item.get("locale"),
            )
        logger.info("✅ Alias seeds loaded", count=len(data))
    except Exception as e:
        logger.warning("Alias seed load failed", error=str(e))


async def shutdown_adapters() -> None:
    """Placeholder for future graceful shutdown logic."""
    try:
        postgres = Container.postgres()
        await postgres.disconnect()
    except Exception:
        pass
    return None


async def _init_structured_data(postgres_conn) -> None:
    """Initialize the structured data subsystem — repos, registry, orchestrator, runner.

    Best-effort: logs warnings if something fails but does not block app startup.
    """
    try:
        from src.server.domain.structured_data.repositories.raw_repository import RawRepository
        from src.server.domain.structured_data.repositories.candidate_repository import CandidateRepository
        from src.server.domain.structured_data.repositories.canonical_repository import CanonicalRepository
        from src.server.domain.structured_data.repositories.issue_repository import IssueRepository
        from src.server.domain.structured_data.registry import build_default_registry
        from src.server.domain.structured_data.orchestrator import Orchestrator
        from src.server.domain.structured_data.scheduler.runner import TaskRunner
        from src.server.domain.structured_data.approval_service import ApprovalService
        from src.server.domain.structured_data.publish_service import PublishService

        # Create repositories
        raw_repo = RawRepository(postgres_conn)
        candidate_repo = CandidateRepository(postgres_conn)
        canonical_repo = CanonicalRepository(postgres_conn)
        issue_repo = IssueRepository(postgres_conn)

        # Ensure schemas (creates tables if missing)
        await raw_repo.ensure_schema()
        await candidate_repo.ensure_schema()
        await canonical_repo.ensure_schema()
        await issue_repo.ensure_schema()

        # Build dataset registry with default configs
        registry = build_default_registry()

        # Register financial_statements normalizer + validator (if available)
        try:
            from src.server.domain.structured_data.normalize.financial_statements import FinancialStatementsNormalizer
            registry.register_normalizer("financial_statements", FinancialStatementsNormalizer())
        except Exception:
            logger.debug("Financial statements normalizer not loaded")

        try:
            from src.server.domain.structured_data.validate.financial_statements import FinancialStatementsValidator
            registry.register_validator("financial_statements", FinancialStatementsValidator())
        except Exception:
            logger.debug("Financial statements validator not loaded")

        # Create orchestrator
        orchestrator = Orchestrator(
            registry=registry,
            raw_repo=raw_repo,
            candidate_repo=candidate_repo,
            canonical_repo=canonical_repo,
            issue_repo=issue_repo,
        )

        # Create runner
        gateway = Container.market_gateway()
        runner = TaskRunner(
            registry=registry,
            raw_repo=raw_repo,
            gateway=gateway,
        )

        # Create services
        approval_service = ApprovalService(
            candidate_repo=candidate_repo,
            canonical_repo=canonical_repo,
            issue_repo=issue_repo,
        )
        publish_service = PublishService(
            candidate_repo=candidate_repo,
            canonical_repo=canonical_repo,
        )

        # Inject into route modules
        from src.server.api.routes.structured_data import set_structured_data_components
        from src.server.api.routes.admin import set_approval_service as _set_admin_approval_service
        set_structured_data_components(
            runner=runner,
            orchestrator=orchestrator,
            approval_service=approval_service,
            publish_service=publish_service,
        )
        _set_admin_approval_service(approval_service)

        logger.info(
            "✅ Structured data subsystem initialized",
            datasets=len(registry.list_all()),
        )
    except Exception as e:
        logger.warning(
            "⚠️  Structured data subsystem initialization failed (non-fatal)",
            error=str(e),
        )
