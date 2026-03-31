"""Tests for index_constituents structured data dimension.

Covers:
- IndexConstituentsNormalizer: akshare field mapping, weight merge, exchange inference, business key
- Validation rules: weight sum range, no duplicate symbols, weights non-negative, constituents not empty
- Registry integration
"""

import pytest


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------

class TestIndexConstituentsNormalizer:
    """Tests for IndexConstituentsNormalizer."""

    @pytest.fixture
    def normalizer(self):
        from src.server.domain.structured_data.normalize.index_constituents import (
            IndexConstituentsNormalizer,
        )
        return IndexConstituentsNormalizer()

    @pytest.mark.asyncio
    async def test_dataset_key(self, normalizer):
        assert normalizer.dataset_key == "index_constituents"

    @pytest.mark.asyncio
    async def test_normalize_akshare_constituents(self, normalizer):
        """Normalizes akshare-style constituent data with Chinese field names."""
        raw = {
            "constituents": {
                "data": [
                    {
                        "日期": "2024-09-30",
                        "指数代码": "000300",
                        "指数名称": "沪深300",
                        "成分券代码": "600519",
                        "成分券名称": "贵州茅台",
                        "交易所": "上海",
                    },
                    {
                        "日期": "2024-09-30",
                        "指数代码": "000300",
                        "指数名称": "沪深300",
                        "成分券代码": "000001",
                        "成分券名称": "平安银行",
                        "交易所": "深圳",
                    },
                ],
            },
        }

        result = await normalizer.normalize(
            raw, source="akshare", index_code="000300",
        )

        assert result["index_code"] == "000300"
        assert result["index_name"] == "沪深300"
        assert result["effective_date"] == "2024-09-30"
        assert result["constituent_count"] == 2
        assert result["business_key"] == "000300:2024-09-30"
        assert result["constituents"][0]["symbol"] == "600519"
        assert result["constituents"][0]["exchange"] == "SSE"
        assert result["constituents"][0]["constituent_name"] == "贵州茅台"
        assert result["constituents"][1]["symbol"] == "000001"
        assert result["constituents"][1]["exchange"] == "SZSE"

    @pytest.mark.asyncio
    async def test_normalize_merges_weights(self, normalizer):
        """Weight data from 'weights' section is merged into constituents."""
        raw = {
            "constituents": {
                "data": [
                    {"日期": "2024-09-30", "指数代码": "000300", "指数名称": "沪深300",
                     "成分券代码": "600519", "成分券名称": "贵州茅台", "交易所": "上海"},
                    {"日期": "2024-09-30", "指数代码": "000300", "指数名称": "沪深300",
                     "成分券代码": "000001", "成分券名称": "平安银行", "交易所": "深圳"},
                ],
            },
            "weights": {
                "data": [
                    {"日期": "2024-09-30", "指数代码": "000300", "指数名称": "沪深300",
                     "成分券代码": "600519", "成分券名称": "贵州茅台", "权重": 5.2},
                    {"日期": "2024-09-30", "指数代码": "000300", "指数名称": "沪深300",
                     "成分券代码": "000001", "成分券名称": "平安银行", "权重": 1.3},
                ],
            },
        }

        result = await normalizer.normalize(
            raw, source="akshare", index_code="000300",
        )

        assert result["constituents"][0]["weight"] == 5.2
        assert result["constituents"][1]["weight"] == 1.3

    @pytest.mark.asyncio
    async def test_normalize_infers_exchange(self, normalizer):
        """Exchange is correctly inferred from Chinese market names."""
        from src.server.domain.structured_data.normalize.index_constituents import _infer_exchange

        assert _infer_exchange("上海", "600519") == "SSE"
        assert _infer_exchange("深圳", "000001") == "SZSE"
        assert _infer_exchange("北京", "430001") == "BSE"
        assert _infer_exchange("SH", "600519") == "SSE"
        assert _infer_exchange("SZ", "000001") == "SZSE"
        # When market is non-empty and matches suffix, suffix-based check works
        assert _infer_exchange("上海", "600519.SH") == "SSE"
        # Empty market returns "" regardless of symbol suffix (early return)
        assert _infer_exchange("", "600519.SH") == ""

    @pytest.mark.asyncio
    async def test_normalize_cleans_symbol_suffix(self, normalizer):
        """Exchange suffixes (.SH, .SZ, .BJ) are stripped from symbol."""
        raw = {
            "constituents": {
                "data": [
                    {"日期": "2024-09-30", "指数代码": "000300", "指数名称": "沪深300",
                     "成分券代码": "600519.SH", "成分券名称": "贵州茅台", "交易所": "上海"},
                ],
            },
        }

        result = await normalizer.normalize(
            raw, source="akshare", index_code="000300",
        )

        assert result["constituents"][0]["symbol"] == "600519"

    @pytest.mark.asyncio
    async def test_normalize_generic_passthrough(self, normalizer):
        """Non-akshare sources pass data through as-is."""
        raw = {
            "data": [
                {"symbol": "AAPL", "weight": 5.0, "exchange": "NASDAQ"},
                {"symbol": "MSFT", "weight": 4.5, "exchange": "NASDAQ"},
            ],
        }

        result = await normalizer.normalize(
            raw, source="custom", index_code="SPX",
        )

        assert result["constituent_count"] == 2
        assert result["constituents"][0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_normalize_extracts_index_code_from_data(self, normalizer):
        """Index code is extracted from data rows when not in kwargs."""
        raw = {
            "constituents": {
                "data": [
                    {"日期": "2024-09-30", "指数代码": "000905", "指数名称": "中证500",
                     "成分券代码": "600519", "成分券名称": "贵州茅台", "交易所": "上海"},
                ],
            },
        }

        result = await normalizer.normalize(raw, source="akshare")

        assert result["index_code"] == "000905"

    @pytest.mark.asyncio
    async def test_normalize_empty_input(self, normalizer):
        """Empty input produces empty constituents."""
        result = await normalizer.normalize({}, source="akshare")

        assert result["constituent_count"] == 0
        assert result["constituents"] == []
        assert result["business_key"] == ""

    @pytest.mark.asyncio
    async def test_normalize_includes_metadata(self, normalizer):
        """Output includes _source and _normalized_at."""
        raw = {"data": [{"symbol": "AAPL"}]}
        result = await normalizer.normalize(raw, source="custom", index_code="SPX")

        assert result["_source"] == "custom"
        assert "_normalized_at" in result


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestIndexConstituentsValidator:
    """Tests for index_constituents validation rules."""

    @pytest.fixture
    def engine(self):
        from src.server.domain.structured_data.validate.engine import ValidationEngine
        from src.server.domain.structured_data.validate.index_constituents import (
            register_index_constituents_rules,
        )
        eng = ValidationEngine()
        register_index_constituents_rules(eng)
        return eng

    @pytest.mark.asyncio
    async def test_valid_data_passes(self, engine):
        """Valid constituent data with proper weights passes."""
        data = {
            "business_key": "000300:2024-09-30",
            "index_code": "000300",
            "constituents": [
                {"symbol": "600519", "weight": 5.2},
                {"symbol": "000001", "weight": 1.3},
            ],
        }
        result = await engine.validate(
            dataset_key="index_constituents",
            business_key="000300:2024-09-30",
            data=data,
        )
        assert not result.has_errors

    @pytest.mark.asyncio
    async def test_weight_sum_out_of_range_warns(self, engine):
        """Weight sum outside [95, 105] triggers WARNING."""
        data = {
            "business_key": "000300:2024-09-30",
            "index_code": "000300",
            "constituents": [
                {"symbol": "600519", "weight": 50.0},
                {"symbol": "000001", "weight": 10.0},
            ],
        }
        result = await engine.validate(
            dataset_key="index_constituents",
            business_key="000300:2024-09-30",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "weight_sum_in_range"]
        assert len(issues) > 0
        assert issues[0].severity == "WARNING"

    @pytest.mark.asyncio
    async def test_weight_sum_within_range_passes(self, engine):
        """Weight sum between 95 and 105 passes."""
        constituents = [{"symbol": f"SYM{i}", "weight": 1.0} for i in range(100)]
        data = {
            "business_key": "000300:2024-09-30",
            "index_code": "000300",
            "constituents": constituents,
        }
        result = await engine.validate(
            dataset_key="index_constituents",
            business_key="000300:2024-09-30",
            data=data,
        )
        weight_issues = [i for i in result.issues if i.rule_name == "weight_sum_in_range"]
        assert len(weight_issues) == 0

    @pytest.mark.asyncio
    async def test_duplicate_symbols_error(self, engine):
        """Duplicate symbols in constituents triggers ERROR."""
        data = {
            "business_key": "000300:2024-09-30",
            "index_code": "000300",
            "constituents": [
                {"symbol": "600519", "weight": 5.0},
                {"symbol": "600519", "weight": 5.0},
            ],
        }
        result = await engine.validate(
            dataset_key="index_constituents",
            business_key="000300:2024-09-30",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "no_duplicate_symbols"]
        assert len(issues) > 0
        assert issues[0].severity == "ERROR"

    @pytest.mark.asyncio
    async def test_negative_weight_error(self, engine):
        """Negative weight triggers ERROR."""
        data = {
            "business_key": "000300:2024-09-30",
            "index_code": "000300",
            "constituents": [
                {"symbol": "600519", "weight": -1.5},
            ],
        }
        result = await engine.validate(
            dataset_key="index_constituents",
            business_key="000300:2024-09-30",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "weights_non_negative"]
        assert len(issues) > 0
        assert issues[0].severity == "ERROR"

    @pytest.mark.asyncio
    async def test_empty_constituents_warns(self, engine):
        """Empty constituents list triggers WARNING."""
        data = {
            "business_key": "000300:2024-09-30",
            "index_code": "000300",
            "constituents": [],
        }
        result = await engine.validate(
            dataset_key="index_constituents",
            business_key="000300:2024-09-30",
            data=data,
        )
        issues = [i for i in result.issues if i.rule_name == "constituents_not_empty"]
        assert len(issues) > 0
        assert issues[0].severity == "WARNING"

    @pytest.mark.asyncio
    async def test_missing_business_key_error(self, engine):
        """Missing business_key triggers ERROR."""
        data = {
            "index_code": "000300",
            "constituents": [{"symbol": "600519"}],
        }
        result = await engine.validate(
            dataset_key="index_constituents",
            business_key="test",
            data=data,
        )
        issues = [i for i in result.issues if "business_key" in (i.field_path or "")]
        assert len(issues) > 0

    @pytest.mark.asyncio
    async def test_missing_index_code_error(self, engine):
        """Missing index_code triggers ERROR."""
        data = {
            "business_key": "000300:2024-09-30",
            "constituents": [{"symbol": "600519"}],
        }
        result = await engine.validate(
            dataset_key="index_constituents",
            business_key="000300:2024-09-30",
            data=data,
        )
        issues = [i for i in result.issues if "index_code" in (i.field_path or "")]
        assert len(issues) > 0

    @pytest.mark.asyncio
    async def test_missing_constituents_error(self, engine):
        """Missing constituents field triggers ERROR."""
        data = {
            "business_key": "000300:2024-09-30",
            "index_code": "000300",
        }
        result = await engine.validate(
            dataset_key="index_constituents",
            business_key="000300:2024-09-30",
            data=data,
        )
        issues = [i for i in result.issues if "constituents" in (i.field_path or "")]
        assert len(issues) > 0


# ---------------------------------------------------------------------------
# Registry integration tests
# ---------------------------------------------------------------------------

class TestIndexConstituentsRegistry:
    """Verify index_constituents is registered in the default registry."""

    def test_registry_has_index_constituents(self):
        from src.server.domain.structured_data.registry import build_default_registry
        registry = build_default_registry()
        config = registry.get("index_constituents")
        assert config is not None
        assert config.display_name == "指数成分与权重"
        assert config.primary_key_template == "{index_code}:{effective_date}"

    def test_registry_has_sources(self):
        from src.server.domain.structured_data.registry import build_default_registry
        registry = build_default_registry()
        config = registry.get("index_constituents")
        source_names = [s.source_name for s in config.sources]
        assert "akshare" in source_names

    def test_normalizer_importable(self):
        from src.server.domain.structured_data.normalize.index_constituents import (
            IndexConstituentsNormalizer,
        )
        n = IndexConstituentsNormalizer()
        assert n.dataset_key == "index_constituents"

    def test_fetcher_registered(self):
        """Verify the fetcher is importable from use_cases.structured_data."""
        from src.server.core.use_cases.structured_data import index_constituents_fetcher
        assert callable(index_constituents_fetcher)
