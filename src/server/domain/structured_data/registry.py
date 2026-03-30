# src/server/domain/structured_data/registry.py
"""Dataset Registry — central configuration store for all data dimensions.

Each data dimension (financial_statements, company_profile, etc.) registers
its source priority, TTL rules, validation rules, and approval thresholds here.
New dimensions only need to add a config entry + normalizer + validator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from src.server.utils.logger import logger


# ---------------------------------------------------------------------------
# Configuration data classes
# ---------------------------------------------------------------------------

class RefreshTrigger(str, Enum):
    """How a dataset can be triggered for refresh."""
    ON_DEMAND = "on_demand"           # Triggered by API/MCP request
    SCHEDULED = "scheduled"           # Triggered by cron/scheduler
    EVENT_DRIVEN = "event_driven"     # Triggered by an external event (e.g. new filing)


@dataclass
class SourceConfig:
    """Configuration for a single data source within a dataset."""
    source_name: str                      # e.g. "akshare", "tushare", "baostock"
    priority: int = 100                   # Lower = higher priority
    adapter_method: Optional[str] = None  # Method name on the adapter to call
    enabled: bool = True
    max_retries: int = 3
    retry_delay_seconds: float = 5.0
    timeout_seconds: float = 30.0


@dataclass
class TTLConfig:
    """Time-to-live configuration for cached/published data."""
    soft_ttl_hours: int = 24     # Data is stale but still usable
    hard_ttl_hours: int = 168    # Data must be refreshed (7 days default)
    market_hours_only: bool = True  # Only refresh during market hours for intraday


@dataclass
class DatasetConfig:
    """Complete configuration for a data dimension.

    Adding a new data dimension = creating a DatasetConfig + normalizer + validator.
    No framework code changes needed.
    """
    dataset_key: str                                  # e.g. "financial_statements"
    display_name: str                                 # e.g. "A股财报三表"
    description: str = ""
    primary_key_template: str = ""                    # e.g. "{exchange}:{symbol}:{report_period}:{statement_type}"
    sources: List[SourceConfig] = field(default_factory=list)
    ttl: TTLConfig = field(default_factory=TTLConfig)
    refresh_triggers: List[RefreshTrigger] = field(
        default_factory=lambda: [RefreshTrigger.ON_DEMAND, RefreshTrigger.SCHEDULED]
    )
    # Cron expression for scheduled refresh (empty = no scheduled refresh)
    cron_schedule: str = ""                           # e.g. "0 18 * * 1-5" = weekdays 6pm
    # Validation rules to apply (referenced by name)
    validation_rules: List[str] = field(default_factory=list)
    # Auto-publish threshold: confidence >= this → auto-publish, below → pending_review
    auto_publish_threshold: float = 0.8
    # Whether this dataset requires approval for any publish
    requires_approval: bool = False
    # Whether to keep raw snapshots indefinitely
    archive_raw: bool = True
    # Tags for categorization
    tags: List[str] = field(default_factory=list)
    # Whether this dataset is active
    is_active: bool = True

    @property
    def sorted_sources(self) -> List[SourceConfig]:
        """Sources sorted by priority (lower number = higher priority)."""
        return sorted(
            [s for s in self.sources if s.enabled],
            key=lambda s: s.priority,
        )

    @property
    def primary_source(self) -> Optional[SourceConfig]:
        """The highest-priority enabled source."""
        sources = self.sorted_sources
        return sources[0] if sources else None


# ---------------------------------------------------------------------------
# Dataset Registry
# ---------------------------------------------------------------------------

class DatasetRegistry:
    """Central registry for all data dimensions.

    Usage:
        registry = DatasetRegistry()
        registry.register(financial_statements_config)
        config = registry.get("financial_statements")
        all_configs = registry.list_all()
    """

    def __init__(self):
        self._configs: Dict[str, DatasetConfig] = {}
        self._normalizers: Dict[str, Any] = {}     # dataset_key -> normalizer instance
        self._validators: Dict[str, Any] = {}       # dataset_key -> validator instance
        self._fetchers: Dict[str, Any] = {}          # dataset_key -> fetcher callable

    def register(self, config: DatasetConfig) -> None:
        """Register a dataset configuration."""
        if config.dataset_key in self._configs:
            logger.warning(
                "Dataset already registered, overwriting",
                dataset_key=config.dataset_key,
            )
        self._configs[config.dataset_key] = config
        logger.info(
            "Registered dataset",
            dataset_key=config.dataset_key,
            display_name=config.display_name,
            sources=len(config.sources),
        )

    def register_many(self, configs: List[DatasetConfig]) -> None:
        """Register multiple dataset configurations."""
        for config in configs:
            self.register(config)

    def get(self, dataset_key: str) -> Optional[DatasetConfig]:
        """Get a dataset configuration by key."""
        return self._configs.get(dataset_key)

    def require(self, dataset_key: str) -> DatasetConfig:
        """Get a dataset config or raise KeyError."""
        config = self._configs.get(dataset_key)
        if not config:
            raise KeyError(
                f"Dataset '{dataset_key}' not registered. "
                f"Available: {list(self._configs.keys())}"
            )
        return config

    def list_all(self) -> List[DatasetConfig]:
        """List all registered datasets."""
        return list(self._configs.values())

    def list_active(self) -> List[DatasetConfig]:
        """List only active datasets."""
        return [c for c in self._configs.values() if c.is_active]

    def list_by_tag(self, tag: str) -> List[DatasetConfig]:
        """List datasets that have a specific tag."""
        return [c for c in self._configs.values() if tag in c.tags]

    def list_scheduled(self) -> List[DatasetConfig]:
        """List datasets that have a cron schedule configured."""
        return [
            c for c in self._configs.values()
            if c.is_active and c.cron_schedule
            and RefreshTrigger.SCHEDULED in c.refresh_triggers
        ]

    # ------------------------------------------------------------------
    # Component registration (normalizers, validators, fetchers)
    # ------------------------------------------------------------------

    def register_normalizer(self, dataset_key: str, normalizer: Any) -> None:
        """Register a normalizer instance for a dataset."""
        self._normalizers[dataset_key] = normalizer

    def register_validator(self, dataset_key: str, validator: Any) -> None:
        """Register a validator instance for a dataset."""
        self._validators[dataset_key] = validator

    def register_fetcher(self, dataset_key: str, fetcher: Any) -> None:
        """Register a fetcher callable for a dataset.

        The fetcher should be an async callable that accepts:
            (dataset_key: str, source: str, business_key: str, **kwargs) -> Dict[str, Any]
        """
        self._fetchers[dataset_key] = fetcher

    def get_normalizer(self, dataset_key: str) -> Optional[Any]:
        return self._normalizers.get(dataset_key)

    def get_validator(self, dataset_key: str) -> Optional[Any]:
        return self._validators.get(dataset_key)

    def get_fetcher(self, dataset_key: str) -> Optional[Any]:
        return self._fetchers.get(dataset_key)

    def has_dataset(self, dataset_key: str) -> bool:
        return dataset_key in self._configs

    @property
    def dataset_keys(self) -> Set[str]:
        return set(self._configs.keys())


# ---------------------------------------------------------------------------
# Built-in dataset configurations
# ---------------------------------------------------------------------------

def build_default_registry() -> DatasetRegistry:
    """Build a registry with default configurations for all known dimensions.

    Individual dimensions can be customized after creation via register().
    """
    registry = DatasetRegistry()

    registry.register_many([
        # --- Financial statements ---
        DatasetConfig(
            dataset_key="financial_statements",
            display_name="A股财报三表",
            description="利润表、资产负债表、现金流量表",
            primary_key_template="{exchange}:{symbol}:{report_period}:{statement_type}",
            sources=[
                SourceConfig(source_name="akshare", priority=1),
                SourceConfig(source_name="tushare", priority=2),
            ],
            ttl=TTLConfig(soft_ttl_hours=168, hard_ttl_hours=720),  # Quarterly data
            cron_schedule="0 20 * * 1-5",  # Weekdays 8pm
            validation_rules=[
                "revenue_positive",
                "net_income_reasonable",
                "balance_sheet_balanced",
                "field_type_check",
            ],
            auto_publish_threshold=0.85,
            tags=["financial", "quarterly"],
        ),
        # --- Company profile ---
        DatasetConfig(
            dataset_key="company_profile",
            display_name="公司基础资料",
            description="公司名、行业、法人、注册地、上市日期等",
            primary_key_template="{exchange}:{symbol}",
            sources=[
                SourceConfig(source_name="akshare", priority=1),
                SourceConfig(source_name="tushare", priority=2),
            ],
            ttl=TTLConfig(soft_ttl_hours=720, hard_ttl_hours=4320),  # Monthly
            cron_schedule="0 2 * * 1",  # Weekly Monday 2am
            auto_publish_threshold=0.9,
            tags=["reference", "slow-changing"],
        ),
        # --- Dividend ---
        DatasetConfig(
            dataset_key="dividend",
            display_name="分红送转",
            description="分红方案、除权除息日、派息金额、送转比例",
            primary_key_template="{exchange}:{symbol}:{report_period}:{dividend_type}",
            sources=[
                SourceConfig(source_name="akshare", priority=1),
                SourceConfig(source_name="tushare", priority=2),
            ],
            ttl=TTLConfig(soft_ttl_hours=168, hard_ttl_hours=720),
            cron_schedule="0 19 * * 1-5",
            auto_publish_threshold=0.85,
            tags=["financial", "event"],
        ),
        # --- Shareholder ---
        DatasetConfig(
            dataset_key="shareholder",
            display_name="股东与持股变化",
            description="十大股东、流通股东、股东户数、增减持",
            primary_key_template="{exchange}:{symbol}:{report_period}:{holder_type}",
            sources=[
                SourceConfig(source_name="akshare", priority=1),
                SourceConfig(source_name="tushare", priority=2),
            ],
            ttl=TTLConfig(soft_ttl_hours=168, hard_ttl_hours=720),
            cron_schedule="0 21 * * 1-5",
            auto_publish_threshold=0.8,
            tags=["financial", "quarterly"],
        ),
        # --- Corporate actions ---
        DatasetConfig(
            dataset_key="corporate_actions",
            display_name="公司结构化事件",
            description="回购、解禁、增减持、停复牌等",
            primary_key_template="{exchange}:{symbol}:{event_type}:{event_date}",
            sources=[
                SourceConfig(source_name="akshare", priority=1),
                SourceConfig(source_name="tushare", priority=2),
            ],
            ttl=TTLConfig(soft_ttl_hours=24, hard_ttl_hours=168),
            cron_schedule="30 18 * * 1-5",
            auto_publish_threshold=0.75,
            tags=["event", "daily"],
        ),
        # --- Index constituents ---
        DatasetConfig(
            dataset_key="index_constituents",
            display_name="指数成分与权重",
            description="指数样本、权重、调整时间",
            primary_key_template="{index_code}:{effective_date}",
            sources=[
                SourceConfig(source_name="akshare", priority=1),
            ],
            ttl=TTLConfig(soft_ttl_hours=720, hard_ttl_hours=4320),
            cron_schedule="0 3 * * 1",
            auto_publish_threshold=0.9,
            tags=["reference", "slow-changing"],
        ),
        # --- Daily market data ---
        DatasetConfig(
            dataset_key="daily_market_data",
            display_name="日频市场数据",
            description="日线OHLCV、估值快照、日频资金流",
            primary_key_template="{exchange}:{symbol}:{trade_date}",
            sources=[
                SourceConfig(source_name="akshare", priority=1),
                SourceConfig(source_name="baostock", priority=2),
            ],
            ttl=TTLConfig(soft_ttl_hours=24, hard_ttl_hours=168),
            cron_schedule="0 18 * * 1-5",  # After market close
            auto_publish_threshold=0.9,
            tags=["market", "daily"],
        ),
    ])

    return registry
