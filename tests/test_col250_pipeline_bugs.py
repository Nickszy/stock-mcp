"""Tests for COL-250 pipeline bug fixes.

Covers:
1. Orchestrator passes source to normalizer
2. Orchestrator dynamic confidence scoring
3. BALANCE_TUSHARE equity mapping correctness
4. _normalize_latest_row finds actual latest by report_period
5. Fetcher source-specific adapter routing
6. RawRepository.list_snapshots() job_id filter
"""

import inspect
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# ---------------------------------------------------------------------------
# Bug 1: Orchestrator passes source to normalizer
# ---------------------------------------------------------------------------


class TestOrchestratorSourcePassing:
    """Verify orchestrator passes source param to normalizer.normalize()."""

    @pytest.mark.asyncio
    async def test_normalize_receives_source_param(self):
        """normalizer.normalize(raw_data, source=source) is called with source."""
        from src.server.domain.structured_data.orchestrator import Orchestrator
        from src.server.domain.structured_data.registry import (
            DatasetConfig,
            DatasetRegistry,
            SourceConfig,
            TTLConfig,
        )

        config = DatasetConfig(
            dataset_key="test_dataset",
            display_name="Test",
            sources=[SourceConfig(source_name="akshare", priority=1)],
            ttl=TTLConfig(soft_ttl_hours=24, hard_ttl_hours=72),
        )
        registry = DatasetRegistry()
        registry.register(config)

        raw_repo = MagicMock()
        candidate_repo = MagicMock()
        canonical_repo = MagicMock()
        issue_repo = MagicMock()

        candidate_repo.insert_candidate = AsyncMock(return_value=str(uuid4()))
        candidate_repo.transition_state = AsyncMock()
        candidate_repo.insert_issue = AsyncMock()
        candidate_repo.mark_superseded = AsyncMock()
        canonical_repo.get_current = AsyncMock(return_value=None)
        canonical_repo.publish = AsyncMock()
        issue_repo.create_task = AsyncMock()

        orchestrator = Orchestrator(
            registry=registry,
            raw_repo=raw_repo,
            candidate_repo=candidate_repo,
            canonical_repo=canonical_repo,
            issue_repo=issue_repo,
        )

        captured_source = {}
        mock_normalizer = MagicMock()

        async def fake_normalize(raw_data, source="", **kwargs):
            captured_source["source"] = source
            return {"business_key": "SSE:600519:20240930:all", "revenue": 100.0}

        mock_normalizer.normalize = fake_normalize

        snapshot = {
            "snapshot_id": str(uuid4()),
            "job_id": str(uuid4()),
            "source": "tushare",
            "raw_data": {"some": "data"},
            "business_key": "SSE:600519",
        }

        await orchestrator._process_snapshot(
            snapshot=snapshot,
            config=config,
            normalizer=mock_normalizer,
        )

        assert captured_source.get("source") == "tushare", (
            f"Expected source='tushare', got source='{captured_source.get('source')}'"
        )


# ---------------------------------------------------------------------------
# Bug 2: Dynamic confidence scoring
# ---------------------------------------------------------------------------


class TestDynamicConfidence:
    """Verify orchestrator calculates confidence dynamically."""

    @pytest.mark.asyncio
    async def test_sparse_data_goes_to_pending_review(self):
        from src.server.domain.structured_data.orchestrator import Orchestrator
        from src.server.domain.structured_data.registry import (
            DatasetConfig,
            DatasetRegistry,
            SourceConfig,
            TTLConfig,
        )

        config = DatasetConfig(
            dataset_key="test",
            display_name="Test",
            sources=[SourceConfig(source_name="akshare", priority=1)],
            ttl=TTLConfig(soft_ttl_hours=24, hard_ttl_hours=72),
            auto_publish_threshold=0.85,
        )
        registry = DatasetRegistry()
        registry.register(config)

        raw_repo = MagicMock()
        candidate_repo = MagicMock()
        canonical_repo = MagicMock()
        issue_repo = MagicMock()

        candidate_repo.insert_candidate = AsyncMock(return_value=str(uuid4()))
        candidate_repo.transition_state = AsyncMock()
        candidate_repo.insert_issue = AsyncMock()
        candidate_repo.mark_superseded = AsyncMock()
        canonical_repo.get_current = AsyncMock(return_value=None)
        canonical_repo.publish = AsyncMock()
        issue_repo.create_task = AsyncMock()

        orchestrator = Orchestrator(
            registry=registry,
            raw_repo=raw_repo,
            candidate_repo=candidate_repo,
            canonical_repo=canonical_repo,
            issue_repo=issue_repo,
        )

        mock_normalizer = MagicMock()

        async def sparse_normalize(raw_data, source="", **kwargs):
            # Only 1 of 2 non-meta fields has data → low completeness
            return {"business_key": "SSE:600519", "revenue": 100.0, "cost": None}

        mock_normalizer.normalize = sparse_normalize

        snapshot = {
            "snapshot_id": str(uuid4()),
            "job_id": str(uuid4()),
            "source": "akshare",
            "raw_data": {},
            "business_key": "SSE:600519",
        }

        result = await orchestrator._process_snapshot(
            snapshot=snapshot,
            config=config,
            normalizer=mock_normalizer,
        )

        # completeness = 1/2 = 0.5, confidence = min(0.95, 0.6+0.5*0.25) = 0.725 < 0.85
        # Verify the candidate was transitioned to PENDING_REVIEW
        from src.server.domain.structured_data.enums import PipelineState
        transitions = candidate_repo.transition_state.call_args_list
        transition_states = [str(t) for t in transitions]
        assert any(PipelineState.PENDING_REVIEW.value in t for t in transition_states), (
            "Expected PENDING_REVIEW state for sparse data (confidence < 0.85)"
        )

    @pytest.mark.asyncio
    async def test_validation_errors_degrade_confidence(self):
        """ERROR-level validation issues should degrade confidence below 0.5."""
        from src.server.domain.structured_data.orchestrator import Orchestrator
        from src.server.domain.structured_data.registry import (
            DatasetConfig,
            DatasetRegistry,
            SourceConfig,
            TTLConfig,
        )

        config = DatasetConfig(
            dataset_key="test",
            display_name="Test",
            sources=[SourceConfig(source_name="akshare", priority=1)],
            ttl=TTLConfig(soft_ttl_hours=24, hard_ttl_hours=72),
        )
        registry = DatasetRegistry()
        registry.register(config)

        candidate_repo = MagicMock()
        candidate_repo.insert_candidate = AsyncMock(return_value=str(uuid4()))
        candidate_repo.transition_state = AsyncMock()
        candidate_repo.insert_issue = AsyncMock()
        canonical_repo = MagicMock()
        canonical_repo.get_current = AsyncMock(return_value=None)
        issue_repo = MagicMock()
        issue_repo.create_task = AsyncMock()

        orchestrator = Orchestrator(
            registry=registry,
            raw_repo=MagicMock(),
            candidate_repo=candidate_repo,
            canonical_repo=canonical_repo,
            issue_repo=issue_repo,
        )

        mock_normalizer = MagicMock()

        async def normalize_ok(raw_data, source="", **kwargs):
            return {"business_key": "TEST", "revenue": 100.0}

        mock_normalizer.normalize = normalize_ok

        mock_validator = MagicMock()

        async def validate_errors(data, cfg):
            return [{"rule_name": "test", "severity": "ERROR", "message": "bad"}]

        mock_validator.validate = validate_errors

        snapshot = {
            "snapshot_id": str(uuid4()),
            "job_id": str(uuid4()),
            "source": "akshare",
            "raw_data": {},
            "business_key": "TEST",
        }

        result = await orchestrator._process_snapshot(
            snapshot=snapshot,
            config=config,
            normalizer=mock_normalizer,
            validator=mock_validator,
        )

        # Verify ERROR-level validation routed to PENDING_REVIEW via transition_state
        from src.server.domain.structured_data.enums import PipelineState
        transitions = candidate_repo.transition_state.call_args_list
        transition_states = [str(t) for t in transitions]
        assert any(PipelineState.PENDING_REVIEW.value in t for t in transition_states), (
            "Expected PENDING_REVIEW for validation errors"
        )
        # Verify confidence was degraded (not hardcoded 0.3)
        transition_calls = candidate_repo.transition_state.call_args_list
        for call in transition_calls:
            kw = call.kwargs
            if "confidence_score" in kw:
                assert kw["confidence_score"] <= 0.5


# ---------------------------------------------------------------------------
# Bug 3: BALANCE_TUSHARE equity mapping
# ---------------------------------------------------------------------------


class TestTushareEquityMapping:
    """Verify BALANCE_TUSHARE field mappings are semantically correct."""

    def test_total_equity_maps_to_exc_minority(self):
        """total_equity → total_hldr_eqy_exc_min_int (不含少数股东 = 归属母公司).

        In Chinese accounting convention, "total_equity" typically refers to
        parent-only equity (excluding minority interest).
        """
        from src.server.domain.structured_data.normalize.financial_statements import BALANCE_TUSHARE

        assert BALANCE_TUSHARE["total_equity"] == "total_hldr_eqy_exc_min_int", (
            "total_equity should map to total_hldr_eqy_exc_min_int (excluding minority)"
        )

    def test_total_equity_inc_minority_exists(self):
        """total_equity_inc_minority → total_hldr_eqy_inc_min_int (含少数股东)."""
        from src.server.domain.structured_data.normalize.financial_statements import BALANCE_TUSHARE

        assert "total_equity_inc_minority" in BALANCE_TUSHARE, (
            "total_equity_inc_minority field should exist in BALANCE_TUSHARE"
        )
        assert BALANCE_TUSHARE["total_equity_inc_minority"] == "total_hldr_eqy_inc_min_int", (
            "total_equity_inc_minority should map to total_hldr_eqy_inc_min_int (including minority)"
        )


# ---------------------------------------------------------------------------
# Bug 4: _normalize_latest_row finds actual latest by report_period
# ---------------------------------------------------------------------------


class TestNormalizeLatestRow:
    """Verify _normalize_latest_row picks the latest row by period, not rows[0]."""

    def test_picks_latest_period_not_first_row(self):
        from src.server.domain.structured_data.normalize.financial_statements import (
            FinancialStatementsNormalizer,
            INCOME_CANONICAL,
            INCOME_TUSHARE,
        )

        normalizer = FinancialStatementsNormalizer()
        # Rows NOT sorted by date — oldest first
        rows = [
            {"revenue": 100, "end_date": "2023-12-31"},
            {"revenue": 200, "end_date": "2024-06-30"},
            {"revenue": 300, "end_date": "2024-09-30"},  # Latest
            {"revenue": 150, "end_date": "2024-03-31"},
        ]

        result = normalizer._normalize_latest_row(
            rows, "tushare", INCOME_CANONICAL, INCOME_TUSHARE,
        )

        assert result.get("revenue") == 300.0, (
            f"Expected revenue=300.0 from latest period, got {result.get('revenue')}"
        )

    def test_handles_single_row(self):
        from src.server.domain.structured_data.normalize.financial_statements import (
            FinancialStatementsNormalizer,
            INCOME_CANONICAL,
            INCOME_TUSHARE,
        )

        normalizer = FinancialStatementsNormalizer()
        rows = [{"revenue": 500, "end_date": "2024-09-30"}]
        result = normalizer._normalize_latest_row(
            rows, "tushare", INCOME_CANONICAL, INCOME_TUSHARE,
        )
        assert result.get("revenue") == 500.0

    def test_handles_empty_rows(self):
        from src.server.domain.structured_data.normalize.financial_statements import (
            FinancialStatementsNormalizer,
            INCOME_CANONICAL,
            INCOME_TUSHARE,
        )

        normalizer = FinancialStatementsNormalizer()
        result = normalizer._normalize_latest_row(
            [], "tushare", INCOME_CANONICAL, INCOME_TUSHARE,
        )
        assert result == {}


# ---------------------------------------------------------------------------
# Bug 5: Fetcher source-specific adapter routing
# ---------------------------------------------------------------------------


class TestFetcherSourceRouting:
    """Verify financial_statements_fetcher supports source-specific routing."""

    @pytest.mark.asyncio
    async def test_fetcher_calls_source_adapter_when_specified(self):
        """When source='tushare', fetcher should try the tushare adapter directly."""
        from src.server.core.use_cases.structured_data import (
            financial_statements_fetcher,
            _fetch_from_adapter,
        )

        mock_gateway = MagicMock()
        mock_adapter = MagicMock()

        tushare_data = {
            "income_statement": [{"revenue": 100, "end_date": "2024-09-30"}],
        }
        mock_adapter.get_financial_statements = AsyncMock(return_value=tushare_data)
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=mock_adapter)

        result = await _fetch_from_adapter(mock_gateway, "tushare", "600519")

        mock_gateway.get_adapter_by_provider.assert_called_once_with("tushare")
        mock_adapter.get_financial_statements.assert_awaited_once()
        assert result == tushare_data

    @pytest.mark.asyncio
    async def test_fetcher_adapter_not_found_returns_none(self):
        """When adapter not found, _fetch_from_adapter returns None."""
        from src.server.core.use_cases.structured_data import _fetch_from_adapter

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=None)

        result = await _fetch_from_adapter(mock_gateway, "unknown_source", "600519")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetcher_adapter_error_returns_none(self):
        """When adapter raises, _fetch_from_adapter catches and returns None."""
        from src.server.core.use_cases.structured_data import _fetch_from_adapter

        mock_gateway = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.get_financial_statements = AsyncMock(side_effect=Exception("timeout"))
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=mock_adapter)

        result = await _fetch_from_adapter(mock_gateway, "tushare", "600519")
        assert result is None


# ---------------------------------------------------------------------------
# Bug 6: RawRepository.list_snapshots() job_id filter
# ---------------------------------------------------------------------------


class TestRawRepositoryJobIdFilter:
    """Verify list_snapshots supports job_id parameter."""

    def test_list_snapshots_accepts_job_id_param(self):
        """list_snapshots signature includes job_id parameter."""
        from src.server.domain.structured_data.repositories.raw_repository import RawRepository

        sig = inspect.signature(RawRepository.list_snapshots)
        assert "job_id" in sig.parameters, "list_snapshots must accept job_id parameter"

    @pytest.mark.asyncio
    async def test_list_snapshots_includes_job_id_in_query(self):
        """When job_id is provided, it should be included in the SQL WHERE clause."""
        from src.server.domain.structured_data.repositories.raw_repository import RawRepository

        mock_pg = MagicMock()
        mock_conn = AsyncMock()

        captured_sql = {}

        async def fake_fetch(sql, *args):
            captured_sql["sql"] = sql
            captured_sql["args"] = args
            return []

        mock_conn.fetch = fake_fetch
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        mock_pg.get_client = MagicMock(return_value=mock_pool)
        mock_pg.connected = True

        repo = RawRepository(mock_pg)
        await repo.list_snapshots(
            dataset_key="financial_statements",
            job_id="test-job-id",
            limit=50,
        )

        sql = captured_sql.get("sql", "")
        assert "job_id" in sql, f"SQL should filter by job_id, got: {sql}"
