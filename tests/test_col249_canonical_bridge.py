"""Tests for COL-249 canonical-first data bridge."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestExtractReportPeriod:
    def test_standard_format(self):
        from src.server.domain.structured_data.canonical_reader import _extract_report_period
        assert _extract_report_period('SSE:600519:20240930:all') == '20240930'

    def test_no_period(self):
        from src.server.domain.structured_data.canonical_reader import _extract_report_period
        assert _extract_report_period('SSE:600519') == ''

    def test_empty(self):
        from src.server.domain.structured_data.canonical_reader import _extract_report_period
        assert _extract_report_period('') == ''


class TestBuildBusinessKey:
    def test_with_period(self):
        from src.server.domain.structured_data.canonical_reader import build_business_key
        assert build_business_key('SSE', '600519', '20240930') == 'SSE:600519:20240930:all'

    def test_without_period(self):
        from src.server.domain.structured_data.canonical_reader import build_business_key
        assert build_business_key('SSE', '600519', '') == 'SSE:600519'


class TestReadCanonicalFinancialStatements:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_records(self):
        from src.server.domain.structured_data.canonical_reader import read_canonical_financial_statements
        mock_repo = MagicMock()
        mock_repo.find_by_symbol = AsyncMock(return_value=[])
        with patch('src.server.domain.structured_data.canonical_reader._get_canonical_repo', return_value=mock_repo):
            result = await read_canonical_financial_statements('financial_statements', '600519', 'SSE')
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_structured_data(self):
        from src.server.domain.structured_data.canonical_reader import read_canonical_financial_statements
        mock_repo = MagicMock()
        mock_repo.find_by_symbol = AsyncMock(return_value=[
            {
                'business_key': 'SSE:600519:20240930:all',
                'data': {'revenue': 100.0},
                'version': 1,
                'source': 'tushare',
                'published_at': '2024-10-01T00:00:00',
            },
            {
                'business_key': 'SSE:600519:20240630:all',
                'data': {'revenue': 80.0},
                'version': 1,
                'source': 'tushare',
                'published_at': '2024-07-01T00:00:00',
            },
        ])
        with patch('src.server.domain.structured_data.canonical_reader._get_canonical_repo', return_value=mock_repo):
            result = await read_canonical_financial_statements('financial_statements', '600519', 'SSE')
            assert result is not None
            assert len(result) == 2
            assert result[0]['report_period'] == '20240930'
            assert result[0]['source_type'] == 'canonical'
            assert result[0]['provider'] == 'tushare'

    @pytest.mark.asyncio
    async def test_handles_json_string_data(self):
        import json
        from src.server.domain.structured_data.canonical_reader import read_canonical_financial_statements
        mock_repo = MagicMock()
        mock_repo.find_by_symbol = AsyncMock(return_value=[
            {
                'business_key': 'SSE:600519:20240930:all',
                'data': json.dumps({'revenue': 50.0}),
                'version': 2,
                'source': 'akshare',
                'published_at': '2024-10-01T00:00:00',
            },
        ])
        with patch('src.server.domain.structured_data.canonical_reader._get_canonical_repo', return_value=mock_repo):
            result = await read_canonical_financial_statements('financial_statements', '600519', 'SSE')
            assert result is not None
            assert result[0]['data']['revenue'] == 50.0

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self):
        from src.server.domain.structured_data.canonical_reader import read_canonical_financial_statements
        mock_repo = MagicMock()
        mock_repo.find_by_symbol = AsyncMock(side_effect=Exception('DB error'))
        with patch('src.server.domain.structured_data.canonical_reader._get_canonical_repo', return_value=mock_repo):
            result = await read_canonical_financial_statements('financial_statements', '600519', 'SSE')
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_repo_none(self):
        from src.server.domain.structured_data.canonical_reader import read_canonical_financial_statements
        with patch('src.server.domain.structured_data.canonical_reader._get_canonical_repo', return_value=None):
            result = await read_canonical_financial_statements('financial_statements', '600519', 'SSE')
            assert result is None


class TestCanonicalRepositoryFindCanonical:
    def test_method_exists(self):
        from src.server.domain.structured_data.repositories.canonical_repository import CanonicalRepository
        import inspect
        sig = inspect.signature(CanonicalRepository.find_by_symbol)
        params = list(sig.parameters.keys())
        assert 'dataset_key' in params
        assert 'exchange' in params
        assert 'symbol' in params
        assert 'limit' in params
