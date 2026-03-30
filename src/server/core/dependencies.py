# src/server/core/dependencies.py
"""Dependency injection container for the project.
All services, adapters, connections, cache, and settings are registered here.
Modules can obtain instances via `Container.xxx()`.
"""

from dependency_injector import containers, providers

from src.server.config.settings import get_settings
from src.server.infrastructure.connections.redis_connection import RedisConnection
from src.server.infrastructure.connections.tushare_connection import TushareConnection
from src.server.infrastructure.connections.finnhub_connection import FinnhubConnection
from src.server.infrastructure.connections.baostock_connection import BaostockConnection
from src.server.infrastructure.connections.postgres_connection import PostgresConnection

from src.server.infrastructure.cache.redis_cache import AsyncRedisCache

# Import adapter classes
from src.server.domain.adapters.yahoo_adapter import YahooAdapter
from src.server.domain.adapters.akshare_adapter import AkshareAdapter
from src.server.domain.adapters.crypto_adapter import CryptoAdapter
from src.server.domain.adapters.tushare_adapter import TushareAdapter
from src.server.domain.adapters.finnhub_adapter import FinnhubAdapter
from src.server.domain.adapters.baostock_adapter import BaostockAdapter
from src.server.domain.adapters.ccxt_adapter import CCXTAdapter
from src.server.domain.adapters.futures_adapter import FuturesAdapter
from src.server.domain.adapters.alpha_vantage_adapter import AlphaVantageAdapter
from src.server.domain.adapters.twelve_data_adapter import TwelveDataAdapter
from src.server.domain.adapters.fred_adapter import FredAdapter
from src.server.domain.adapters.edgar_adapter import EdgarAdapter

# Import service classes
from src.server.domain.services.fundamental_service import FundamentalService
from src.server.domain.services.news_service import NewsService
from src.server.domain.services.technical_service import TechnicalService
from src.server.domain.services.filings_service import FilingsService
from src.server.domain.services.money_flow_service import MoneyFlowService
from src.server.domain.services.chip_service import ChipService

# Import domain classes
from src.server.domain.market_gateway import MarketGateway
from src.server.domain.quote_cache import QuoteCache
from src.server.domain.symbols import SymbolResolver
from src.server.domain.routing import MarketRouter, ProviderHealthTracker, RoutingPolicy
from src.server.domain.security_master import SecurityMasterRepository


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(packages=["src.server"])

    config = providers.Singleton(get_settings)

    # Connections
    redis = providers.Singleton(
        RedisConnection,
        config=providers.Callable(lambda cfg: cfg.redis.model_dump(), config),
    )
    tushare = providers.Singleton(
        TushareConnection,
        config=providers.Callable(lambda cfg: cfg.tushare.model_dump(), config),
    )
    finnhub = providers.Singleton(
        FinnhubConnection,
        config=providers.Callable(lambda cfg: cfg.finnhub.model_dump(), config),
    )
    baostock = providers.Singleton(
        BaostockConnection,
        config=providers.Callable(lambda cfg: cfg.baostock.model_dump(), config),
    )
    postgres = providers.Singleton(
        PostgresConnection,
        config=providers.Callable(
            lambda cfg: {
                "dsn": cfg.postgres.build_asyncpg_dsn(),
                "host": cfg.postgres.host,
                "port": cfg.postgres.port,
                "user": cfg.postgres.user,
                "password": cfg.postgres.password,
                "database": cfg.postgres.database,
                "pool_min": cfg.postgres.pool_min,
                "pool_max": cfg.postgres.pool_max,
            },
            config,
        ),
    )

    # Cache
    cache = providers.Singleton(AsyncRedisCache, redis_client=redis)

    # Quote cache (real-time price caching with single-flight protection)
    quote_cache = providers.Singleton(QuoteCache, cache=cache)

    # Adapters (each receives cache for result caching)
    yahoo_adapter = providers.Singleton(
        YahooAdapter,
        cache=cache,
        proxy_url=providers.Callable(
            lambda cfg: (
                f"http://{cfg.proxy.host}:{cfg.proxy.port}"
                if cfg.proxy.enabled
                else None
            ),
            config,
        ),
    )
    akshare_adapter = providers.Singleton(AkshareAdapter, cache=cache)
    crypto_adapter = providers.Singleton(CryptoAdapter, cache=cache)
    ccxt_adapter = providers.Singleton(CCXTAdapter, cache=cache)
    tushare_adapter = providers.Singleton(
        TushareAdapter, tushare_conn=tushare, cache=cache
    )
    finnhub_adapter = providers.Singleton(
        FinnhubAdapter, finnhub_conn=finnhub, cache=cache
    )
    baostock_adapter = providers.Singleton(BaostockAdapter, cache=cache)
    futures_adapter = providers.Singleton(
        FuturesAdapter,
        cache=cache,
        proxy_url=providers.Callable(
            lambda cfg: (
                f"http://{cfg.proxy.host}:{cfg.proxy.port}"
                if cfg.proxy.enabled
                else None
            ),
            config,
        ),
    )
    alpha_vantage_adapter = providers.Singleton(
        AlphaVantageAdapter,
        api_key=providers.Callable(lambda cfg: cfg.api_keys.alpha_vantage or "", config),
        cache=cache,
        proxy_url=providers.Callable(
            lambda cfg: (
                f"http://{cfg.proxy.host}:{cfg.proxy.port}"
                if cfg.proxy.enabled
                else None
            ),
            config,
        ),
    )
    twelve_data_adapter = providers.Singleton(
        TwelveDataAdapter,
        api_key=providers.Callable(lambda cfg: cfg.api_keys.twelve_data or "", config),
        cache=cache,
        proxy_url=providers.Callable(
            lambda cfg: (
                f"http://{cfg.proxy.host}:{cfg.proxy.port}"
                if cfg.proxy.enabled
                else None
            ),
            config,
        ),
    )
    fred_adapter = providers.Singleton(
        FredAdapter,
        api_key=providers.Callable(lambda cfg: cfg.api_keys.fred or "", config),
        cache=cache,
        proxy_url=providers.Callable(
            lambda cfg: (
                f"http://{cfg.proxy.host}:{cfg.proxy.port}"
                if cfg.proxy.enabled
                else None
            ),
            config,
        ),
    )
    edgar_adapter = providers.Singleton(EdgarAdapter, cache=cache)

    # Security Master
    security_master_repo = providers.Singleton(
        SecurityMasterRepository,
        postgres_conn=postgres,
        backend_mode=providers.Callable(lambda cfg: cfg.security_master_backend, config),
        sqlite_path=providers.Callable(lambda cfg: cfg.security_master_sqlite_path, config),
    )

    # MarketGateway (unified gateway)
    # NOTE: SymbolResolver receives gateway as "adapter_manager" for backward compatibility
    # during initialization,    # SymbolResolver is created first, then MarketGateway is created with resolver injected.
    # After MarketGateway is created, # SymbolResolver needs gateway for adapter methods
    symbol_resolver = providers.Singleton(
        SymbolResolver,
        security_master_repo=security_master_repo,
        adapter_manager=None,  # Will be set after gateway is created
    )

    # Routing components
    routing_policy = providers.Singleton(RoutingPolicy.load)
    provider_health = providers.Singleton(ProviderHealthTracker)

    # MarketGateway - unified gateway
    market_gateway = providers.Singleton(
        MarketGateway,
        symbol_resolver=symbol_resolver,
        market_router=None,  # Will be set after router is created
        provider_timeout_seconds=providers.Callable(
            lambda cfg: cfg.timeout.provider_call_seconds,
            config,
        ),
        quote_cache=quote_cache,
    )

    # MarketRouter (optional advanced routing)
    # Created after MarketGateway to avoid circular dependency
    market_router = providers.Singleton(
        MarketRouter,
        adapter_manager=market_gateway,
        security_master_repo=security_master_repo,
        routing_policy=routing_policy,
        health_tracker=provider_health,
        provider_timeout_seconds=providers.Callable(
            lambda cfg: cfg.timeout.provider_call_seconds,
            config,
        ),
    )

    # Update SymbolResolver's adapter_manager reference to point to gateway
    # (done after MarketGateway is created)
    # MinIO Client
    from src.server.infrastructure.minio_client import MinioClient
    minio_client = providers.Singleton(MinioClient)

    # Services (receive gateway, backward-compatible param name "adapter_manager")
    fundamental_service = providers.Factory(
        FundamentalService,
        adapter_manager=market_gateway,
        cache=cache,
    )
    news_service = providers.Factory(
        NewsService,
        adapter_manager=market_gateway,
        cache=cache,
        api_keys=providers.Callable(lambda cfg: cfg.api_keys.model_dump(), config),
    )
    technical_service = providers.Factory(
        TechnicalService,
        adapter_manager=market_gateway,
    )
    filings_service = providers.Factory(
        FilingsService,
        adapter_manager=market_gateway,
        minio_client=minio_client,
    )
    money_flow_service = providers.Factory(
        MoneyFlowService,
        adapter_manager=market_gateway,
    )
    chip_service = providers.Factory(
        ChipService,
        adapter_manager=market_gateway,
        cache=cache,
    )
