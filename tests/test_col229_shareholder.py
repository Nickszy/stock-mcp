# tests/test_col229_shareholder.py
"""Tests for COL-229: shareholder structured data dimension."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestShareholderNormalizer:
    """Verify ShareholderNormalizer field mapping."""

    @pytest.mark.asyncio
    async def test_tushare_normalization(self):
        from src.server.domain.structured_data.normalize.shareholder import (
            ShareholderNormalizer,
        )

        normalizer = ShareholderNormalizer()
        raw_data = {
            "ts_code": "600519.SH",
            "data": {
                "top10_holders": [
                    {
                        "ts_code": "600519.SH",
                        "ann_date": "20240330",
                        "end_date": "20231231",
                        "holder_name": "中国贵州茅台酒厂(集团)有限责任公司",
                        "hold_amount": 641055300.0,
                        "hold_ratio": 54.06,
                    }
                ],
                "top10_floatholders": [],
                "holder_number": [],
                "holder_trade": [],
            },
        }
        result = await normalizer.normalize(
            raw_data, source="tushare", symbol="600519", exchange="SSE"
        )
        assert result["symbol"] == "600519"
        assert result["exchange"] == "SSE"
        assert result["_source"] == "tushare"
        assert len(result["top10_holders"]) == 1
        holder = result["top10_holders"][0]
        assert holder["holder_name"] == "中国贵州茅台酒厂(集团)有限责任公司"
        assert holder["hold_ratio"] == 54.06
        assert holder["hold_amount"] == 641055300.0
        # Date formatted
        assert holder["end_date"] == "2023-12-31"
        assert holder["ann_date"] == "2024-03-30"

    @pytest.mark.asyncio
    async def test_ts_code_parsing(self):
        from src.server.domain.structured_data.normalize.shareholder import (
            ShareholderNormalizer,
        )

        normalizer = ShareholderNormalizer()
        raw_data = {
            "ts_code": "000001.SZ",
            "data": {
                "top10_holders": [],
                "top10_floatholders": [],
                "holder_number": [],
                "holder_trade": [],
            },
        }
        result = await normalizer.normalize(raw_data, source="tushare")
        assert result["symbol"] == "000001"
        assert result["exchange"] == "SZSE"

    @pytest.mark.asyncio
    async def test_multiple_sections(self):
        from src.server.domain.structured_data.normalize.shareholder import (
            ShareholderNormalizer,
        )

        normalizer = ShareholderNormalizer()
        raw_data = {
            "ts_code": "600519.SH",
            "data": {
                "top10_holders": [
                    {"holder_name": "Holder A", "hold_ratio": 54.0,
                     "hold_amount": 100.0, "ts_code": "600519.SH",
                     "ann_date": "20240330", "end_date": "20231231"},
                ],
                "top10_floatholders": [
                    {"holder_name": "Float A", "hold_ratio": 30.0,
                     "hold_amount": 50.0, "ts_code": "600519.SH",
                     "ann_date": "20240330", "end_date": "20231231"},
                ],
                "holder_number": [
                    {"holder_num": 150000, "ts_code": "600519.SH",
                     "ann_date": "20240330", "end_date": "20231231"},
                ],
                "holder_trade": [
                    {"holder_name": "Insider", "trade_type": "BUY",
                     "vol": 1000, "change_vol": 1000, "ts_code": "600519.SH",
                     "ann_date": "20240315"},
                ],
            },
        }
        result = await normalizer.normalize(
            raw_data, source="tushare", symbol="600519", exchange="SSE"
        )
        assert len(result["top10_holders"]) == 1
        assert len(result["top10_floatholders"]) == 1
        assert len(result["holder_number"]) == 1
        assert len(result["holder_trade"]) == 1

    @pytest.mark.asyncio
    async def test_generic_passthrough(self):
        from src.server.domain.structured_data.normalize.shareholder import (
            ShareholderNormalizer,
        )

        normalizer = ShareholderNormalizer()
        raw_data = {
            "top10_holders": [{"holder_name": "Test Holder"}],
            "top10_floatholders": [],
            "holder_number": [],
            "holder_trade": [],
        }
        result = await normalizer.normalize(
            raw_data, source="generic", symbol="AAPL", exchange="NASDAQ"
        )
        assert result["symbol"] == "AAPL"
        assert result["_source"] == "generic"

    @pytest.mark.asyncio
    async def test_empty_holders(self):
        from src.server.domain.structured_data.normalize.shareholder import (
            ShareholderNormalizer,
        )

        normalizer = ShareholderNormalizer()
        raw_data = {
            "ts_code": "600519.SH",
            "data": {
                "top10_holders": [],
                "top10_floatholders": [],
                "holder_number": [],
                "holder_trade": [],
            },
        }
        result = await normalizer.normalize(
            raw_data, source="tushare", symbol="600519", exchange="SSE"
        )
        assert result["top10_holders"] == []


class TestShareholderValidator:
    """Verify shareholder validation rules."""

    @pytest.mark.asyncio
    async def test_missing_business_key_triggers_error(self):
        from src.server.domain.structured_data.validate.shareholder import (
            register_shareholder_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_shareholder_rules(engine)

        result = await engine.validate("shareholder", "SSE:600519", {})
        assert result.error_count >= 1
        assert any(i.field_path == "business_key" for i in result.issues)

    @pytest.mark.asyncio
    async def test_valid_data_passes(self):
        from src.server.domain.structured_data.validate.shareholder import (
            register_shareholder_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_shareholder_rules(engine)

        data = {
            "business_key": "SSE:600519:20231231:all",
            "top10_holders": [
                {"holder_name": "Holder A", "hold_ratio": 54.0, "hold_amount": 100.0}
            ],
        }
        result = await engine.validate("shareholder", "SSE:600519", data)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_empty_holders_warning(self):
        from src.server.domain.structured_data.validate.shareholder import (
            register_shareholder_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_shareholder_rules(engine)

        data = {"business_key": "SSE:600519:20231231:all", "top10_holders": []}
        result = await engine.validate("shareholder", "SSE:600519", data)
        assert any(i.rule_name == "top10_non_empty" for i in result.issues)

    @pytest.mark.asyncio
    async def test_hold_ratio_out_of_range(self):
        from src.server.domain.structured_data.validate.shareholder import (
            register_shareholder_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_shareholder_rules(engine)

        data = {
            "business_key": "SSE:600519:20231231:all",
            "top10_holders": [
                {"holder_name": "Holder A", "hold_ratio": 150.0, "hold_amount": 100.0}
            ],
        }
        result = await engine.validate("shareholder", "SSE:600519", data)
        assert any(i.rule_name == "hold_ratio_valid" for i in result.issues)

    @pytest.mark.asyncio
    async def test_negative_hold_amount(self):
        from src.server.domain.structured_data.validate.shareholder import (
            register_shareholder_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_shareholder_rules(engine)

        data = {
            "business_key": "SSE:600519:20231231:all",
            "top10_holders": [
                {"holder_name": "Holder A", "hold_ratio": 10.0, "hold_amount": -500.0}
            ],
        }
        result = await engine.validate("shareholder", "SSE:600519", data)
        assert any(i.rule_name == "hold_amount_non_negative" for i in result.issues)


class TestShareholderFetcher:
    """Verify shareholder_fetcher calls gateway adapter."""

    @pytest.mark.asyncio
    async def test_fetcher_calls_get_shareholder_info(self):
        from src.server.core.use_cases.structured_data import shareholder_fetcher

        mock_result = {
            "ts_code": "600519.SH",
            "data": {
                "top10_holders": [{"holder_name": "Holder A"}],
                "top10_floatholders": [],
                "holder_number": [],
                "holder_trade": [],
            },
        }

        mock_adapter = MagicMock()
        mock_adapter.get_shareholder_info = AsyncMock(return_value=mock_result)

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=mock_adapter)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await shareholder_fetcher(
                "shareholder", "tushare", "SSE:600519"
            )

        assert result is not None
        assert result.get("_source") == "tushare"
        mock_adapter.get_shareholder_info.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetcher_returns_none_when_no_adapter(self):
        from src.server.core.use_cases.structured_data import shareholder_fetcher

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=None)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await shareholder_fetcher(
                "shareholder", "unknown", "TEST:X"
            )

        assert result is None


class TestShareholderDatasetConfig:
    """Verify shareholder is registered in the default registry."""

    def test_dataset_config_exists(self):
        from src.server.domain.structured_data.registry import build_default_registry

        registry = build_default_registry()
        config = registry.require("shareholder")
        assert config.dataset_key == "shareholder"
        assert config.primary_key_template == "{exchange}:{symbol}:{report_period}:{holder_type}"

    def test_normalizer_dataset_key(self):
        from src.server.domain.structured_data.normalize.shareholder import (
            ShareholderNormalizer,
        )

        n = ShareholderNormalizer()
        assert n.dataset_key == "shareholder"
