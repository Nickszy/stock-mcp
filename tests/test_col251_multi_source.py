# tests/test_col251_multi_source.py
"""Tests for COL-251: multi-source cross-validation."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from collections import defaultdict


# ---------------------------------------------------------------------------
# Comparison Engine Tests
# ---------------------------------------------------------------------------

class TestComparisonEngine:
    """Verify the field-level comparison logic."""

    def test_identical_data_high_confidence(self):
        from src.server.domain.structured_data.compare.engine import (
            ComparisonEngine,
        )

        engine = ComparisonEngine()
        result = engine.compare(
            business_key="SSE:600519",
            dataset_key="daily_market_data",
            candidates=[
                {"_source": "akshare", "open": 1700.0, "high": 1720.0, "low": 1690.0, "close": 1710.0, "volume": 2500000},
                {"_source": "tushare", "open": 1700.0, "high": 1720.0, "low": 1690.0, "close": 1710.0, "volume": 2500000},
            ],
        )
        assert result.confidence_score == 1.0
        assert len(result.sources_compared) == 2
        assert not result.has_conflicts
        assert result.field_count > 0

    def test_single_source_moderate_confidence(self):
        from src.server.domain.structured_data.compare.engine import ComparisonEngine

        engine = ComparisonEngine()
        result = engine.compare(
            business_key="SSE:600519",
            dataset_key="daily_market_data",
            candidates=[
                {"_source": "akshare", "open": 1700.0, "high": 1720.0, "close": 1710.0},
            ],
        )
        assert result.confidence_score == 0.7
        assert len(result.sources_compared) == 1
        assert result.field_count > 0  # Single source has all fields as agreed (no comparison needed)

    def test_numeric_within_tolerance(self):
        from src.server.domain.structured_data.compare.engine import ComparisonEngine

        engine = ComparisonEngine()
        result = engine.compare(
            business_key="SSE:600519",
            dataset_key="daily_market_data",
            candidates=[
                {"_source": "akshare", "open": 1700.0, "high": 1720.0, "close": 1710.0, "volume": 2500000},
                {"_source": "tushare", "open": 1701.5, "high": 1721.5, "close": 1711.0, "volume": 2490000},
            ],
        )
        # Within 1% tolerance -> high confidence
        assert result.confidence_score >= 0.9
        assert not result.has_conflicts

        assert "close" in result.agreed_fields

    def test_numeric_outside_tolerance(self):
        from src.server.domain.structured_data.compare.engine import ComparisonEngine

        engine = ComparisonEngine()
        result = engine.compare(
            business_key="SSE:600519",
            dataset_key="daily_market_data",
            candidates=[
                {"_source": "akshare", "open": 1700.0, "high": 1720.0, "close": 1710.0, "volume": 2500000},
                {"_source": "tushare", "open": 1700.0, "high": 1720.5, "close": 1711.0, "volume": 2200000},
            ],
        )
        # Volume differs by ~12% -> conflict
        assert result.has_conflicts
        assert "volume" in result.conflict_fields
        # Most fields agree, so confidence is still relatively high despite 1 conflict

    def test_empty_candidates(self):
        from src.server.domain.structured_data.compare.engine import ComparisonEngine

        engine = ComparisonEngine()
        result = engine.compare(
            business_key="SSE:600519",
            dataset_key="daily_market_data",
            candidates=[],
        )
        assert result.confidence_score == 0.0
        assert result.sources_compared == []


# ---------------------------------------------------------------------------
# Runner Multi-Source Collection Tests
# ---------------------------------------------------------------------------

class TestRunnerMultiSourceCollection:
    """Verify runner collects from ALL sources."""

    @pytest.mark.asyncio
    async def test_collects_all_sources(self):
        """When multiple sources are configured, the runner should collect from all of them."""
        from src.server.domain.structured_data.scheduler.runner import TaskRunner
        from src.server.domain.structured_data.registry import build_default_registry

        registry = build_default_registry()

        # Register a mock fetcher that records calls counts
        call_counts = []

        async def mock_fetcher(dataset_key, source, business_key, **kwargs):
            call_counts.append(source)
            return {"_source": source, "source": source, "data": {"test": True}}

        registry.register_fetcher("daily_market_data", mock_fetcher)

        runner = TaskRunner(
            registry=registry,
            raw_repo=MagicMock(),
            gateway=MagicMock(),
        )

        config = registry.require("daily_market_data")

        results = await runner._fetch_from_sources(
            config=config,
            business_key="SSE:600519",
        )

        # Should have called fetcher for each source
        assert len(call_counts) == len(config.sorted_sources)
        assert len(results) == len(config.sorted_sources)

        # Each result should be tagged with source
        for result in results:
            assert "_source" in result

            assert result["_source"] in [s.source_name for s in config.sorted_sources]

    @pytest.mark.asyncio
    async def test_stops_on_source_override(self):
        """When source_override is set, only that source should be fetched."""
        from src.server.domain.structured_data.scheduler.runner import TaskRunner
        from src.server.domain.structured_data.registry import build_default_registry

        registry = build_default_registry()

        call_counts = []

        async def mock_fetcher(dataset_key, source, business_key, **kwargs):
            call_counts.append(source)
            return {"_source": source, "source": source, "data": {"test": True}}

        registry.register_fetcher("daily_market_data", mock_fetcher)

        runner = TaskRunner(
            registry=registry,
            raw_repo=MagicMock(),
            gateway=MagicMock(),
        )

        config = registry.require("daily_market_data")

        results = await runner._fetch_from_sources(
            config=config,
            business_key="SSE:600519",
            source_override="akshare",
        )

        # Only akshare should have been called
        assert call_counts == ["akshare"]
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Orchestrator Multi-Source Tests
# ---------------------------------------------------------------------------

class TestOrchestratorMultiSource:
    """Verify orchestrator uses multi-source comparison."""

    @pytest.mark.asyncio
    async def test_multi_source_boosts_confidence(self):
        """With multi-source agreement, confidence should reach auto-publish level."""
        from src.server.domain.structured_data.compare.engine import ComparisonEngine

        engine = ComparisonEngine()

        # Simulate comparing two identical sources
        result = engine.compare(
            business_key="SSE:600519:2024Q3",
            dataset_key="financial_statements",
            candidates=[
                {
                    "business_key": "SSE:600519:2024Q3",
                    "symbol": "600519",
                    "exchange": "SSE",
                    "_source": "akshare",
                    "revenue": 1000000,
                    "net_income": 500000,
                    "eps": 10.0,
                },
                {
                    "business_key": "SSE:600519:2024Q3",
                    "symbol": "600519",
                    "exchange": "SSE",
                    "_source": "tushare",
                    "revenue": 1000000,
                    "net_income": 500000,
                    "eps": 10.0,
                },
            ],
        )
        assert result.confidence_score == 1.0
        assert not result.has_conflicts
        assert "revenue" in result.agreed_fields
        assert "net_income" in result.agreed_fields
        assert "eps" in result.agreed_fields

    @pytest.mark.asyncio
    async def test_conflict_detected(self):
        """When sources disagree, conflicts should be reported."""
        from src.server.domain.structured_data.compare.engine import ComparisonEngine

        engine = ComparisonEngine()
        result = engine.compare(
            business_key="SSE:600519:2024Q3",
            dataset_key="financial_statements",
            candidates=[
                {
                    "business_key": "SSE:600519:2024Q3",
                    "_source": "akshare",
                    "revenue": 1000000,
                    "net_income": 500000,
                    "eps": 10.0,
                },
                {
                    "business_key": "SSE:600519:2024Q3",
                    "_source": "tushare",
                    "revenue": 1200000,  # 20% off
                    "net_income": 500000,
                    "eps": 10.0,
                },
            ],
        )
        assert result.has_conflicts
        assert "revenue" in result.conflict_fields
        assert result.confidence_score < 1.0
