# tests/test_col227_company_profile.py
"""Tests for COL-227: company profile structured data dimension."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestCompanyProfileNormalizer:
    """Verify CompanyProfileNormalizer field mapping."""

    @pytest.mark.asyncio
    async def test_akshare_normalization(self):
        from src.server.domain.structured_data.normalize.company_profile import (
            CompanyProfileNormalizer,
        )

        normalizer = CompanyProfileNormalizer()
        raw_data = {
            "ticker": "SSE:600519",
            "name": "贵州茅台",
            "properties": {
                "行业": "白酒",
                "上市时间": "2001-08-27",
                "总股本": 125619.5,
                "流通股": 1000000.0,
            },
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", symbol="600519", exchange="SSE"
        )
        assert result["business_key"] == "SSE:600519"
        assert result["symbol"] == "600519"
        assert result["exchange"] == "SSE"
        assert result["short_name"] == "贵州茅台"
        assert result["industry"] == "白酒"
        assert result["listing_date"] == "2001-08-27"
        assert result["total_shares"] == 125619.5
        assert result["float_shares"] == 1000000.0
        assert result["_source"] == "akshare"

    @pytest.mark.asyncio
    async def test_tushare_normalization(self):
        from src.server.domain.structured_data.normalize.company_profile import (
            CompanyProfileNormalizer,
        )

        normalizer = CompanyProfileNormalizer()
        raw_data = {
            "name": "贵州茅台",
            "fullname": "贵州茅台酒股份有限公司",
            "industry": "白酒",
            "list_date": "20010827",
            "market": "主板",
            "curr_type": "CNY",
        }
        result = await normalizer.normalize(
            raw_data, source="tushare", symbol="600519", exchange="SSE"
        )
        assert result["business_key"] == "SSE:600519"
        assert result["short_name"] == "贵州茅台"
        assert result["full_name"] == "贵州茅台酒股份有限公司"
        assert result["listing_date"] == "2001-08-27"
        assert result["currency"] == "CNY"

    @pytest.mark.asyncio
    async def test_generic_normalization(self):
        from src.server.domain.structured_data.normalize.company_profile import (
            CompanyProfileNormalizer,
        )

        normalizer = CompanyProfileNormalizer()
        raw_data = {
            "short_name": "Test Corp",
            "industry": "Tech",
            "listing_date": "2020-01-15",
        }
        result = await normalizer.normalize(
            raw_data, source="generic", symbol="AAPL", exchange="NASDAQ"
        )
        assert result["business_key"] == "NASDAQ:AAPL"
        assert result["short_name"] == "Test Corp"

    @pytest.mark.asyncio
    async def test_ticker_from_raw_data(self):
        from src.server.domain.structured_data.normalize.company_profile import (
            CompanyProfileNormalizer,
        )

        normalizer = CompanyProfileNormalizer()
        raw_data = {"ticker": "SZSE:000001", "name": "平安银行"}
        result = await normalizer.normalize(raw_data, source="akshare")
        assert result["symbol"] == "000001"
        assert result["exchange"] == "SZSE"
        assert result["business_key"] == "SZSE:000001"


class TestCompanyProfileValidator:
    """Verify company profile validation rules."""

    @pytest.mark.asyncio
    async def test_missing_short_name_triggers_error(self):
        from src.server.domain.structured_data.validate.company_profile import (
            register_company_profile_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_company_profile_rules(engine)

        result = await engine.validate("company_profile", "SSE:600519", {})
        assert result.error_count >= 1
        assert any(i.field_path == "short_name" for i in result.issues)

    @pytest.mark.asyncio
    async def test_valid_data_passes(self):
        from src.server.domain.structured_data.validate.company_profile import (
            register_company_profile_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_company_profile_rules(engine)

        data = {"business_key": "SSE:600519", "short_name": "茅台", "industry": "白酒", "listing_date": "2001-08-27"}
        result = await engine.validate("company_profile", "SSE:600519", data)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_invalid_listing_date(self):
        from src.server.domain.structured_data.validate.company_profile import (
            register_company_profile_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_company_profile_rules(engine)

        data = {"business_key": "SSE:600519", "short_name": "X", "listing_date": "not-a-date"}
        result = await engine.validate("company_profile", "SSE:600519", data)
        assert any(i.rule_name == "listing_date_valid" for i in result.issues)

    @pytest.mark.asyncio
    async def test_float_exceeds_total(self):
        from src.server.domain.structured_data.validate.company_profile import (
            register_company_profile_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_company_profile_rules(engine)

        data = {"business_key": "SSE:600519", "short_name": "X", "total_shares": 1000.0, "float_shares": 5000.0}
        result = await engine.validate("company_profile", "SSE:600519", data)
        assert any(i.rule_name == "float_not_exceed_total" for i in result.issues)


class TestCompanyProfileFetcher:
    """Verify company_profile_fetcher calls gateway adapter."""

    @pytest.mark.asyncio
    async def test_fetcher_calls_get_asset_info(self):
        from src.server.core.use_cases.structured_data import company_profile_fetcher

        mock_asset = MagicMock()
        mock_asset.model_dump.return_value = {
            "ticker": "SSE:600519",
            "name": "贵州茅台",
            "properties": {"industry": "白酒"},
        }

        mock_adapter = MagicMock()
        mock_adapter.get_asset_info = AsyncMock(return_value=mock_asset)

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=mock_adapter)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await company_profile_fetcher(
                "company_profile", "akshare", "SSE:600519"
            )

        assert result is not None
        mock_adapter.get_asset_info.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetcher_returns_none_when_no_adapter(self):
        from src.server.core.use_cases.structured_data import company_profile_fetcher

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=None)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await company_profile_fetcher(
                "company_profile", "unknown", "TEST:X"
            )

        assert result is None


class TestCompanyProfileDatasetConfig:
    """Verify company_profile is registered in the default registry."""

    def test_dataset_config_exists(self):
        from src.server.domain.structured_data.registry import build_default_registry

        registry = build_default_registry()
        config = registry.require("company_profile")
        assert config is not None
        assert config.dataset_key == "company_profile"
        assert config.primary_key_template == "{exchange}:{symbol}"

    def test_normalizer_dataset_key(self):
        from src.server.domain.structured_data.normalize.company_profile import (
            CompanyProfileNormalizer,
        )

        n = CompanyProfileNormalizer()
        assert n.dataset_key == "company_profile"
