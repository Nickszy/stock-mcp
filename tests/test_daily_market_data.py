"""Tests for daily_market_data structured data dimension.

Covers:
- DailyMarketDataNormalizer: single row, multi-row, field mapping, business key construction
- Validation rules: OHLC consistency, volume non-negative, close not zero, rows not empty
- Fetcher registration in registry
"""

import pytest
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------

class TestDailyMarketDataNormalizer:
    """Tests for DailyMarketDataNormalizer."""

    @pytest.fixture
    def normalizer(self):
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )
        return DailyMarketDataNormalizer()

    @pytest.mark.asyncio
    async def test_dataset_key(self, normalizer):
        assert normalizer.dataset_key == "daily_market_data"

    @pytest.mark.asyncio
    async def test_normalize_single_row(self, normalizer):
        """Single-row input (one day of data) is normalized correctly."""
        raw = {
            "ticker": "SSE:600519",
            "timestamp": "2024-09-30",
            "open_price": 1800.0,
            "high_price": 1820.0,
            "low_price": 1790.0,
            "close_price": 1810.0,
            "volume": 50000,
            "change": 10.0,
            "change_percent": 0.55,
            "market_cap": 2270000000000,
        }

        result = await normalizer.normalize(raw, source="akshare", symbol="600519", exchange="SSE")

        assert result["symbol"] == "600519"
        assert result["exchange"] == "SSE"
        assert result["row_count"] == 1
        assert len(result["rows"]) == 1
        assert result["rows"][0]["open"] == 1800.0
        assert result["rows"][0]["high"] == 1820.0
        assert result["rows"][0]["low"] == 1790.0
        assert result["rows"][0]["close"] == 1810.0
        assert result["rows"][0]["volume"] == 50000.0

    @pytest.mark.asyncio
    async def test_normalize_multi_row(self, normalizer):
        """Multi-row input with 'rows' key is normalized correctly."""
        raw = {
            "rows": [
                {
                    "ticker": "SSE:600519",
                    "timestamp": "2024-09-30",
                    "open_price": 1800.0,
                    "high_price": 1820.0,
                    "low_price": 1790.0,
                    "close_price": 1810.0,
                    "volume": 50000,
                },
                {
                    "ticker": "SSE:600519",
                    "timestamp": "2024-09-29",
                    "open_price": 1790.0,
                    "high_price": 1805.0,
                    "low_price": 1785.0,
                    "close_price": 1800.0,
                    "volume": 45000,
                },
            ]
        }

        result = await normalizer.normalize(raw, source="akshare", symbol="600519", exchange="SSE")

        assert result["row_count"] == 2
        # trade_date is from the last row in the list
        assert result["trade_date"] == "20240929"
        assert result["business_key"] == "SSE:600519:20240929"

    @pytest.mark.asyncio
    async def test_normalize_extracts_symbol_from_ticker(self, normalizer):
        """When symbol/exchange not provided, extracts from ticker field."""
        raw = {
            "ticker": "SSE:600519",
            "timestamp": "2024-09-30",
            "open_price": 1800.0,
            "high_price": 1820.0,
            "low_price": 1790.0,
            "close_price": 1810.0,
        }

        result = await normalizer.normalize(raw, source="akshare")

        row = result["rows"][0]
        assert row["symbol"] == "600519"
        assert row["exchange"] == "SSE"

    @pytest.mark.asyncio
    async def test_normalize_uses_close_price_or_price(self, normalizer):
        """Falls back to 'price' field when 'close_price' is absent."""
        raw = {
            "ticker": "NASDAQ:AAPL",
            "timestamp": "2024-09-30",
            "price": 175.0,
        }

        result = await normalizer.normalize(raw, source="yahoo", symbol="AAPL", exchange="NASDAQ")

        assert result["rows"][0]["close"] == 175.0

    @pytest.mark.asyncio
    async def test_normalize_trade_date_from_timestamp(self, normalizer):
        """Trade date is extracted from timestamp field."""
        raw = {
            "ticker": "SSE:600519",
            "timestamp": "2024-06-15T10:30:00",
            "open_price": 1800,
            "close_price": 1810,
        }

        result = await normalizer.normalize(raw, source="akshare", symbol="600519", exchange="SSE")

        assert result["rows"][0]["trade_date"] == "20240615"

    @pytest.mark.asyncio
    async def test_normalize_skips_non_dict_rows(self, normalizer):
        """Non-dict items in rows list are silently skipped."""
        raw = {
            "rows": [
                {"ticker": "SSE:600519", "timestamp": "2024-09-30", "close_price": 1810},
                "invalid",
                42,
                None,
            ]
        }

        result = await normalizer.normalize(raw, source="akshare", symbol="600519", exchange="SSE")

        assert result["row_count"] == 1

    @pytest.mark.asyncio
    async def test_normalize_empty_input(self, normalizer):
        """Empty input produces empty rows and empty business key."""
        result = await normalizer.normalize({}, source="akshare")

        assert result["row_count"] == 0
        assert result["rows"] == []
        assert result["business_key"] == ""

    @pytest.mark.asyncio
    async def test_normalize_includes_source(self, normalizer):
        """Normalized output includes _source metadata."""
        raw = {"rows": [{"ticker": "SSE:600519", "timestamp": "2024-09-30", "close_price": 1810}]}

        result = await normalizer.normalize(raw, source="baostock", symbol="600519", exchange="SSE")

        assert result["_source"] == "baostock"


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestDailyMarketDataValidator:
    """Tests for daily_market_data validation rules."""

    @pytest.fixture
    def engine(self):
        from src.server.domain.structured_data.validate.engine import ValidationEngine
        from src.server.domain.structured_data.validate.daily_market_data import (
            register_daily_market_data_rules,
        )
        eng = ValidationEngine()
        register_daily_market_data_rules(eng)
        return eng

    @pytest.mark.asyncio
    async def test_valid_data_passes(self, engine):
        """Valid OHLCV data passes all rules."""
        data = {
            "business_key": "SSE:600519:20240930",
            "rows": [
                {"open": 1800, "high": 1820, "low": 1790, "close": 1810, "volume": 50000},
            ],
        }
        result = await engine.validate(
            dataset_key="daily_market_data",
            business_key="SSE:600519:20240930",
            data=data,
        )
        assert not result.has_errors

    @pytest.mark.asyncio
    async def test_high_less_than_low_fails(self, engine):
        """OHLC rule flags when high < low."""
        data = {
            "business_key": "SSE:600519:20240930",
            "rows": [
                {"open": 1800, "high": 1790, "low": 1820, "close": 1810, "volume": 50000},
            ],
        }
        result = await engine.validate(
            dataset_key="daily_market_data",
            business_key="SSE:600519:20240930",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "ohlc_consistent"]
        assert len(issues) > 0
        assert "high" in issues[0].message
        assert "low" in issues[0].message

    @pytest.mark.asyncio
    async def test_high_less_than_open_close_fails(self, engine):
        """OHLC rule flags when high < max(open, close)."""
        data = {
            "business_key": "SSE:600519:20240930",
            "rows": [
                {"open": 1830, "high": 1810, "low": 1790, "close": 1825, "volume": 50000},
            ],
        }
        result = await engine.validate(
            dataset_key="daily_market_data",
            business_key="SSE:600519:20240930",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "ohlc_consistent"]
        assert len(issues) > 0

    @pytest.mark.asyncio
    async def test_low_greater_than_open_close_fails(self, engine):
        """OHLC rule flags when low > min(open, close)."""
        data = {
            "business_key": "SSE:600519:20240930",
            "rows": [
                {"open": 1800, "high": 1820, "low": 1810, "close": 1795, "volume": 50000},
            ],
        }
        result = await engine.validate(
            dataset_key="daily_market_data",
            business_key="SSE:600519:20240930",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "ohlc_consistent"]
        assert len(issues) > 0

    @pytest.mark.asyncio
    async def test_negative_volume_fails(self, engine):
        """Negative volume triggers ERROR."""
        data = {
            "business_key": "SSE:600519:20240930",
            "rows": [
                {"open": 1800, "high": 1820, "low": 1790, "close": 1810, "volume": -500},
            ],
        }
        result = await engine.validate(
            dataset_key="daily_market_data",
            business_key="SSE:600519:20240930",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "volume_non_negative"]
        assert len(issues) > 0
        assert issues[0].severity == "ERROR"

    @pytest.mark.asyncio
    async def test_zero_close_fails(self, engine):
        """Zero close price triggers ERROR."""
        data = {
            "business_key": "SSE:600519:20240930",
            "rows": [
                {"open": 1800, "high": 1820, "low": 1790, "close": 0, "volume": 50000},
            ],
        }
        result = await engine.validate(
            dataset_key="daily_market_data",
            business_key="SSE:600519:20240930",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "close_not_zero"]
        assert len(issues) > 0
        assert issues[0].severity == "ERROR"

    @pytest.mark.asyncio
    async def test_empty_rows_warns(self, engine):
        """Empty rows list triggers WARNING."""
        data = {
            "business_key": "SSE:600519:20240930",
            "rows": [],
        }
        result = await engine.validate(
            dataset_key="daily_market_data",
            business_key="SSE:600519:20240930",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "rows_not_empty"]
        assert len(issues) > 0
        assert issues[0].severity == "WARNING"

    @pytest.mark.asyncio
    async def test_missing_business_key_fails(self, engine):
        """Missing business_key triggers ERROR."""
        data = {
            "rows": [{"close": 100}],
        }
        result = await engine.validate(
            dataset_key="daily_market_data",
            business_key="test",
            data=data,
        )
        # NotNullRule or NotEmptyStringRule for business_key
        issues = [i for i in result.issues if "business_key" in (i.field_path or "")]
        assert len(issues) > 0

    @pytest.mark.asyncio
    async def test_multiple_rows_all_checked(self, engine):
        """Validation checks all rows, not just the first."""
        data = {
            "business_key": "SSE:600519:20240930",
            "rows": [
                {"open": 1800, "high": 1820, "low": 1790, "close": 1810, "volume": 50000},
                {"open": 1810, "high": 1830, "low": 1800, "close": 0, "volume": 45000},
            ],
        }
        result = await engine.validate(
            dataset_key="daily_market_data",
            business_key="SSE:600519:20240930",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "close_not_zero"]
        assert len(issues) > 0


# ---------------------------------------------------------------------------
# Registry integration tests
# ---------------------------------------------------------------------------

class TestDailyMarketDataRegistry:
    """Verify daily_market_data is registered in the default registry."""

    def test_registry_has_daily_market_data(self):
        from src.server.domain.structured_data.registry import build_default_registry
        registry = build_default_registry()
        config = registry.get("daily_market_data")
        assert config is not None
        assert config.display_name == "日频市场数据"
        assert config.primary_key_template == "{exchange}:{symbol}:{trade_date}"

    def test_registry_has_sources(self):
        from src.server.domain.structured_data.registry import build_default_registry
        registry = build_default_registry()
        config = registry.get("daily_market_data")
        source_names = [s.source_name for s in config.sources]
        assert "akshare" in source_names
        assert "baostock" in source_names

    def test_normalizer_registered_in_init(self):
        """Verify the normalizer is importable and has correct dataset_key."""
        from src.server.domain.structured_data.normalize.daily_market_data import (
            DailyMarketDataNormalizer,
        )
        n = DailyMarketDataNormalizer()
        assert n.dataset_key == "daily_market_data"
