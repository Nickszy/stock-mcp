# tests/test_col232_daily_market_data.py
"""Tests for COL-232: daily market data structured data dimension."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDailyMarketDataNormalizer:
    """Verify DailyMarketDataNormalizer field mapping."""

    @pytest.mark.asyncio
    async def test_ohlcv_row_normalization(self):
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )

        normalizer = DailyMarketDataNormalizer()
        raw_data = {
            "rows": [
                {
                    "ticker": "SSE:600519",
                    "timestamp": "2024-03-28T00:00:00Z",
                    "open_price": 1700.0,
                    "high_price": 1720.5,
                    "low_price": 1695.0,
                    "close_price": 1710.0,
                    "volume": 2500000,
                    "change": 10.0,
                    "change_percent": 0.59,
                    "market_cap": 2100000000000,
                    "currency": "CNY",
                },
            ],
        }
        result = await normalizer.normalize(
            raw_data, source="tushare", symbol="600519", exchange="SSE"
        )
        assert result["symbol"] == "600519"
        assert result["exchange"] == "SSE"
        assert result["_source"] == "tushare"
        assert result["row_count"] == 1
        row = result["rows"][0]
        assert row["open"] == 1700.0
        assert row["high"] == 1720.5
        assert row["low"] == 1695.0
        assert row["close"] == 1710.0
        assert row["volume"] == 2500000.0
        assert row["change"] == 10.0
        assert row["change_percent"] == 0.59
        assert row["market_cap"] == 2100000000000.0
        assert row["trade_date"] == "20240328"
        assert row["currency"] == "CNY"

    @pytest.mark.asyncio
    async def test_single_row_input(self):
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )

        normalizer = DailyMarketDataNormalizer()
        raw_data = {
            "ticker": "SSE:600519",
            "timestamp": "2024-03-28T00:00:00Z",
            "open_price": 1700.0,
            "high_price": 1720.0,
            "low_price": 1690.0,
            "close_price": 1710.0,
            "volume": 2500000,
        }
        result = await normalizer.normalize(
            raw_data, source="baostock", symbol="600519", exchange="SSE"
        )
        assert result["row_count"] == 1
        assert result["rows"][0]["close"] == 1710.0

    @pytest.mark.asyncio
    async def test_empty_rows(self):
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )

        normalizer = DailyMarketDataNormalizer()
        raw_data = {"rows": []}
        result = await normalizer.normalize(
            raw_data, source="akshare", symbol="600519", exchange="SSE"
        )
        assert result["rows"] == []
        assert result["row_count"] == 0
        assert result["business_key"] == ""

    @pytest.mark.asyncio
    async def test_generic_passthrough(self):
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )

        normalizer = DailyMarketDataNormalizer()
        raw_data = {
            "rows": [
                {
                    "open_price": 150.0,
                    "high_price": 155.0,
                    "low_price": 149.0,
                    "close_price": 153.0,
                    "volume": 1000000,
                    "timestamp": "2024-01-15",
                },
            ],
        }
        result = await normalizer.normalize(
            raw_data, source="generic", symbol="AAPL", exchange="NASDAQ"
        )
        assert result["symbol"] == "AAPL"
        assert result["exchange"] == "NASDAQ"
        assert result["_source"] == "generic"
        assert result["rows"][0]["close"] == 153.0

    @pytest.mark.asyncio
    async def test_ticker_parsing(self):
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )

        normalizer = DailyMarketDataNormalizer()
        raw_data = {
            "rows": [
                {
                    "ticker": "SZSE:000001",
                    "timestamp": "2024-03-28",
                    "close_price": 12.5,
                },
            ],
        }
        result = await normalizer.normalize(raw_data, source="test")
        row = result["rows"][0]
        assert row["symbol"] == "000001"
        assert row["exchange"] == "SZSE"

    @pytest.mark.asyncio
    async def test_price_fallback(self):
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )

        normalizer = DailyMarketDataNormalizer()
        raw_data = {
            "rows": [
                {
                    "ticker": "SSE:600519",
                    "timestamp": "2024-03-28",
                    "price": 1700.0,
                },
            ],
        }
        result = await normalizer.normalize(
            raw_data, source="test", symbol="600519", exchange="SSE"
        )
        assert result["rows"][0]["close"] == 1700.0

    @pytest.mark.asyncio
    async def test_none_values_handled(self):
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )

        normalizer = DailyMarketDataNormalizer()
        raw_data = {
            "rows": [
                {
                    "ticker": "SSE:600519",
                    "timestamp": "2024-03-28",
                    "open_price": None,
                    "high_price": None,
                    "low_price": None,
                    "close_price": 1700.0,
                    "volume": None,
                },
            ],
        }
        result = await normalizer.normalize(
            raw_data, source="test", symbol="600519", exchange="SSE"
        )
        row = result["rows"][0]
        assert row["open"] is None
        assert row["high"] is None
        assert row["low"] is None
        assert row["close"] == 1700.0
        assert row["volume"] is None

    @pytest.mark.asyncio
    async def test_multiple_rows(self):
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )

        normalizer = DailyMarketDataNormalizer()
        raw_data = {
            "rows": [
                {
                    "ticker": "SSE:600519",
                    "timestamp": "2024-03-27",
                    "open_price": 1700.0,
                    "close_price": 1710.0,
                },
                {
                    "ticker": "SSE:600519",
                    "timestamp": "2024-03-28",
                    "open_price": 1710.0,
                    "close_price": 1720.0,
                },
            ],
        }
        result = await normalizer.normalize(
            raw_data, source="test", symbol="600519", exchange="SSE"
        )
        assert result["row_count"] == 2
        assert result["trade_date"] == "20240328"
        assert result["business_key"] == "SSE:600519:20240328"


class TestDailyMarketDataValidator:
    """Verify daily market data validation rules."""

    @pytest.mark.asyncio
    async def test_missing_business_key_triggers_error(self):
        from src.server.domain.structured_data.validate.daily_market_data import (
            register_daily_market_data_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_daily_market_data_rules(engine)

        result = await engine.validate("daily_market_data", "SSE:600519:20240328", {})
        assert result.error_count >= 1
        assert any(i.field_path == "business_key" for i in result.issues)

    @pytest.mark.asyncio
    async def test_valid_data_passes(self):
        from src.server.domain.structured_data.validate.daily_market_data import (
            register_daily_market_data_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_daily_market_data_rules(engine)

        data = {
            "business_key": "SSE:600519:20240328",
            "rows": [
                {
                    "open": 1700.0,
                    "high": 1720.0,
                    "low": 1690.0,
                    "close": 1710.0,
                    "volume": 2500000,
                },
            ],
        }
        result = await engine.validate("daily_market_data", "SSE:600519:20240328", data)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_empty_rows_warning(self):
        from src.server.domain.structured_data.validate.daily_market_data import (
            register_daily_market_data_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_daily_market_data_rules(engine)

        data = {"business_key": "SSE:600519:20240328", "rows": []}
        result = await engine.validate("daily_market_data", "SSE:600519:20240328", data)
        assert any(i.rule_name == "rows_not_empty" for i in result.issues)

    @pytest.mark.asyncio
    async def test_ohlc_high_less_than_low(self):
        from src.server.domain.structured_data.validate.daily_market_data import (
            register_daily_market_data_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_daily_market_data_rules(engine)

        data = {
            "business_key": "SSE:600519:20240328",
            "rows": [
                {
                    "open": 1700.0,
                    "high": 1690.0,
                    "low": 1720.0,
                    "close": 1710.0,
                    "volume": 1000,
                },
            ],
        }
        result = await engine.validate("daily_market_data", "SSE:600519:20240328", data)
        assert any(i.rule_name == "ohlc_consistent" for i in result.issues)

    @pytest.mark.asyncio
    async def test_ohlc_high_less_than_open(self):
        from src.server.domain.structured_data.validate.daily_market_data import (
            register_daily_market_data_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_daily_market_data_rules(engine)

        data = {
            "business_key": "SSE:600519:20240328",
            "rows": [
                {
                    "open": 1750.0,
                    "high": 1720.0,
                    "low": 1700.0,
                    "close": 1710.0,
                    "volume": 1000,
                },
            ],
        }
        result = await engine.validate("daily_market_data", "SSE:600519:20240328", data)
        assert any(i.rule_name == "ohlc_consistent" for i in result.issues)

    @pytest.mark.asyncio
    async def test_negative_volume_error(self):
        from src.server.domain.structured_data.validate.daily_market_data import (
            register_daily_market_data_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_daily_market_data_rules(engine)

        data = {
            "business_key": "SSE:600519:20240328",
            "rows": [
                {
                    "open": 1700.0,
                    "high": 1720.0,
                    "low": 1690.0,
                    "close": 1710.0,
                    "volume": -100,
                },
            ],
        }
        result = await engine.validate("daily_market_data", "SSE:600519:20240328", data)
        assert any(i.rule_name == "volume_non_negative" for i in result.issues)

    @pytest.mark.asyncio
    async def test_zero_close_error(self):
        from src.server.domain.structured_data.validate.daily_market_data import (
            register_daily_market_data_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_daily_market_data_rules(engine)

        data = {
            "business_key": "SSE:600519:20240328",
            "rows": [
                {
                    "open": 1700.0,
                    "high": 1720.0,
                    "low": 1690.0,
                    "close": 0,
                    "volume": 1000,
                },
            ],
        }
        result = await engine.validate("daily_market_data", "SSE:600519:20240328", data)
        assert any(i.rule_name == "close_not_zero" for i in result.issues)


class TestDailyMarketDataFetcher:
    """Verify daily_market_data_fetcher calls gateway adapter."""

    @pytest.mark.asyncio
    async def test_fetcher_calls_get_historical_prices(self):
        from src.server.core.use_cases.structured_data import daily_market_data_fetcher

        price_dict = {
            "ticker": "SSE:600519",
            "price": 1710.0,
            "currency": "CNY",
            "timestamp": "2024-03-28",
            "volume": 2500000,
            "open_price": 1700.0,
            "high_price": 1720.0,
            "low_price": 1690.0,
            "close_price": 1710.0,
            "change": 10.0,
            "change_percent": 0.59,
            "market_cap": 2100000000000.0,
        }
        mock_price = MagicMock()
        mock_price.to_dict = MagicMock(return_value=price_dict)

        mock_adapter = MagicMock()
        mock_adapter.get_historical_prices = AsyncMock(return_value=[mock_price])

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=mock_adapter)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await daily_market_data_fetcher(
                "daily_market_data", "tushare", "SSE:600519"
            )

        assert result is not None
        assert result.get("_source") == "tushare"
        assert len(result["rows"]) == 1
        assert result["rows"][0]["close_price"] == 1710.0
        mock_adapter.get_historical_prices.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetcher_returns_none_when_no_adapter(self):
        from src.server.core.use_cases.structured_data import daily_market_data_fetcher

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=None)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await daily_market_data_fetcher(
                "daily_market_data", "unknown", "TEST:X"
            )

        assert result is None


class TestDailyMarketDataDatasetConfig:
    """Verify daily_market_data is registered in the default registry."""

    def test_dataset_config_exists(self):
        from src.server.domain.structured_data.registry import build_default_registry

        registry = build_default_registry()
        config = registry.require("daily_market_data")
        assert config.dataset_key == "daily_market_data"
        assert config.primary_key_template == "{exchange}:{symbol}:{trade_date}"

    def test_normalizer_dataset_key(self):
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )

        n = DailyMarketDataNormalizer()
        assert n.dataset_key == "daily_market_data"
