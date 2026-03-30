# tests/test_col231_index_constituents.py
"""Tests for COL-231: index constituents structured data dimension."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestIndexConstituentsNormalizer:
    """Verify IndexConstituentsNormalizer field mapping."""

    @pytest.mark.asyncio
    async def test_akshare_constituents_normalization(self):
        from src.server.domain.structured_data.normalize.index_constituents import (
            IndexConstituentsNormalizer,
        )

        normalizer = IndexConstituentsNormalizer()
        raw_data = {
            "constituents": {
                "index_code": "000300",
                "data": [
                    {
                        "日期": "2024-03-28",
                        "指数代码": "000300",
                        "指数名称": "沪深300",
                        "成分券代码": "600519",
                        "成分券名称": "贵州茅台",
                        "交易所": "上海",
                    },
                    {
                        "日期": "2024-03-28",
                        "指数代码": "000300",
                        "指数名称": "沪深300",
                        "成分券代码": "000001",
                        "成分券名称": "平安银行",
                        "交易所": "深圳",
                    },
                ],
            },
            "weights": {
                "index_code": "000300",
                "data": [
                    {
                        "日期": "2024-03-28",
                        "指数代码": "000300",
                        "成分券代码": "600519",
                        "成分券名称": "贵州茅台",
                        "权重": 5.23,
                    },
                    {
                        "日期": "2024-03-28",
                        "指数代码": "000300",
                        "成分券代码": "000001",
                        "成分券名称": "平安银行",
                        "权重": 1.12,
                    },
                ],
            },
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", index_code="000300"
        )
        assert result["index_code"] == "000300"
        assert result["_source"] == "akshare"
        assert result["constituent_count"] == 2
        assert result["index_name"] == "沪深300"

        # Check first constituent
        c1 = result["constituents"][0]
        assert c1["symbol"] == "600519"
        assert c1["exchange"] == "SSE"
        assert c1["weight"] == 5.23
        assert c1["constituent_name"] == "贵州茅台"

        # Check second constituent
        c2 = result["constituents"][1]
        assert c2["symbol"] == "000001"
        assert c2["exchange"] == "SZSE"
        assert c2["weight"] == 1.12

    @pytest.mark.asyncio
    async def test_constituents_without_weights(self):
        from src.server.domain.structured_data.normalize.index_constituents import (
            IndexConstituentsNormalizer,
        )

        normalizer = IndexConstituentsNormalizer()
        raw_data = {
            "constituents": {
                "index_code": "000905",
                "data": [
                    {
                        "日期": "2024-03-28",
                        "指数代码": "000905",
                        "指数名称": "中证500",
                        "成分券代码": "600123",
                        "成分券名称": "兰花科创",
                        "交易所": "上海",
                    }
                ],
            }
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", index_code="000905"
        )
        assert result["constituent_count"] == 1
        assert result["constituents"][0]["weight"] is None

    @pytest.mark.asyncio
    async def test_single_source_passthrough(self):
        from src.server.domain.structured_data.normalize.index_constituents import (
            IndexConstituentsNormalizer,
        )

        normalizer = IndexConstituentsNormalizer()
        raw_data = {
            "index_code": "000300",
            "data": [
                {
                    "日期": "2024-03-28",
                    "指数代码": "000300",
                    "指数名称": "沪深300",
                    "成分券代码": "600519",
                    "成分券名称": "贵州茅台",
                    "交易所": "上海",
                }
            ],
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", index_code="000300"
        )
        assert result["index_code"] == "000300"
        assert result["constituent_count"] == 1

    @pytest.mark.asyncio
    async def test_empty_data(self):
        from src.server.domain.structured_data.normalize.index_constituents import (
            IndexConstituentsNormalizer,
        )

        normalizer = IndexConstituentsNormalizer()
        raw_data = {}
        result = await normalizer.normalize(
            raw_data, source="akshare", index_code="000300"
        )
        assert result["constituents"] == []
        assert result["constituent_count"] == 0

    @pytest.mark.asyncio
    async def test_generic_passthrough(self):
        from src.server.domain.structured_data.normalize.index_constituents import (
            IndexConstituentsNormalizer,
        )

        normalizer = IndexConstituentsNormalizer()
        raw_data = {
            "data": [
                {"symbol": "AAPL", "weight": 6.5, "effective_date": "2024-03-28"}
            ]
        }
        result = await normalizer.normalize(
            raw_data, source="generic", index_code="SPX"
        )
        assert result["_source"] == "generic"
        assert result["constituent_count"] == 1

    @pytest.mark.asyncio
    async def test_business_key_format(self):
        from src.server.domain.structured_data.normalize.index_constituents import (
            IndexConstituentsNormalizer,
        )

        normalizer = IndexConstituentsNormalizer()
        raw_data = {
            "constituents": {
                "index_code": "000300",
                "data": [
                    {
                        "日期": "2024-03-28",
                        "指数代码": "000300",
                        "指数名称": "沪深300",
                        "成分券代码": "600519",
                        "成分券名称": "贵州茅台",
                        "交易所": "上海",
                    }
                ],
            }
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", index_code="000300"
        )
        assert result["business_key"] == "000300:2024-03-28"


class TestIndexConstituentsValidator:
    """Verify index constituents validation rules."""

    @pytest.mark.asyncio
    async def test_missing_business_key_triggers_error(self):
        from src.server.domain.structured_data.validate.index_constituents import (
            register_index_constituents_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_index_constituents_rules(engine)

        result = await engine.validate("index_constituents", "000300:2024-03-28", {})
        assert result.error_count >= 1
        assert any(i.field_path == "business_key" for i in result.issues)

    @pytest.mark.asyncio
    async def test_valid_data_passes(self):
        from src.server.domain.structured_data.validate.index_constituents import (
            register_index_constituents_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_index_constituents_rules(engine)

        data = {
            "business_key": "000300:2024-03-28",
            "index_code": "000300",
            "constituents": [
                {"symbol": "600519", "weight": 5.23},
                {"symbol": "000001", "weight": 1.12},
            ],
        }
        result = await engine.validate("index_constituents", "000300:2024-03-28", data)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_empty_constituents_warning(self):
        from src.server.domain.structured_data.validate.index_constituents import (
            register_index_constituents_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_index_constituents_rules(engine)

        data = {
            "business_key": "000300:2024-03-28",
            "index_code": "000300",
            "constituents": [],
        }
        result = await engine.validate("index_constituents", "000300:2024-03-28", data)
        assert any(i.rule_name == "constituents_not_empty" for i in result.issues)

    @pytest.mark.asyncio
    async def test_duplicate_symbols_error(self):
        from src.server.domain.structured_data.validate.index_constituents import (
            register_index_constituents_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_index_constituents_rules(engine)

        data = {
            "business_key": "000300:2024-03-28",
            "index_code": "000300",
            "constituents": [
                {"symbol": "600519", "weight": 5.0},
                {"symbol": "600519", "weight": 3.0},
            ],
        }
        result = await engine.validate("index_constituents", "000300:2024-03-28", data)
        assert any(i.rule_name == "no_duplicate_symbols" for i in result.issues)

    @pytest.mark.asyncio
    async def test_weight_sum_out_of_range_warning(self):
        from src.server.domain.structured_data.validate.index_constituents import (
            register_index_constituents_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_index_constituents_rules(engine)

        data = {
            "business_key": "000300:2024-03-28",
            "index_code": "000300",
            "constituents": [
                {"symbol": "600519", "weight": 50.0},
                {"symbol": "000001", "weight": 50.0},
                {"symbol": "600036", "weight": 50.0},
            ],
        }
        result = await engine.validate("index_constituents", "000300:2024-03-28", data)
        assert any(i.rule_name == "weight_sum_in_range" for i in result.issues)

    @pytest.mark.asyncio
    async def test_negative_weight_error(self):
        from src.server.domain.structured_data.validate.index_constituents import (
            register_index_constituents_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_index_constituents_rules(engine)

        data = {
            "business_key": "000300:2024-03-28",
            "index_code": "000300",
            "constituents": [
                {"symbol": "600519", "weight": -5.0},
            ],
        }
        result = await engine.validate("index_constituents", "000300:2024-03-28", data)
        assert any(i.rule_name == "weights_non_negative" for i in result.issues)


class TestIndexConstituentsFetcher:
    """Verify index_constituents_fetcher calls gateway adapter."""

    @pytest.mark.asyncio
    async def test_fetcher_calls_adapter_methods(self):
        from src.server.core.use_cases.structured_data import index_constituents_fetcher

        mock_adapter = MagicMock()
        mock_adapter.get_index_constituents = AsyncMock(
            return_value={"data": [{"成分券代码": "600519"}], "index_code": "000300"}
        )
        mock_adapter.get_index_constituent_weights = AsyncMock(
            return_value={"data": [{"成分券代码": "600519", "权重": 5.23}], "index_code": "000300"}
        )

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=mock_adapter)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await index_constituents_fetcher(
                "index_constituents", "akshare", "000300"
            )

        assert result is not None
        assert result.get("_source") == "akshare"
        assert "constituents" in result
        assert "weights" in result

    @pytest.mark.asyncio
    async def test_fetcher_returns_none_when_no_adapter(self):
        from src.server.core.use_cases.structured_data import index_constituents_fetcher

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=None)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await index_constituents_fetcher(
                "index_constituents", "unknown", "000300"
            )

        assert result is None


class TestIndexConstituentsDatasetConfig:
    """Verify index_constituents is registered in the default registry."""

    def test_dataset_config_exists(self):
        from src.server.domain.structured_data.registry import build_default_registry

        registry = build_default_registry()
        config = registry.require("index_constituents")
        assert config.dataset_key == "index_constituents"
        assert config.primary_key_template == "{index_code}:{effective_date}"

    def test_normalizer_dataset_key(self):
        from src.server.domain.structured_data.normalize.index_constituents import (
            IndexConstituentsNormalizer,
        )

        n = IndexConstituentsNormalizer()
        assert n.dataset_key == "index_constituents"
