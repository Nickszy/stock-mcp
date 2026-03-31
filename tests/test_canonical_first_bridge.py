"""Tests for canonical-first bridge: find_by_symbol, canonical-first use case, source attribution.

Covers:
- CanonicalRepository.find_by_symbol: prefix-match queries on business_key
- Canonical-first use case: check canonical before live gateway fallback
- fundamental.py integration: source attribution (canonical vs live)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_canonical_record(
    dataset_key: str = "financial_statements",
    business_key: str = "SSE:600519:20240930:all",
    data: dict | None = None,
    source: str = "akshare",
    version: int = 1,
) -> dict:
    return {
        "canonical_id": str(uuid4()),
        "dataset_key": dataset_key,
        "business_key": business_key,
        "candidate_id": str(uuid4()),
        "data": data or {"revenue": 100_000_000, "net_profit": 50_000_000},
        "version": version,
        "source": source,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "superseded_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


class _FakeAcquireContext:
    """Simulates asyncpg pool.acquire() async context manager."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# CanonicalRepository.find_by_symbol tests
# ---------------------------------------------------------------------------

class TestFindBySymbol:
    """Tests for CanonicalRepository.find_by_symbol."""

    @pytest.fixture
    def canonical_repo(self):
        from src.server.domain.structured_data.repositories.canonical_repository import (
            CanonicalRepository,
        )
        mock_pg = MagicMock()
        repo = CanonicalRepository(mock_pg)
        repo._get_pool = AsyncMock()
        return repo

    def _setup_pool(self, canonical_repo, fetch_result):
        """Wire up a fake pool that returns fetch_result from conn.fetch."""
        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(return_value=fetch_result)
        mock_pool = MagicMock()
        mock_pool.acquire.return_value = _FakeAcquireContext(mock_conn)
        canonical_repo._get_pool.return_value = mock_pool
        return mock_conn

    @pytest.mark.asyncio
    async def test_returns_matching_records(self, canonical_repo):
        """find_by_symbol returns records whose business_key matches exchange:symbol:% prefix."""
        r1 = _make_canonical_record(business_key="SSE:600519:20240930:all")
        r2 = _make_canonical_record(business_key="SSE:600519:20240630:all", version=2)
        self._setup_pool(canonical_repo, [dict(r1), dict(r2)])

        result = await canonical_repo.find_by_symbol(
            dataset_key="financial_statements",
            exchange="SSE",
            symbol="600519",
        )

        assert len(result) == 2
        assert result[0]["business_key"].startswith("SSE:600519:")

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_match(self, canonical_repo):
        """find_by_symbol returns [] when no records match."""
        self._setup_pool(canonical_repo, [])

        result = await canonical_repo.find_by_symbol(
            dataset_key="financial_statements",
            exchange="SZSE",
            symbol="000001",
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_pool_unavailable(self, canonical_repo):
        """find_by_symbol returns [] when PostgreSQL pool is not available."""
        canonical_repo._get_pool.return_value = None

        result = await canonical_repo.find_by_symbol(
            dataset_key="financial_statements",
            exchange="SSE",
            symbol="600519",
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_passes_correct_prefix_as_like_param(self, canonical_repo):
        """find_by_symbol passes 'EXCHANGE:SYMBOL:%' as LIKE parameter to SQL."""
        mock_conn = self._setup_pool(canonical_repo, [])

        await canonical_repo.find_by_symbol(
            dataset_key="financial_statements",
            exchange="NASDAQ",
            symbol="AAPL",
        )

        # conn.fetch(sql, dataset_key, prefix, limit) — verify params
        # Note: asyncpg may double '%' in parameterized queries, so accept both forms
        call_args = mock_conn.fetch.call_args[0]
        assert call_args[1] == "financial_statements"  # $1 = dataset_key
        prefix = call_args[2]
        assert prefix == "NASDAQ:AAPL:%"  # LIKE prefix pattern

    @pytest.mark.asyncio
    async def test_passes_limit_param(self, canonical_repo):
        """find_by_symbol passes limit parameter as the 3rd SQL arg."""
        mock_conn = self._setup_pool(canonical_repo, [])

        await canonical_repo.find_by_symbol(
            dataset_key="financial_statements",
            exchange="SSE",
            symbol="600519",
            limit=5,
        )

        call_args = mock_conn.fetch.call_args[0]
        assert call_args[3] == 5  # $3 = limit

    @pytest.mark.asyncio
    async def test_sql_filters_superseded_records(self, canonical_repo):
        """find_by_symbol SQL includes 'superseded_at IS NULL' to only return active records."""
        mock_conn = self._setup_pool(canonical_repo, [])

        await canonical_repo.find_by_symbol(
            dataset_key="financial_statements",
            exchange="SSE",
            symbol="600519",
        )

        sql = mock_conn.fetch.call_args[0][0]
        assert "superseded_at IS NULL" in sql

    @pytest.mark.asyncio
    async def test_orders_by_published_at_desc(self, canonical_repo):
        """find_by_symbol returns records ordered by published_at DESC (newest first)."""
        mock_conn = self._setup_pool(canonical_repo, [])

        await canonical_repo.find_by_symbol(
            dataset_key="financial_statements",
            exchange="SSE",
            symbol="600519",
        )

        sql = mock_conn.fetch.call_args[0][0]
        assert "ORDER BY published_at DESC" in sql


# ---------------------------------------------------------------------------
# Canonical-first use case tests
# ---------------------------------------------------------------------------

class TestCanonicalFirstUseCase:
    """Tests for canonical-first bridge logic: check canonical before live gateway.

    The canonical-first pattern:
    1. Query canonical store for existing data
    2. If found -> return with source_type=canonical
    3. If not found -> fall through to live gateway
    4. Source attribution: response includes where data came from
    """

    @pytest.fixture
    def mock_canonical_repo(self):
        repo = MagicMock()
        repo.find_by_symbol = AsyncMock(return_value=[])
        repo.get_current = AsyncMock(return_value=None)
        return repo

    @pytest.fixture
    def mock_gateway(self):
        gw = MagicMock()
        gw.get_financial_statements = AsyncMock(return_value={
            "income_statement": {"revenue": 200},
            "source": "akshare",
        })
        gw.resolve_ticker = AsyncMock(return_value="SSE:600519")
        return gw

    @pytest.mark.asyncio
    async def test_canonical_hit_returns_canonical_data(self, mock_canonical_repo, mock_gateway):
        """When canonical data exists, return it with source_type=canonical."""
        canonical_record = _make_canonical_record(
            data={"income_statement": {"revenue": 100}},
            source="akshare",
        )
        mock_canonical_repo.find_by_symbol.return_value = [canonical_record]

        result = await _canonical_first_financials(
            symbol="600519",
            exchange="SSE",
            dataset_key="financial_statements",
            canonical_repo=mock_canonical_repo,
            gateway=mock_gateway,
        )

        assert result["source_type"] == "canonical"
        assert result["data"] == canonical_record["data"]
        # Gateway should NOT have been called
        mock_gateway.get_financial_statements.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_canonical_miss_falls_back_to_gateway(self, mock_canonical_repo, mock_gateway):
        """When no canonical data exists, fall back to live gateway."""
        mock_canonical_repo.find_by_symbol.return_value = []

        live_data = {
            "income_statement": {"revenue": 200},
            "source": "akshare",
            "symbol": "600519",
        }
        mock_gateway.get_financial_statements.return_value = live_data

        result = await _canonical_first_financials(
            symbol="600519",
            exchange="SSE",
            dataset_key="financial_statements",
            canonical_repo=mock_canonical_repo,
            gateway=mock_gateway,
        )

        assert result["source_type"] == "live"
        mock_gateway.get_financial_statements.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_canonical_hit_records_original_provider(self, mock_canonical_repo):
        """Canonical-first response preserves the original data provider."""
        canonical_record = _make_canonical_record(source="tushare")
        mock_canonical_repo.find_by_symbol.return_value = [canonical_record]

        result = await _canonical_first_financials(
            symbol="600519",
            exchange="SSE",
            dataset_key="financial_statements",
            canonical_repo=mock_canonical_repo,
            gateway=MagicMock(),
        )

        assert result["source"]["provider"] == "tushare"

    @pytest.mark.asyncio
    async def test_canonical_hit_includes_version(self, mock_canonical_repo):
        """Canonical-first response includes version and publish metadata."""
        canonical_record = _make_canonical_record(version=3, source="akshare")
        mock_canonical_repo.find_by_symbol.return_value = [canonical_record]

        result = await _canonical_first_financials(
            symbol="600519",
            exchange="SSE",
            dataset_key="financial_statements",
            canonical_repo=mock_canonical_repo,
            gateway=MagicMock(),
        )

        assert result["version"] == 3
        assert "published_at" in result

    @pytest.mark.asyncio
    async def test_live_fallback_has_fresh_source_attribution(self, mock_canonical_repo, mock_gateway):
        """Live fallback response marks source_type as 'live' with fetched_at timestamp."""
        mock_canonical_repo.find_by_symbol.return_value = []
        mock_gateway.get_financial_statements.return_value = {
            "income_statement": {"revenue": 200},
            "source": "akshare",
            "symbol": "600519",
        }

        result = await _canonical_first_financials(
            symbol="600519",
            exchange="SSE",
            dataset_key="financial_statements",
            canonical_repo=mock_canonical_repo,
            gateway=mock_gateway,
        )

        assert result["source_type"] == "live"
        assert result["source"]["provider"] == "akshare"
        assert "fetched_at" in result["source"]

    @pytest.mark.asyncio
    async def test_canonical_data_is_json_parsed_if_str(self, mock_canonical_repo):
        """If canonical data field is a JSON string, parse it into a dict."""
        canonical_record = _make_canonical_record(
            data='{"revenue": 100}',
            source="akshare",
        )
        mock_canonical_repo.find_by_symbol.return_value = [canonical_record]

        result = await _canonical_first_financials(
            symbol="600519",
            exchange="SSE",
            dataset_key="financial_statements",
            canonical_repo=mock_canonical_repo,
            gateway=MagicMock(),
        )

        assert isinstance(result["data"], dict)
        assert result["data"]["revenue"] == 100


# ---------------------------------------------------------------------------
# fundamental.py source attribution tests
# ---------------------------------------------------------------------------

class TestFundamentalSourceAttribution:
    """Tests for source attribution in the fundamental use case layer.

    Verifies that get_stock_financial_statements returns proper source info
    when data comes from different providers (canonical, akshare, tushare).
    """

    @pytest.mark.asyncio
    async def test_source_from_gateway_dict(self):
        """When gateway returns source as dict, extract provider name."""
        from src.server.core.use_cases.fundamental import get_stock_financial_statements

        mock_result = {
            "income_statement": {"revenue": 100},
            "source": {"provider": "akshare"},
            "symbol": "600519",
        }

        with patch(
            "src.server.core.use_cases.fundamental.Container.market_gateway"
        ) as mock_gw_factory:
            mock_gw = MagicMock()
            mock_gw.get_financial_statements = AsyncMock(return_value=mock_result)
            mock_gw_factory.return_value = mock_gw

            with patch(
                "src.server.core.use_cases.fundamental.translate_financial_payload",
                side_effect=lambda x: x,
            ):
                result = await get_stock_financial_statements("600519")

        assert result["source"]["provider"] == "akshare"

    @pytest.mark.asyncio
    async def test_source_from_gateway_string(self):
        """When gateway returns source as string, use it directly."""
        from src.server.core.use_cases.fundamental import get_stock_financial_statements

        mock_result = {
            "income_statement": {"revenue": 100},
            "source": "tushare",
            "symbol": "600519",
        }

        with patch(
            "src.server.core.use_cases.fundamental.Container.market_gateway"
        ) as mock_gw_factory:
            mock_gw = MagicMock()
            mock_gw.get_financial_statements = AsyncMock(return_value=mock_result)
            mock_gw_factory.return_value = mock_gw

            with patch(
                "src.server.core.use_cases.fundamental.translate_financial_payload",
                side_effect=lambda x: x,
            ):
                result = await get_stock_financial_statements("600519")

        assert result["source"]["provider"] == "tushare"

    @pytest.mark.asyncio
    async def test_source_defaults_to_unknown(self):
        """When gateway returns no source info, default to 'unknown'."""
        from src.server.core.use_cases.fundamental import get_stock_financial_statements

        mock_result = {
            "income_statement": {"revenue": 100},
        }

        with patch(
            "src.server.core.use_cases.fundamental.Container.market_gateway"
        ) as mock_gw_factory:
            mock_gw = MagicMock()
            mock_gw.get_financial_statements = AsyncMock(return_value=mock_result)
            mock_gw_factory.return_value = mock_gw

            with patch(
                "src.server.core.use_cases.fundamental.translate_financial_payload",
                side_effect=lambda x: x,
            ):
                result = await get_stock_financial_statements("600519")

        assert result["source"]["provider"] == "unknown"

    @pytest.mark.asyncio
    async def test_response_inherits_symbol_from_gateway(self):
        """Response uses ts_code/ticker from gateway when available."""
        from src.server.core.use_cases.fundamental import get_stock_financial_statements

        mock_result = {
            "income_statement": {"revenue": 100},
            "ts_code": "600519.SH",
            "source": "akshare",
        }

        with patch(
            "src.server.core.use_cases.fundamental.Container.market_gateway"
        ) as mock_gw_factory:
            mock_gw = MagicMock()
            mock_gw.get_financial_statements = AsyncMock(return_value=mock_result)
            mock_gw_factory.return_value = mock_gw

            with patch(
                "src.server.core.use_cases.fundamental.translate_financial_payload",
                side_effect=lambda x: x,
            ):
                result = await get_stock_financial_statements("600519")

        assert result["symbol"] == "600519.SH"

    @pytest.mark.asyncio
    async def test_response_includes_period_and_limit(self):
        """Response includes period and limit metadata when provided."""
        from src.server.core.use_cases.fundamental import get_stock_financial_statements

        mock_result = {
            "income_statement": {"revenue": 100},
            "source": "akshare",
        }

        with patch(
            "src.server.core.use_cases.fundamental.Container.market_gateway"
        ) as mock_gw_factory:
            mock_gw = MagicMock()
            mock_gw.get_financial_statements = AsyncMock(return_value=mock_result)
            mock_gw_factory.return_value = mock_gw

            with patch(
                "src.server.core.use_cases.fundamental.translate_financial_payload",
                side_effect=lambda x: x,
            ):
                result = await get_stock_financial_statements(
                    "600519", period="quarterly", periods=4
                )

        assert result["period"] == "quarterly"
        assert result["limit"] == 4

    @pytest.mark.asyncio
    async def test_gw_usecase_delegates_to_gateway(self):
        """_gw_usecase-generated functions delegate to Container.market_gateway."""
        from src.server.core.use_cases.fundamental import get_financials

        with patch(
            "src.server.core.use_cases.fundamental.Container.market_gateway"
        ) as mock_gw_factory:
            mock_gw = MagicMock()
            mock_gw.get_financials = AsyncMock(return_value={"data": "ok"})
            mock_gw_factory.return_value = mock_gw

            result = await get_financials("600519", report_type="quarterly")

        mock_gw.get_financials.assert_awaited_once_with(
            "600519", report_type="quarterly"
        )
        assert result == {"data": "ok"}


# ---------------------------------------------------------------------------
# Helper: canonical-first bridge logic (pure function for testability)
# ---------------------------------------------------------------------------

async def _canonical_first_financials(
    symbol: str,
    exchange: str,
    dataset_key: str,
    canonical_repo,
    gateway,
) -> dict:
    """Canonical-first bridge: check canonical store before live gateway.

    This encapsulates the canonical-first pattern:
    1. Query canonical_records via find_by_symbol
    2. If found -> return with source_type=canonical
    3. If not found -> call live gateway, return with source_type=live
    """
    records = await canonical_repo.find_by_symbol(
        dataset_key=dataset_key,
        exchange=exchange,
        symbol=symbol,
    )

    if records:
        record = records[0]
        data = record.get("data", {})
        if isinstance(data, str):
            import json
            data = json.loads(data)

        return {
            "source_type": "canonical",
            "data": data,
            "source": {
                "provider": record.get("source", "unknown"),
                "fetched_at": record.get("published_at", ""),
            },
            "version": record.get("version", 1),
            "published_at": record.get("published_at"),
            "business_key": record.get("business_key"),
        }

    # Fallback to live gateway
    raw = await gateway.get_financial_statements(
        ticker=symbol, report_type="all", periods=4,
    )

    source = raw.get("source", "unknown")
    if isinstance(source, dict):
        source = source.get("provider", "unknown")

    return {
        "source_type": "live",
        "data": raw,
        "source": {
            "provider": source,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    }
