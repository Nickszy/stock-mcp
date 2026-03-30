# tests/test_multi_source_cross_validation.py
"""Tests for multi-source cross-validation (COL-251).

Tests:
1. ComparisonEngine — field-level diff and confidence
2. MultiSourceComparator — grouping, adjustment, best-source selection
3. Orchestrator integration — deferred publish + cross-validation
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from collections import defaultdict


# ---------------------------------------------------------------------------
# ComparisonEngine tests
# ---------------------------------------------------------------------------

from src.server.domain.structured_data.compare.engine import (
    ComparisonEngine,
    ComparisonResult,
    FieldDiff,
    ToleranceConfig,
)


class TestComparisonEngine:
    """Test the core ComparisonEngine field-level comparison."""

    def test_single_source_returns_moderate_confidence(self):
        engine = ComparisonEngine()
        result = engine.compare(
            business_key="SSE:600519:2024Q3",
            dataset_key="financial_statements",
            candidates=[{"source": "akshare", "revenue": 1000000}],
        )
        assert result.confidence_score == 0.7
        assert result.sources_compared == ["akshare"]
        assert not result.has_conflicts

    def test_two_sources_perfect_agreement(self):
        engine = ComparisonEngine()
        result = engine.compare(
            business_key="SSE:600519:2024Q3",
            dataset_key="financial_statements",
            candidates=[
                {"source": "akshare", "revenue": 1000000, "net_income": 500000},
                {"source": "tushare", "revenue": 1000000, "net_income": 500000},
            ],
        )
        assert result.confidence_score >= 0.95
        assert not result.has_conflicts
        assert "revenue" in result.agreed_fields
        assert "net_income" in result.agreed_fields

    def test_two_sources_near_agreement_within_tolerance(self):
        engine = ComparisonEngine(ToleranceConfig(numeric_relative_tol=0.02))
        result = engine.compare(
            business_key="SSE:600519:2024Q3",
            dataset_key="financial_statements",
            candidates=[
                {"source": "akshare", "revenue": 1000000},
                {"source": "tushare", "revenue": 1005000},  # 0.5% diff
            ],
        )
        assert not result.has_conflicts
        assert result.confidence_score >= 0.8

    def test_two_sources_significant_disagreement(self):
        engine = ComparisonEngine(ToleranceConfig(numeric_relative_tol=0.01))
        result = engine.compare(
            business_key="SSE:600519:2024Q3",
            dataset_key="financial_statements",
            candidates=[
                {"source": "akshare", "revenue": 1000000, "net_income": 500000},
                {"source": "tushare", "revenue": 900000, "net_income": 450000},  # 10% diff
            ],
        )
        assert result.has_conflicts
        assert "revenue" in result.conflict_fields
        assert "net_income" in result.conflict_fields
        assert result.confidence_score < 0.7

    def test_three_sources_mixed_agreement(self):
        engine = ComparisonEngine()
        result = engine.compare(
            business_key="SSE:600519:2024Q3",
            dataset_key="financial_statements",
            candidates=[
                {"source": "akshare", "revenue": 1000000, "net_income": 500000, "eps": 5.0},
                {"source": "tushare", "revenue": 1000000, "net_income": 500000, "eps": 5.0},
                {"source": "baostock", "revenue": 1000000, "net_income": 480000, "eps": 5.0},
            ],
        )
        # 2/3 fields agree fully, 1 disagrees
        assert result.conflict_count >= 1
        assert "net_income" in result.conflict_fields
        assert "revenue" in result.agreed_fields

    def test_empty_candidates(self):
        engine = ComparisonEngine()
        result = engine.compare(
            business_key="test",
            dataset_key="test",
            candidates=[],
        )
        assert result.confidence_score == 0.0
        assert result.sources_compared == []

    def test_ignore_metadata_fields(self):
        engine = ComparisonEngine()
        result = engine.compare(
            business_key="test",
            dataset_key="test",
            candidates=[
                {"source": "a", "revenue": 100, "_source": "a", "fetched_at": "2024-01-01"},
                {"source": "b", "revenue": 100, "_source": "b", "fetched_at": "2024-01-02"},
            ],
        )
        # _source and fetched_at should be ignored
        assert "revenue" in result.agreed_fields
        assert "_source" not in result.field_diffs


# ---------------------------------------------------------------------------
# MultiSourceComparator tests
# ---------------------------------------------------------------------------

from src.server.domain.structured_data.compare.multi_source_comparator import (
    MultiSourceComparator,
)


import src.server.domain.structured_data.compare.multi_source_comparator as _msc_mod

_completeness_score = _msc_mod._completeness_score


class TestMultiSourceComparator:
    """Test the higher-level MultiSourceComparator."""

    def test_compare_two_sources(self):
        comp = MultiSourceComparator()
        result = comp.compare_candidates(
            dataset_key="financial_statements",
            business_key="SSE:600519:2024Q3",
            candidates=[
                {"source": "akshare", "revenue": 1000000, "net_income": 500000},
                {"source": "tushare", "revenue": 1000000, "net_income": 500000},
            ],
        )
        assert result.confidence_score >= 0.9
        assert not result.has_conflicts

    def test_confidence_boost_on_agreement(self):
        comp = MultiSourceComparator(confidence_boost=0.15)
        result = comp.compare_candidates(
            dataset_key="test",
            business_key="test",
            candidates=[
                {"source": "a", "revenue": 100},
                {"source": "b", "revenue": 100},
            ],
        )
        adj = comp.confidence_adjustment(result)
        assert adj > 0  # Should get a positive boost

    def test_confidence_penalty_on_conflict(self):
        comp = MultiSourceComparator(confidence_penalty=0.1)
        result = comp.compare_candidates(
            dataset_key="test",
            business_key="test",
            candidates=[
                {"source": "a", "revenue": 100},
                {"source": "b", "revenue": 200},  # 100% diff
            ],
        )
        adj = comp.confidence_adjustment(result)
        assert adj < 0  # Should get a penalty

    def test_confidence_adjustment_none_returns_zero(self):
        comp = MultiSourceComparator()
        assert comp.confidence_adjustment(None) == 0.0

    def test_group_and_compare_single_source_skips(self):
        comp = MultiSourceComparator()
        result = comp.group_and_compare(
            dataset_key="test",
            candidates_by_source={"akshare": {"revenue": 100}},
            business_key="test",
        )
        assert result == {}  # Single source = no comparison

    def test_group_and_compare_two_sources(self):
        comp = MultiSourceComparator()
        result = comp.group_and_compare(
            dataset_key="test",
            candidates_by_source={
                "akshare": {"revenue": 100},
                "tushare": {"revenue": 100},
            },
            business_key="SSE:600519:2024Q3",
        )
        assert "SSE:600519:2024Q3" in result
        assert result["SSE:600519:2024Q3"].confidence_score >= 0.9

    def test_pick_best_source_prefers_completeness(self):
        comp = MultiSourceComparator()
        candidates = [
            {"source": "a", "revenue": 100, "net_income": None},
            {"source": "b", "revenue": 100, "net_income": 50},
        ]
        best = comp.pick_best_source(candidates, None)
        assert best["source"] == "b"

    def test_pick_best_source_empty(self):
        comp = MultiSourceComparator()
        assert comp.pick_best_source([], None) == {}

    def test_pick_best_source_single(self):
        comp = MultiSourceComparator()
        assert comp.pick_best_source([{"source": "a"}], None) == {"source": "a"}


class TestCompletenessScore:
    def test_all_filled(self):
        assert _completeness_score({"a": 1, "b": 2, "c": 3}) == 1.0

    def test_partial(self):
        score = _completeness_score({"a": 1, "b": None, "c": 3})
        assert 0.6 < score < 0.7

    def test_all_none(self):
        assert _completeness_score({"a": None, "b": None}) == 0.0

    def test_empty(self):
        assert _completeness_score({}) == 0.0

    def test_meta_fields_ignored(self):
        assert _completeness_score({"a": 1, "_meta": "x"}) == 1.0


# ---------------------------------------------------------------------------
# Orchestrator integration tests (mocked repos)
# ---------------------------------------------------------------------------

from src.server.domain.structured_data.orchestrator import Orchestrator
from src.server.domain.structured_data.registry import (
    DatasetConfig,
    DatasetRegistry,
    SourceConfig,
    TTLConfig,
)


def _make_config() -> DatasetConfig:
    return DatasetConfig(
        dataset_key="financial_statements",
        display_name="Financial Statements",
        description="test",
        primary_key_template="{exchange}:{symbol}:{report_period}:{statement_type}",
        sources=[
            SourceConfig(source_name="akshare", priority=1),
            SourceConfig(source_name="tushare", priority=2),
        ],
        ttl=TTLConfig(soft_ttl_hours=24, hard_ttl_hours=168),
        auto_publish_threshold=0.85,
    )


def _make_mock_orchestrator():
    registry = MagicMock(spec=DatasetRegistry)
    registry.require.return_value = _make_config()

    raw_repo = AsyncMock()
    candidate_repo = AsyncMock()
    canonical_repo = AsyncMock()
    issue_repo = AsyncMock()

    # Default: no existing canonical
    canonical_repo.get_current.return_value = None
    candidate_repo.insert_candidate.return_value = "cand-001"
    issue_repo.create_task.return_value = "task-001"

    orch = Orchestrator(
        registry=registry,
        raw_repo=raw_repo,
        candidate_repo=candidate_repo,
        canonical_repo=canonical_repo,
        issue_repo=issue_repo,
    )
    return orch, registry, raw_repo, candidate_repo, canonical_repo, issue_repo


class TestOrchestratorMultiSource:
    """Test the orchestrator's multi-source cross-validation pipeline."""

    @pytest.mark.asyncio
    async def test_single_source_goes_through_publish_decision(self):
        orch, registry, raw_repo, cand_repo, canon_repo, issue_repo = _make_mock_orchestrator()

        normalizer = AsyncMock()
        normalizer.normalize.return_value = {
            "revenue": 1000000,
            "net_income": 500000,
            "business_key": "SSE:600519:2024Q3:income",
        }
        validator = AsyncMock()
        validator.validate.return_value = []

        registry.get_normalizer.return_value = normalizer
        registry.get_validator.return_value = validator

        raw_repo.list_snapshots.return_value = [
            {"snapshot_id": "snap-1", "job_id": "job-1", "source": "akshare",
             "raw_data": {"revenue": 1000000}, "business_key": "SSE:600519:2024Q3:income"},
        ]

        result = await orch.process_job("job-1", "financial_statements")

        assert result["status"] == "completed"
        assert result["normalized"] == 1
        assert result["validated"] == 1

    @pytest.mark.asyncio
    async def test_two_sources_cross_validated(self):
        orch, registry, raw_repo, cand_repo, canon_repo, issue_repo = _make_mock_orchestrator()

        normalizer = AsyncMock()
        # Both sources produce the same normalized data
        normalizer.normalize.side_effect = [
            {"revenue": 1000000, "net_income": 500000,
             "business_key": "SSE:600519:2024Q3:income"},
            {"revenue": 1000000, "net_income": 500000,
             "business_key": "SSE:600519:2024Q3:income"},
        ]
        validator = AsyncMock()
        validator.validate.return_value = []

        registry.get_normalizer.return_value = normalizer
        registry.get_validator.return_value = validator

        # Two snapshots from different sources, same business_key
        cand_repo.insert_candidate.side_effect = ["cand-001", "cand-002"]

        raw_repo.list_snapshots.return_value = [
            {"snapshot_id": "snap-1", "job_id": "job-1", "source": "akshare",
             "raw_data": {"revenue": 1000000}, "business_key": "SSE:600519:2024Q3:income"},
            {"snapshot_id": "snap-2", "job_id": "job-1", "source": "tushare",
             "raw_data": {"revenue": 1000000}, "business_key": "SSE:600519:2024Q3:income"},
        ]

        result = await orch.process_job("job-1", "financial_statements")

        assert result["status"] == "completed"
        assert result["cross_validated"] == 1
        assert result["normalized"] == 2

    @pytest.mark.asyncio
    async def test_no_snapshots_returns_no_data(self):
        orch, registry, raw_repo, *_ = _make_mock_orchestrator()

        registry.get_normalizer.return_value = AsyncMock()
        raw_repo.list_snapshots.return_value = []

        result = await orch.process_job("job-1", "financial_statements")

        assert result["status"] == "no_data"
        assert result["processed"] == 0

    @pytest.mark.asyncio
    async def test_validation_errors_routes_to_review(self):
        orch, registry, raw_repo, cand_repo, canon_repo, issue_repo = _make_mock_orchestrator()

        normalizer = AsyncMock()
        normalizer.normalize.return_value = {
            "revenue": 1000000,
            "business_key": "SSE:600519:2024Q3:income",
        }
        validator = AsyncMock()
        validator.validate.return_value = [
            {"rule_name": "missing_field", "severity": "ERROR",
             "field_path": "net_income", "message": "Required field missing"},
        ]

        registry.get_normalizer.return_value = normalizer
        registry.get_validator.return_value = validator

        raw_repo.list_snapshots.return_value = [
            {"snapshot_id": "snap-1", "job_id": "job-1", "source": "akshare",
             "raw_data": {"revenue": 1000000}, "business_key": "SSE:600519:2024Q3:income"},
        ]

        result = await orch.process_job("job-1", "financial_statements")

        # With ERROR severity, should route to review
        assert result["status"] == "completed"
        # The candidate should have been transitioned to PENDING_REVIEW
        transitions = cand_repo.transition_state.call_args_list
        assert any(
            PipelineState.PENDING_REVIEW.value in str(t)
            for t in transitions
        )
