# tests/test_col228_dividend.py
"""Tests for COL-228: dividend structured data dimension."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDividendNormalizer:
    """Verify DividendNormalizer field mapping."""

    @pytest.mark.asyncio
    async def test_tushare_normalization(self):
        from src.server.domain.structured_data.normalize.dividend import (
            DividendNormalizer,
        )

        normalizer = DividendNormalizer()
        raw_data = {
            "ts_code": "600519.SH",
            "rows": [
                {
                    "end_date": "20231231",
                    "ann_date": "20240329",
                    "div_proc": "实施",
                    "stk_div": 0.0,
                    "stk_bo_rate": 0.0,
                    "stk_co_rate": 0.0,
                    "cash_div": 25.91,
                    "cash_div_tax": 30.87,
                    "record_date": "20240619",
                    "ex_date": "20240619",
                    "pay_date": "20240619",
                    "div_listdate": None,
                    "imp_ann_date": None,
                    "base_share": None,
                }
            ],
        }
        result = await normalizer.normalize(
            raw_data, source="tushare", symbol="600519", exchange="SSE"
        )
        assert result["business_key"] == "SSE:600519:20231231:cash"
        assert result["symbol"] == "600519"
        assert result["exchange"] == "SSE"
        assert result["row_count"] == 1
        assert result["_source"] == "tushare"
        # Check date formatting (YYYYMMDD → YYYY-MM-DD)
        row = result["rows"][0]
        assert row["end_date"] == "2023-12-31"
        assert row["ann_date"] == "2024-03-29"
        assert row["ex_date"] == "2024-06-19"
        assert row["cash_div"] == 25.91
        assert row["cash_div_tax"] == 30.87

    @pytest.mark.asyncio
    async def test_tushare_ts_code_parsing(self):
        from src.server.domain.structured_data.normalize.dividend import (
            DividendNormalizer,
        )

        normalizer = DividendNormalizer()
        raw_data = {
            "ts_code": "000001.SZ",
            "rows": [],
        }
        result = await normalizer.normalize(raw_data, source="tushare")
        assert result["symbol"] == "000001"
        assert result["exchange"] == "SZSE"

    @pytest.mark.asyncio
    async def test_multiple_rows_sorted(self):
        from src.server.domain.structured_data.normalize.dividend import (
            DividendNormalizer,
        )

        normalizer = DividendNormalizer()
        raw_data = {
            "ts_code": "600519.SH",
            "rows": [
                {"end_date": "20211231", "cash_div": 21.51, "cash_div_tax": 27.23,
                 "ann_date": None, "div_proc": None, "stk_div": None,
                 "stk_bo_rate": None, "stk_co_rate": None, "record_date": None,
                 "ex_date": None, "pay_date": None, "div_listdate": None,
                 "imp_ann_date": None, "base_share": None},
                {"end_date": "20221231", "cash_div": 27.54, "cash_div_tax": 30.6,
                 "ann_date": None, "div_proc": None, "stk_div": None,
                 "stk_bo_rate": None, "stk_co_rate": None, "record_date": None,
                 "ex_date": None, "pay_date": None, "div_listdate": None,
                 "imp_ann_date": None, "base_share": None},
                {"end_date": "20231231", "cash_div": 25.91, "cash_div_tax": 30.87,
                 "ann_date": None, "div_proc": None, "stk_div": None,
                 "stk_bo_rate": None, "stk_co_rate": None, "record_date": None,
                 "ex_date": None, "pay_date": None, "div_listdate": None,
                 "imp_ann_date": None, "base_share": None},
            ],
        }
        result = await normalizer.normalize(
            raw_data, source="tushare", symbol="600519", exchange="SSE"
        )
        assert result["row_count"] == 3
        # Latest end_date used for overall business_key
        assert "20231231" in result["business_key"]

    @pytest.mark.asyncio
    async def test_empty_rows(self):
        from src.server.domain.structured_data.normalize.dividend import (
            DividendNormalizer,
        )

        normalizer = DividendNormalizer()
        raw_data = {"ts_code": "600519.SH", "rows": []}
        result = await normalizer.normalize(
            raw_data, source="tushare", symbol="600519", exchange="SSE"
        )
        assert result["row_count"] == 0
        assert result["rows"] == []

    @pytest.mark.asyncio
    async def test_generic_passthrough(self):
        from src.server.domain.structured_data.normalize.dividend import (
            DividendNormalizer,
        )

        normalizer = DividendNormalizer()
        raw_data = {
            "rows": [
                {"end_date": "2024-06-30", "cash_div": 10.0},
            ]
        }
        result = await normalizer.normalize(
            raw_data, source="generic", symbol="AAPL", exchange="NASDAQ"
        )
        assert result["symbol"] == "AAPL"
        assert result["exchange"] == "NASDAQ"
        assert result["_source"] == "generic"


class TestDividendValidator:
    """Verify dividend validation rules."""

    @pytest.mark.asyncio
    async def test_missing_business_key_triggers_error(self):
        from src.server.domain.structured_data.validate.dividend import (
            register_dividend_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_dividend_rules(engine)

        result = await engine.validate("dividend", "SSE:600519", {})
        assert result.error_count >= 1
        assert any(i.field_path == "business_key" for i in result.issues)

    @pytest.mark.asyncio
    async def test_missing_rows_triggers_error(self):
        from src.server.domain.structured_data.validate.dividend import (
            register_dividend_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_dividend_rules(engine)

        result = await engine.validate(
            "dividend", "SSE:600519", {"business_key": "SSE:600519:20231231:cash"}
        )
        assert result.error_count >= 1
        assert any("rows" in i.field_path for i in result.issues)

    @pytest.mark.asyncio
    async def test_empty_rows_warning(self):
        from src.server.domain.structured_data.validate.dividend import (
            register_dividend_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_dividend_rules(engine)

        data = {"business_key": "SSE:600519:20231231:cash", "rows": []}
        result = await engine.validate("dividend", "SSE:600519", data)
        assert any(i.rule_name == "rows_not_empty" for i in result.issues)

    @pytest.mark.asyncio
    async def test_valid_data_passes(self):
        from src.server.domain.structured_data.validate.dividend import (
            register_dividend_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_dividend_rules(engine)

        data = {
            "business_key": "SSE:600519:20231231:cash",
            "rows": [
                {
                    "end_date": "2023-12-31",
                    "cash_div": 25.91,
                    "cash_div_tax": 30.87,
                    "stk_bo_rate": 0.0,
                    "stk_co_rate": 0.0,
                }
            ],
        }
        result = await engine.validate("dividend", "SSE:600519", data)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_invalid_end_date_format(self):
        from src.server.domain.structured_data.validate.dividend import (
            register_dividend_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_dividend_rules(engine)

        data = {
            "business_key": "SSE:600519:20231231:cash",
            "rows": [{"end_date": "not-a-date"}],
        }
        result = await engine.validate("dividend", "SSE:600519", data)
        assert any(i.rule_name == "row_end_dates_valid" for i in result.issues)

    @pytest.mark.asyncio
    async def test_negative_cash_div(self):
        from src.server.domain.structured_data.validate.dividend import (
            register_dividend_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_dividend_rules(engine)

        data = {
            "business_key": "SSE:600519:20231231:cash",
            "rows": [
                {"end_date": "2023-12-31", "cash_div": -5.0},
            ],
        }
        result = await engine.validate("dividend", "SSE:600519", data)
        assert any(i.rule_name == "cash_div_non_negative" for i in result.issues)

    @pytest.mark.asyncio
    async def test_negative_stock_div_rate(self):
        from src.server.domain.structured_data.validate.dividend import (
            register_dividend_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_dividend_rules(engine)

        data = {
            "business_key": "SSE:600519:20231231:cash",
            "rows": [
                {"end_date": "2023-12-31", "stk_bo_rate": -1.5},
            ],
        }
        result = await engine.validate("dividend", "SSE:600519", data)
        assert any(i.rule_name == "stock_div_non_negative" for i in result.issues)


class TestDividendFetcher:
    """Verify dividend_fetcher calls gateway adapter."""

    @pytest.mark.asyncio
    async def test_fetcher_calls_get_dividend_info(self):
        from src.server.core.use_cases.structured_data import dividend_fetcher

        mock_result = {
            "ts_code": "600519.SH",
            "rows": [
                {"end_date": "20231231", "cash_div": 25.91},
            ],
        }

        mock_adapter = MagicMock()
        mock_adapter.get_dividend_info = AsyncMock(return_value=mock_result)

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=mock_adapter)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await dividend_fetcher(
                "dividend", "tushare", "SSE:600519"
            )

        assert result is not None
        assert result.get("_source") == "tushare"
        mock_adapter.get_dividend_info.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetcher_returns_none_when_no_adapter(self):
        from src.server.core.use_cases.structured_data import dividend_fetcher

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=None)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await dividend_fetcher(
                "dividend", "unknown", "TEST:X"
            )

        assert result is None


class TestDividendDatasetConfig:
    """Verify dividend is registered in the default registry."""

    def test_dataset_config_exists(self):
        from src.server.domain.structured_data.registry import build_default_registry

        registry = build_default_registry()
        config = registry.require("dividend")
        assert config.dataset_key == "dividend"
        assert config.primary_key_template == "{exchange}:{symbol}:{report_period}:{dividend_type}"

    def test_normalizer_dataset_key(self):
        from src.server.domain.structured_data.normalize.dividend import (
            DividendNormalizer,
        )

        n = DividendNormalizer()
        assert n.dataset_key == "dividend"
