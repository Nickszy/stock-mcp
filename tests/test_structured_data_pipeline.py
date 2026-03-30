"""Tests for the financial statements structured data pipeline.

Covers:
- Normalizer: akshare/tushare field mapping
- Validator: balance sheet equation, revenue checks
- Full pipeline: normalize → validate → publish decision
"""

import asyncio
import pytest
from datetime import datetime


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------

class TestFinancialStatementsNormalizer:
    """Test the FinancialStatementsNormalizer."""

    @pytest.fixture
    def normalizer(self):
        from src.server.domain.structured_data.normalize.financial_statements import (
            FinancialStatementsNormalizer,
        )
        return FinancialStatementsNormalizer()

    @pytest.mark.asyncio
    async def test_normalize_structured_akshare(self, normalizer):
        """Test normalizing structured akshare data."""
        raw = {
            "income_statement": [
                {"报告期": "20240930", "营业收入": 1234567890.0, "净利润": 500000000.0,
                 "归属于母公司所有者的净利润": 450000000.0, "营业成本": 600000000.0},
            ],
            "balance_sheet": [
                {"报告期": "20240930", "资产总计": 50000000000.0, "负债合计": 20000000000.0,
                 "所有者权益合计": 30000000000.0},
            ],
            "cash_flow": [
                {"报告期": "20240930", "经营活动产生的现金流量净额": 800000000.0,
                 "投资活动产生的现金流量净额": -200000000.0},
            ],
        }

        result = await normalizer.normalize(raw, source="akshare", symbol="600519", exchange="SSE")

        assert result["business_key"] == "SSE:600519:20240930:all"
        assert result["statement_type"] == "all"
        assert result["source"] == "akshare"

        # Check income statement fields
        income = result["income_statement"]
        assert income["revenue"] == 1234567890.0
        assert income["net_income"] == 500000000.0
        assert income["net_income_attr_p"] == 450000000.0
        assert income["operating_cost"] == 600000000.0

        # Check balance sheet fields
        balance = result["balance_sheet"]
        assert balance["total_assets"] == 50000000000.0
        assert balance["total_liabilities"] == 20000000000.0
        assert balance["total_equity"] == 30000000000.0

        # Check cash flow fields
        cashflow = result["cash_flow"]
        assert cashflow["operating_cash_flow"] == 800000000.0
        assert cashflow["investing_cash_flow"] == -200000000.0

        # Check derived fields
        assert result["derived_gross_margin"] == pytest.approx(51.39, abs=0.1)
        assert result["derived_net_margin"] == pytest.approx(36.46, abs=0.1)
        assert result["derived_debt_ratio"] == pytest.approx(40.0, abs=0.1)

    @pytest.mark.asyncio
    async def test_normalize_flat_row_tushare(self, normalizer):
        """Test normalizing a flat tushare row."""
        raw = {
            "ts_code": "600519.SH",
            "end_date": "20240930",
            "revenue": 1234567890.0,
            "n_income_attr_p": 450000000.0,
            "n_income": 500000000.0,
            "operate_profit": 600000000.0,
            "total_profit": 610000000.0,
            "oper_cost": 600000000.0,
        }

        result = await normalizer.normalize(raw, source="tushare")

        assert "business_key" in result
        assert result["statement_type"] == "income_statement"
        assert result["revenue"] == 1234567890.0
        assert result["net_income"] == 500000000.0
        assert result["net_income_attr_p"] == 450000000.0
        assert result["operating_profit"] == 600000000.0
        assert result["report_period"] == "20240930"
        assert result["source"] == "tushare"

    @pytest.mark.asyncio
    async def test_normalize_balance_sheet_tushare(self, normalizer):
        """Test normalizing tushare balance sheet data."""
        raw = {
            "ts_code": "600519.SH",
            "end_date": "20240930",
            "total_assets": 50000000000.0,
            "total_liab": 20000000000.0,
            "total_hldr_eqy_exc_min_int": 30000000000.0,
            "monetary_cap": 10000000000.0,
        }

        result = await normalizer.normalize(raw, source="tushare")

        assert result["statement_type"] == "balance_sheet"
        assert result["total_assets"] == 50000000000.0
        assert result["total_liabilities"] == 20000000000.0
        assert result["total_equity"] == 30000000000.0
        assert result["monetary_capital"] == 10000000000.0

    @pytest.mark.asyncio
    async def test_normalize_batch(self, normalizer):
        """Test batch normalization."""
        items = [
            {"ts_code": "600519.SH", "end_date": "20240930", "revenue": 100.0, "n_income": 50.0},
            {"ts_code": "000001.SZ", "end_date": "20240930", "revenue": 200.0, "n_income": 80.0},
        ]

        results = await normalizer.normalize_batch(items, source="tushare")
        assert len(results) == 2
        assert results[0]["revenue"] == 100.0
        assert results[1]["revenue"] == 200.0

    @pytest.mark.asyncio
    async def test_empty_data(self, normalizer):
        """Test normalizing empty data."""
        result = await normalizer.normalize({}, source="akshare")
        assert "business_key" in result

    @pytest.mark.asyncio
    async def test_extract_report_period(self, normalizer):
        """Test report period extraction from various formats."""
        from src.server.domain.structured_data.normalize.financial_statements import (
            _extract_report_period,
        )

        assert _extract_report_period({"报告期": "20240930"}, "akshare") == "20240930"
        assert _extract_report_period({"end_date": "2024-09-30"}, "tushare") == "20240930"
        assert _extract_report_period({"end_date": "20240930"}, "tushare") == "20240930"
        assert _extract_report_period({}, "tushare") is None


# ---------------------------------------------------------------------------
# Validator tests
# ---------------------------------------------------------------------------

class TestFinancialStatementsValidator:
    """Test the financial statement validation rules."""

    @pytest.fixture
    def engine(self):
        from src.server.domain.structured_data.validate.engine import ValidationEngine
        from src.server.domain.structured_data.validate.financial_statements import (
            register_financial_statement_rules,
        )
        engine = ValidationEngine()
        register_financial_statement_rules(engine)
        return engine

    @pytest.mark.asyncio
    async def test_valid_data_passes(self, engine):
        """Test that valid financial data passes all rules."""
        data = {
            "revenue": 1234567890.0,
            "net_income": 500000000.0,
            "net_income_attr_p": 450000000.0,
            "total_assets": 50000000000.0,
            "total_liabilities": 20000000000.0,
            "total_equity": 30000000000.0,
            "statement_type": "all",
        }

        result = await engine.validate(
            "financial_statements", "SSE:600519:20240930", data,
        )

        assert result.passed
        assert result.error_count == 0

    @pytest.mark.asyncio
    async def test_missing_revenue_fails(self, engine):
        """Test that missing revenue triggers an error."""
        data = {
            "net_income": 500000000.0,
            "total_assets": 50000000000.0,
            "total_liabilities": 20000000000.0,
        }

        result = await engine.validate(
            "financial_statements", "SSE:600519:20240930", data,
        )

        assert not result.passed
        assert result.error_count > 0
        assert any("revenue" in (i.field_path or "") for i in result.issues)

    @pytest.mark.asyncio
    async def test_unbalanced_balance_sheet(self, engine):
        """Test that unbalanced balance sheet triggers a warning."""
        data = {
            "revenue": 1000000.0,
            "net_income": 500000.0,
            "total_assets": 50000000000.0,
            "total_liabilities": 20000000000.0,
            "total_equity": 5000000000.0,  # assets != liab + equity
            "statement_type": "all",
        }

        result = await engine.validate(
            "financial_statements", "SSE:600519:20240930", data,
        )

        # Should have a warning for balance sheet equation
        assert result.has_warnings
        balance_issues = [
            i for i in result.issues
            if "balance_sheet_balanced" in i.rule_name
        ]
        assert len(balance_issues) == 1

    @pytest.mark.asyncio
    async def test_net_income_unreasonable(self, engine):
        """Test that net income >> revenue triggers a warning."""
        data = {
            "revenue": 1000000.0,
            "net_income": 100000000.0,  # 100x revenue
            "net_income_attr_p": 100000000.0,
            "total_assets": 50000000000.0,
            "total_liabilities": 20000000000.0,
            "total_equity": 30000000000.0,
            "statement_type": "all",
        }

        result = await engine.validate(
            "financial_statements", "SSE:600519:20240930", data,
        )

        assert result.has_warnings
        ni_issues = [
            i for i in result.issues
            if "net_income_reasonable" in i.rule_name
        ]
        assert len(ni_issues) == 1

    @pytest.mark.asyncio
    async def test_negative_revenue_warning(self, engine):
        """Test that negative revenue triggers a warning."""
        data = {
            "revenue": -1000000.0,
            "net_income": -500000.0,
            "total_assets": 50000000000.0,
            "total_liabilities": 20000000000.0,
            "total_equity": 30000000000.0,
            "statement_type": "all",
        }

        result = await engine.validate(
            "financial_statements", "SSE:600519:20240930", data,
        )

        assert result.has_warnings
        revenue_issues = [
            i for i in result.issues
            if "range:revenue" in i.rule_name
        ]
        assert len(revenue_issues) == 1


# ---------------------------------------------------------------------------
# Integration: normalizer + validator
# ---------------------------------------------------------------------------

class TestPipelineIntegration:
    """Test the full normalize → validate pipeline."""

    @pytest.mark.asyncio
    async def test_full_pipeline_akshare(self):
        """Test normalizing and validating akshare data end-to-end."""
        from src.server.domain.structured_data.normalize.financial_statements import (
            FinancialStatementsNormalizer,
        )
        from src.server.domain.structured_data.validate.engine import ValidationEngine
        from src.server.domain.structured_data.validate.financial_statements import (
            register_financial_statement_rules,
        )

        normalizer = FinancialStatementsNormalizer()
        engine = ValidationEngine()
        register_financial_statement_rules(engine)

        raw = {
            "income_statement": [
                {"报告期": "20240930", "营业收入": 120000000000.0,
                 "归属于母公司所有者的净利润": 55000000000.0,
                 "净利润": 56000000000.0, "营业成本": 30000000000.0},
            ],
            "balance_sheet": [
                {"报告期": "20240930", "资产总计": 200000000000.0,
                 "负债合计": 70000000000.0, "所有者权益合计": 130000000000.0},
            ],
            "cash_flow": [
                {"报告期": "20240930", "经营活动产生的现金流量净额": 60000000000.0},
            ],
        }

        # Step 1: Normalize
        normalized = await normalizer.normalize(
            raw, source="akshare", symbol="600519", exchange="SSE",
        )

        assert normalized["business_key"] == "SSE:600519:20240930:all"
        assert normalized["income_statement"]["revenue"] == 120000000000.0
        assert normalized["balance_sheet"]["total_assets"] == 200000000000.0

        # Step 2: Validate
        result = await engine.validate(
            "financial_statements",
            normalized["business_key"],
            normalized,
        )

        # Maotai data should be clean
        assert result.passed
        assert result.score >= 0.8

    @pytest.mark.asyncio
    async def test_validator_adapter_interface(self):
        """Test that the _ValidatorAdapter works with the orchestrator interface."""
        from src.server.core.use_cases.structured_data import _ValidatorAdapter
        from src.server.domain.structured_data.validate.engine import ValidationEngine
        from src.server.domain.structured_data.validate.financial_statements import (
            register_financial_statement_rules,
        )

        engine = ValidationEngine()
        register_financial_statement_rules(engine)
        adapter = _ValidatorAdapter(engine)

        # Good data
        issues = await adapter.validate(
            {"revenue": 100.0, "net_income": 50.0,
             "total_assets": 1000.0, "total_liabilities": 400.0,
             "total_equity": 600.0, "business_key": "test"},
        )
        assert len(issues) == 0

        # Bad data (missing revenue)
        issues = await adapter.validate(
            {"net_income": 50.0, "total_assets": 1000.0, "total_liabilities": 400.0},
        )
        assert len(issues) > 0
        assert any(i["severity"] == "ERROR" for i in issues)
