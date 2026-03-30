# tests/test_col230_corporate_actions.py
"""Tests for COL-230: corporate actions structured data dimension."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestCorporateActionsNormalizer:
    """Verify CorporateActionsNormalizer field mapping."""

    @pytest.mark.asyncio
    async def test_akshare_repurchase_normalization(self):
        from src.server.domain.structured_data.normalize.corporate_actions import (
            CorporateActionsNormalizer,
        )

        normalizer = CorporateActionsNormalizer()
        raw_data = {
            "repurchase": {
                "data": [
                    {
                        "股票代码": "600519",
                        "公司名称": "贵州茅台",
                        "回购期限": "2024-01-01至2024-12-31",
                        "回购目的": "股权激励",
                        "实施进度": "实施中",
                        "回购价格区间": "1600-1800",
                        "回购数量": 100000,
                        "回购金额": 170000000,
                        "最新公告日期": "2024-03-28",
                    }
                ]
            }
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", symbol="600519", exchange="SSE"
        )
        assert result["symbol"] == "600519"
        assert result["exchange"] == "SSE"
        assert result["_source"] == "akshare"
        assert result["event_count"] == 1
        evt = result["events"][0]
        assert evt["event_type"] == "buyback"
        assert evt["event_date"] == "2024-03-28"
        assert evt["amount"] == 170000000.0

    @pytest.mark.asyncio
    async def test_akshare_restricted_release(self):
        from src.server.domain.structured_data.normalize.corporate_actions import (
            CorporateActionsNormalizer,
        )

        normalizer = CorporateActionsNormalizer()
        raw_data = {
            "restricted_release": {
                "summary": [
                    {
                        "股票代码": "600519",
                        "股票简称": "贵州茅台",
                        "解禁日期": "2024-04-15",
                        "解禁数量": 5000000,
                        "解禁市值": 8500000000,
                        "限售股类型": "定向增发",
                    }
                ]
            }
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", symbol="600519", exchange="SSE"
        )
        assert result["event_count"] == 1
        evt = result["events"][0]
        assert evt["event_type"] == "restricted_release"
        assert evt["event_date"] == "2024-04-15"
        assert evt["amount"] == 8500000000.0

    @pytest.mark.asyncio
    async def test_akshare_block_trade(self):
        from src.server.domain.structured_data.normalize.corporate_actions import (
            CorporateActionsNormalizer,
        )

        normalizer = CorporateActionsNormalizer()
        raw_data = {
            "block_trade": {
                "data": [
                    {
                        "交易日期": "2024-03-28",
                        "证券代码": "600519",
                        "证券简称": "贵州茅台",
                        "成交价": 1700.0,
                        "成交量": 10000,
                        "成交额": 17000000,
                        "折溢率": -2.5,
                        "买方营业部": "中信证券",
                        "卖方营业部": "华泰证券",
                    }
                ]
            }
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", symbol="600519", exchange="SSE"
        )
        assert result["event_count"] == 1
        evt = result["events"][0]
        assert evt["event_type"] == "block_trade"
        assert evt["price"] == 1700.0
        assert evt["premium_rate"] == -2.5

    @pytest.mark.asyncio
    async def test_multiple_event_types(self):
        from src.server.domain.structured_data.normalize.corporate_actions import (
            CorporateActionsNormalizer,
        )

        normalizer = CorporateActionsNormalizer()
        raw_data = {
            "repurchase": {
                "data": [
                    {
                        "股票代码": "600519",
                        "公司名称": "贵州茅台",
                        "回购期限": "2024",
                        "回购目的": "员工持股",
                        "实施进度": "完成",
                        "回购价格区间": "",
                        "回购数量": 50000,
                        "回购金额": 85000000,
                        "最新公告日期": "2024-03-20",
                    }
                ]
            },
            "restricted_release": {
                "summary": [
                    {
                        "股票代码": "600519",
                        "股票简称": "贵州茅台",
                        "解禁日期": "2024-04-01",
                        "解禁数量": 1000000,
                        "解禁市值": 1700000000,
                        "限售股类型": "首发原股东",
                    }
                ]
            },
            "block_trade": {
                "data": [
                    {
                        "交易日期": "2024-03-25",
                        "证券代码": "600519",
                        "证券简称": "贵州茅台",
                        "成交价": 1695.0,
                        "成交量": 5000,
                        "成交额": 8475000,
                        "折溢率": -1.0,
                        "买方营业部": "A",
                        "卖方营业部": "B",
                    }
                ]
            },
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", symbol="600519", exchange="SSE"
        )
        assert result["event_count"] == 3
        types = {e["event_type"] for e in result["events"]}
        assert types == {"buyback", "restricted_release", "block_trade"}

    @pytest.mark.asyncio
    async def test_empty_data(self):
        from src.server.domain.structured_data.normalize.corporate_actions import (
            CorporateActionsNormalizer,
        )

        normalizer = CorporateActionsNormalizer()
        raw_data = {}
        result = await normalizer.normalize(
            raw_data, source="akshare", symbol="600519", exchange="SSE"
        )
        assert result["events"] == []
        assert result["event_count"] == 0
        assert result["business_key"] == ""

    @pytest.mark.asyncio
    async def test_generic_passthrough(self):
        from src.server.domain.structured_data.normalize.corporate_actions import (
            CorporateActionsNormalizer,
        )

        normalizer = CorporateActionsNormalizer()
        raw_data = {
            "events": [
                {"event_type": "buyback", "event_date": "2024-03-28", "amount": 1000000}
            ]
        }
        result = await normalizer.normalize(
            raw_data, source="generic", symbol="AAPL", exchange="NASDAQ"
        )
        assert result["symbol"] == "AAPL"
        assert result["_source"] == "generic"
        assert result["event_count"] == 1

    @pytest.mark.asyncio
    async def test_symbol_filtering_in_restricted(self):
        from src.server.domain.structured_data.normalize.corporate_actions import (
            CorporateActionsNormalizer,
        )

        normalizer = CorporateActionsNormalizer()
        raw_data = {
            "restricted_release": {
                "summary": [
                    {
                        "股票代码": "000001",
                        "股票简称": "平安银行",
                        "解禁日期": "2024-04-15",
                        "解禁数量": 1000,
                        "解禁市值": 15000,
                        "限售股类型": "定向增发",
                    },
                    {
                        "股票代码": "600519",
                        "股票简称": "贵州茅台",
                        "解禁日期": "2024-04-20",
                        "解禁数量": 2000,
                        "解禁市值": 3400000,
                        "限售股类型": "首发原股东",
                    },
                ]
            }
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", symbol="600519", exchange="SSE"
        )
        # Only 600519 should pass the filter
        assert result["event_count"] == 1
        assert result["events"][0]["event_date"] == "2024-04-20"

    @pytest.mark.asyncio
    async def test_business_key_format(self):
        from src.server.domain.structured_data.normalize.corporate_actions import (
            CorporateActionsNormalizer,
        )

        normalizer = CorporateActionsNormalizer()
        raw_data = {
            "repurchase": {
                "data": [
                    {
                        "股票代码": "600519",
                        "公司名称": "贵州茅台",
                        "回购期限": "2024",
                        "回购目的": "员工持股",
                        "实施进度": "完成",
                        "回购价格区间": "",
                        "回购数量": 50000,
                        "回购金额": 85000000,
                        "最新公告日期": "2024-03-28",
                    }
                ]
            }
        }
        result = await normalizer.normalize(
            raw_data, source="akshare", symbol="600519", exchange="SSE"
        )
        assert result["business_key"] == "SSE:600519:all:2024-03-28"


class TestCorporateActionsValidator:
    """Verify corporate actions validation rules."""

    @pytest.mark.asyncio
    async def test_missing_business_key_triggers_error(self):
        from src.server.domain.structured_data.validate.corporate_actions import (
            register_corporate_actions_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_corporate_actions_rules(engine)

        result = await engine.validate("corporate_actions", "SSE:600519", {})
        assert result.error_count >= 1
        assert any(i.field_path == "business_key" for i in result.issues)

    @pytest.mark.asyncio
    async def test_valid_data_passes(self):
        from src.server.domain.structured_data.validate.corporate_actions import (
            register_corporate_actions_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_corporate_actions_rules(engine)

        data = {
            "business_key": "SSE:600519:all:2024-03-28",
            "events": [
                {
                    "event_type": "buyback",
                    "event_date": "2024-03-28",
                    "amount": 1000000,
                }
            ],
        }
        result = await engine.validate("corporate_actions", "SSE:600519", data)
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_empty_events_warning(self):
        from src.server.domain.structured_data.validate.corporate_actions import (
            register_corporate_actions_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_corporate_actions_rules(engine)

        data = {"business_key": "SSE:600519:all:2024-03-28", "events": []}
        result = await engine.validate("corporate_actions", "SSE:600519", data)
        assert any(i.rule_name == "events_not_empty" for i in result.issues)

    @pytest.mark.asyncio
    async def test_invalid_event_type_warning(self):
        from src.server.domain.structured_data.validate.corporate_actions import (
            register_corporate_actions_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_corporate_actions_rules(engine)

        data = {
            "business_key": "SSE:600519:all:2024-03-28",
            "events": [
                {"event_type": "unknown_type", "event_date": "2024-03-28"}
            ],
        }
        result = await engine.validate("corporate_actions", "SSE:600519", data)
        assert any(i.rule_name == "event_type_valid" for i in result.issues)

    @pytest.mark.asyncio
    async def test_invalid_date_format_error(self):
        from src.server.domain.structured_data.validate.corporate_actions import (
            register_corporate_actions_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_corporate_actions_rules(engine)

        data = {
            "business_key": "SSE:600519:all:2024-03-28",
            "events": [
                {"event_type": "buyback", "event_date": "28/03/2024", "amount": 100}
            ],
        }
        result = await engine.validate("corporate_actions", "SSE:600519", data)
        assert any(i.rule_name == "event_dates_valid" for i in result.issues)

    @pytest.mark.asyncio
    async def test_negative_amount_warning(self):
        from src.server.domain.structured_data.validate.corporate_actions import (
            register_corporate_actions_rules,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine

        engine = ValidationEngine()
        register_corporate_actions_rules(engine)

        data = {
            "business_key": "SSE:600519:all:2024-03-28",
            "events": [
                {"event_type": "buyback", "event_date": "2024-03-28", "amount": -500}
            ],
        }
        result = await engine.validate("corporate_actions", "SSE:600519", data)
        assert any(i.rule_name == "amount_non_negative" for i in result.issues)


class TestCorporateActionsFetcher:
    """Verify corporate_actions_fetcher calls gateway adapter."""

    @pytest.mark.asyncio
    async def test_fetcher_calls_adapter_methods(self):
        from src.server.core.use_cases.structured_data import corporate_actions_fetcher

        mock_repo = AsyncMock()
        mock_repo.get_repurchase_info = AsyncMock(return_value={"data": [{"code": "600519"}]})
        mock_repo.get_restricted_release = AsyncMock(return_value={"data": {"summary": [{"code": "600519"}]}})

        mock_adapter = MagicMock()
        mock_adapter.get_repurchase_info = AsyncMock(return_value={"data": [{"股票代码": "600519"}]})
        mock_adapter.get_restricted_release = AsyncMock(return_value={"data": {"summary": [{"股票代码": "600519"}]}})

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=mock_adapter)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await corporate_actions_fetcher(
                "corporate_actions", "akshare", "SSE:600519"
            )

        assert result is not None
        assert result.get("_source") == "akshare"

    @pytest.mark.asyncio
    async def test_fetcher_returns_none_when_no_adapter(self):
        from src.server.core.use_cases.structured_data import corporate_actions_fetcher

        mock_gateway = MagicMock()
        mock_gateway.get_adapter_by_provider = MagicMock(return_value=None)

        with patch(
            "src.server.core.dependencies.Container"
        ) as mock_container:
            mock_container.market_gateway.return_value = mock_gateway
            result = await corporate_actions_fetcher(
                "corporate_actions", "unknown", "TEST:X"
            )

        assert result is None


class TestCorporateActionsDatasetConfig:
    """Verify corporate_actions is registered in the default registry."""

    def test_dataset_config_exists(self):
        from src.server.domain.structured_data.registry import build_default_registry

        registry = build_default_registry()
        config = registry.require("corporate_actions")
        assert config.dataset_key == "corporate_actions"
        assert config.primary_key_template == "{exchange}:{symbol}:{event_type}:{event_date}"

    def test_normalizer_dataset_key(self):
        from src.server.domain.structured_data.normalize.corporate_actions import (
            CorporateActionsNormalizer,
        )

        n = CorporateActionsNormalizer()
        assert n.dataset_key == "corporate_actions"
