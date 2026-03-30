# tests/test_structured_data_registry.py
"""Tests for COL-223: Dataset Registry, refresh policies, and task runner."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import sys

sys.path.insert(0, "src")

from server.domain.structured_data.registry import (
    DatasetConfig,
    DatasetRegistry,
    SourceConfig,
    TTLConfig,
    build_default_registry,
    RefreshTrigger,
)
from server.domain.structured_data.scheduler.policies import (
    HardTTLPolicy,
    NoDataPolicy,
    OnDemandPolicy,
    RefreshDecision,
    RefreshPolicyChain,
    SoftTTLPolicy,
)
from server.domain.structured_data.scheduler.runner import TaskRunner


# ============================================================
# DatasetConfig Tests
# ============================================================


class TestSourceConfig:
    def test_defaults(self):
        s = SourceConfig(source_name="akshare")
        assert s.priority == 100
        assert s.enabled is True
        assert s.max_retries == 3

    def test_sorted_sources(self):
        config = DatasetConfig(
            dataset_key="test",
            display_name="Test",
            sources=[
                SourceConfig(source_name="tushare", priority=2),
                SourceConfig(source_name="akshare", priority=1),
                SourceConfig(source_name="baostock", priority=3, enabled=False),
            ],
        )
        sorted_src = config.sorted_sources
        assert len(sorted_src) == 2  # baostock disabled
        assert sorted_src[0].source_name == "akshare"
        assert sorted_src[1].source_name == "tushare"

    def test_primary_source(self):
        config = DatasetConfig(
            dataset_key="test",
            display_name="Test",
            sources=[
                SourceConfig(source_name="tushare", priority=2),
                SourceConfig(source_name="akshare", priority=1),
            ],
        )
        assert config.primary_source.source_name == "akshare"

    def test_primary_source_empty(self):
        config = DatasetConfig(dataset_key="test", display_name="Test")
        assert config.primary_source is None


class TestTTLConfig:
    def test_defaults(self):
        ttl = TTLConfig()
        assert ttl.soft_ttl_hours == 24
        assert ttl.hard_ttl_hours == 168
        assert ttl.market_hours_only is True


# ============================================================
# DatasetRegistry Tests
# ============================================================


class TestDatasetRegistry:
    def test_register_and_get(self):
        registry = DatasetRegistry()
        config = DatasetConfig(dataset_key="test_ds", display_name="Test Dataset")
        registry.register(config)
        assert registry.get("test_ds") is config

    def test_get_nonexistent(self):
        registry = DatasetRegistry()
        assert registry.get("nonexistent") is None

    def test_require_found(self):
        registry = DatasetRegistry()
        config = DatasetConfig(dataset_key="test_ds", display_name="Test")
        registry.register(config)
        assert registry.require("test_ds") is config

    def test_require_not_found(self):
        registry = DatasetRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.require("nonexistent")

    def test_register_many(self):
        registry = DatasetRegistry()
        configs = [
            DatasetConfig(dataset_key="a", display_name="A"),
            DatasetConfig(dataset_key="b", display_name="B"),
        ]
        registry.register_many(configs)
        assert len(registry.dataset_keys) == 2

    def test_list_active(self):
        registry = DatasetRegistry()
        registry.register_many([
            DatasetConfig(dataset_key="active", display_name="Active", is_active=True),
            DatasetConfig(dataset_key="inactive", display_name="Inactive", is_active=False),
        ])
        active = registry.list_active()
        assert len(active) == 1
        assert active[0].dataset_key == "active"

    def test_list_by_tag(self):
        registry = DatasetRegistry()
        registry.register_many([
            DatasetConfig(dataset_key="a", display_name="A", tags=["financial"]),
            DatasetConfig(dataset_key="b", display_name="B", tags=["market"]),
            DatasetConfig(dataset_key="c", display_name="C", tags=["financial", "daily"]),
        ])
        financial = registry.list_by_tag("financial")
        assert len(financial) == 2

    def test_list_scheduled(self):
        registry = DatasetRegistry()
        registry.register_many([
            DatasetConfig(
                dataset_key="scheduled",
                display_name="Scheduled",
                cron_schedule="0 18 * * 1-5",
                refresh_triggers=[RefreshTrigger.SCHEDULED],
            ),
            DatasetConfig(
                dataset_key="on_demand_only",
                display_name="On Demand",
                cron_schedule="",
                refresh_triggers=[RefreshTrigger.ON_DEMAND],
            ),
        ])
        scheduled = registry.list_scheduled()
        assert len(scheduled) == 1
        assert scheduled[0].dataset_key == "scheduled"

    def test_component_registration(self):
        registry = DatasetRegistry()
        registry.register(DatasetConfig(dataset_key="test", display_name="Test"))
        normalizer = MagicMock()
        validator = MagicMock()
        fetcher = AsyncMock()

        registry.register_normalizer("test", normalizer)
        registry.register_validator("test", validator)
        registry.register_fetcher("test", fetcher)

        assert registry.get_normalizer("test") is normalizer
        assert registry.get_validator("test") is validator
        assert registry.get_fetcher("test") is fetcher

    def test_has_dataset(self):
        registry = DatasetRegistry()
        registry.register(DatasetConfig(dataset_key="test", display_name="Test"))
        assert registry.has_dataset("test") is True
        assert registry.has_dataset("nope") is False

    def test_dataset_keys(self):
        registry = DatasetRegistry()
        registry.register_many([
            DatasetConfig(dataset_key="a", display_name="A"),
            DatasetConfig(dataset_key="b", display_name="B"),
        ])
        assert registry.dataset_keys == {"a", "b"}


class TestDefaultRegistry:
    def test_default_has_7_datasets(self):
        registry = build_default_registry()
        assert len(registry.dataset_keys) == 7

    def test_default_keys(self):
        registry = build_default_registry()
        expected = {
            "financial_statements",
            "company_profile",
            "dividend",
            "shareholder",
            "corporate_actions",
            "index_constituents",
            "daily_market_data",
        }
        assert registry.dataset_keys == expected

    def test_financial_statements_config(self):
        registry = build_default_registry()
        fs = registry.get("financial_statements")
        assert fs is not None
        assert fs.display_name != ""
        assert len(fs.sources) == 2
        assert fs.sources[0].source_name == "akshare"
        assert fs.sources[0].priority == 1
        assert fs.auto_publish_threshold == 0.85
        assert "financial" in fs.tags
        assert len(fs.validation_rules) > 0

    def test_all_configs_have_sources(self):
        registry = build_default_registry()
        for config in registry.list_all():
            assert len(config.sources) > 0, f"{config.dataset_key} has no sources"


# ============================================================
# Refresh Policy Tests
# ============================================================


class TestHardTTLPolicy:
    @pytest.mark.asyncio
    async def test_no_previous_data(self):
        policy = HardTTLPolicy()
        config = DatasetConfig(dataset_key="test", display_name="Test")
        d = await policy.evaluate(config)
        assert d.should_refresh is True
        assert d.priority == "urgent"

    @pytest.mark.asyncio
    async def test_within_hard_ttl(self):
        policy = HardTTLPolicy()
        config = DatasetConfig(
            dataset_key="test",
            display_name="Test",
            ttl=TTLConfig(hard_ttl_hours=168),
        )
        recent = datetime.now(timezone.utc) - timedelta(hours=10)
        d = await policy.evaluate(config, last_published_at=recent)
        assert d.should_refresh is False

    @pytest.mark.asyncio
    async def test_past_hard_ttl(self):
        policy = HardTTLPolicy()
        config = DatasetConfig(
            dataset_key="test",
            display_name="Test",
            ttl=TTLConfig(hard_ttl_hours=168),
        )
        old = datetime.now(timezone.utc) - timedelta(hours=200)
        d = await policy.evaluate(config, last_published_at=old)
        assert d.should_refresh is True
        assert d.priority == "urgent"


class TestSoftTTLPolicy:
    @pytest.mark.asyncio
    async def test_past_soft_ttl(self):
        policy = SoftTTLPolicy()
        config = DatasetConfig(
            dataset_key="test",
            display_name="Test",
            ttl=TTLConfig(soft_ttl_hours=24),
        )
        old = datetime.now(timezone.utc) - timedelta(hours=30)
        d = await policy.evaluate(config, last_published_at=old)
        assert d.should_refresh is True
        assert d.priority == "normal"

    @pytest.mark.asyncio
    async def test_within_soft_ttl(self):
        policy = SoftTTLPolicy()
        config = DatasetConfig(
            dataset_key="test",
            display_name="Test",
            ttl=TTLConfig(soft_ttl_hours=24),
        )
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        d = await policy.evaluate(config, last_published_at=recent)
        assert d.should_refresh is False


class TestOnDemandPolicy:
    @pytest.mark.asyncio
    async def test_force(self):
        policy = OnDemandPolicy()
        config = DatasetConfig(dataset_key="test", display_name="Test")
        d = await policy.evaluate(config, force=True)
        assert d.should_refresh is True
        assert d.priority == "urgent"

    @pytest.mark.asyncio
    async def test_not_forced(self):
        policy = OnDemandPolicy()
        config = DatasetConfig(dataset_key="test", display_name="Test")
        d = await policy.evaluate(config, force=False)
        assert d.should_refresh is False


class TestNoDataPolicy:
    @pytest.mark.asyncio
    async def test_no_data(self):
        policy = NoDataPolicy()
        config = DatasetConfig(dataset_key="test", display_name="Test")
        d = await policy.evaluate(config, has_data=False)
        assert d.should_refresh is True
        assert d.priority == "urgent"

    @pytest.mark.asyncio
    async def test_has_data(self):
        policy = NoDataPolicy()
        config = DatasetConfig(dataset_key="test", display_name="Test")
        d = await policy.evaluate(config, has_data=True)
        assert d.should_refresh is False


class TestRefreshPolicyChain:
    @pytest.mark.asyncio
    async def test_chain_force_wins(self):
        chain = RefreshPolicyChain()
        config = DatasetConfig(dataset_key="test", display_name="Test")
        d = await chain.should_refresh(config, force=True)
        assert d.should_refresh is True
        assert d.reason == "force_refresh"

    @pytest.mark.asyncio
    async def test_chain_no_data(self):
        chain = RefreshPolicyChain()
        config = DatasetConfig(dataset_key="test", display_name="Test")
        d = await chain.should_refresh(config, has_data=False)
        assert d.should_refresh is True
        assert d.reason == "no_existing_data"

    @pytest.mark.asyncio
    async def test_chain_fresh_data_skips(self):
        chain = RefreshPolicyChain()
        config = DatasetConfig(
            dataset_key="test",
            display_name="Test",
            ttl=TTLConfig(soft_ttl_hours=24, hard_ttl_hours=168),
        )
        recent = datetime.now(timezone.utc) - timedelta(hours=1)
        d = await chain.should_refresh(
            config, has_data=True, last_published_at=recent, force=False,
        )
        assert d.should_refresh is False

    @pytest.mark.asyncio
    async def test_chain_soft_ttl_triggers(self):
        chain = RefreshPolicyChain()
        config = DatasetConfig(
            dataset_key="test",
            display_name="Test",
            ttl=TTLConfig(soft_ttl_hours=24, hard_ttl_hours=168),
        )
        old = datetime.now(timezone.utc) - timedelta(hours=30)
        d = await chain.should_refresh(
            config, has_data=True, last_published_at=old, force=False,
        )
        assert d.should_refresh is True
        assert "soft_ttl" in d.reason


# ============================================================
# TaskRunner Tests (with mocks)
# ============================================================


class TestTaskRunner:
    def _make_runner(self, registry=None):
        registry = registry or DatasetRegistry()
        registry.register(DatasetConfig(
            dataset_key="test_ds",
            display_name="Test",
            sources=[SourceConfig(source_name="akshare", priority=1)],
            ttl=TTLConfig(soft_ttl_hours=24, hard_ttl_hours=168),
        ))
        raw_repo = MagicMock()
        raw_repo.create_job = AsyncMock(return_value="job_123")
        raw_repo.start_job = AsyncMock()
        raw_repo.complete_job = AsyncMock()
        raw_repo.insert_snapshot = AsyncMock(return_value="snap_1")
        return TaskRunner(
            registry=registry,
            raw_repo=raw_repo,
        )

    @pytest.mark.asyncio
    async def test_refresh_skips_when_fresh(self):
        runner = self._make_runner()
        # No force, fresh data
        result = await runner.refresh_on_demand(
            dataset_key="test_ds",
            force=False,
            has_data=True,
            last_published_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_refresh_forced(self):
        runner = self._make_runner()
        fetcher = AsyncMock(return_value=[{"business_key": "TEST:001", "data": {"price": 100}}])
        runner._registry.register_fetcher("test_ds", fetcher)

        result = await runner.refresh_on_demand(
            dataset_key="test_ds",
            force=True,
        )
        assert result["status"] in ("completed", "partial")
        assert result["job_id"] == "job_123"
        assert result["success_count"] >= 1

    @pytest.mark.asyncio
    async def test_refresh_unknown_dataset(self):
        runner = self._make_runner()
        with pytest.raises(KeyError):
            await runner.refresh_on_demand(dataset_key="nonexistent")

    @pytest.mark.asyncio
    async def test_scheduled_refresh(self):
        registry = DatasetRegistry()
        registry.register(DatasetConfig(
            dataset_key="test_ds",
            display_name="Test",
            sources=[SourceConfig(source_name="akshare", priority=1)],
            cron_schedule="0 18 * * 1-5",
            refresh_triggers=[RefreshTrigger.SCHEDULED],
        ))
        raw_repo = MagicMock()
        raw_repo.create_job = AsyncMock(return_value="job_456")
        raw_repo.start_job = AsyncMock()
        raw_repo.complete_job = AsyncMock()

        runner = TaskRunner(registry=registry, raw_repo=raw_repo)
        fetcher = AsyncMock(return_value=[])
        registry.register_fetcher("test_ds", fetcher)

        result = await runner.refresh_scheduled("test_ds")
        assert result["status"] in ("completed", "partial")
