# tests/test_structured_data_engines.py
"""Tests for COL-224: normalize, compare, and validate engines."""

import asyncio
import math
import pytest
import sys

sys.path.insert(0, "src")

from server.domain.structured_data.normalize.engine import (
    FieldMapping,
    IdentityNormalizer,
    MISSING,
    Normalizer,
)
from server.domain.structured_data.compare.engine import (
    ComparisonEngine,
    ComparisonResult,
    FieldDiff,
    ToleranceConfig,
)
from server.domain.structured_data.validate.engine import (
    ValidationEngine,
    ValidationIssue,
    ValidationResult,
    ValidationRule,
)
from server.domain.structured_data.validate.common_rules import (
    AllowedValuesRule,
    FieldComparisonRule,
    FieldTypeRule,
    NotEmptyStringRule,
    NotNullRule,
    PositiveNumberRule,
    RangeRule,
)


# ============================================================
# Normalize Engine Tests
# ============================================================


class TestFieldMapping:
    def test_basic_mapping(self):
        mapping = FieldMapping([
            ("源收入", "revenue", float, MISSING),
            ("源净利", "net_income", float, MISSING),
        ])
        result = mapping.apply({"源收入": "1000000", "源净利": 500000})
        assert result["revenue"] == 1000000.0
        assert result["net_income"] == 500000.0

    def test_optional_with_default(self):
        mapping = FieldMapping([
            ("required_field", "req", str, MISSING),
            ("optional_field", "opt", float, 0.0),
        ])
        result = mapping.apply({"required_field": "hello"})
        assert result["req"] == "hello"
        assert result["opt"] == 0.0

    def test_missing_required_skipped(self):
        mapping = FieldMapping([
            ("missing_field", "target", str, MISSING),
        ])
        result = mapping.apply({"other": "data"})
        assert "target" not in result

    def test_type_coercion(self):
        mapping = FieldMapping([
            ("val", "val", float, MISSING),
        ])
        assert mapping.apply({"val": "3.14"})["val"] == 3.14
        assert mapping.apply({"val": 42})["val"] == 42.0
        assert mapping.apply({"val": 0})["val"] == 0.0

    def test_int_from_float_string(self):
        mapping = FieldMapping([("val", "val", int, MISSING)])
        assert mapping.apply({"val": "123.0"})["val"] == 123

    def test_failed_coercion_returns_original(self):
        mapping = FieldMapping([("val", "val", float, MISSING)])
        result = mapping.apply({"val": "not_a_number"})
        assert result["val"] == "not_a_number"


class TestIdentityNormalizer:
    @pytest.mark.asyncio
    async def test_passthrough(self):
        normalizer = IdentityNormalizer("test")
        raw = {"symbol": "600519", "revenue": 1000000}
        result = await normalizer.normalize(raw, source="akshare")
        assert result["symbol"] == "600519"
        assert result["revenue"] == 1000000
        assert result["_source"] == "akshare"
        assert "business_key" in result

    @pytest.mark.asyncio
    async def test_batch(self):
        normalizer = IdentityNormalizer("test")
        items = [{"a": 1}, {"b": 2}]
        results = await normalizer.normalize_batch(items, source="test")
        assert len(results) == 2


# ============================================================
# Comparison Engine Tests
# ============================================================


class TestComparisonEngine:
    def test_perfect_match(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [
            {"source": "a", "revenue": 1000000, "name": "Test"},
            {"source": "b", "revenue": 1000000, "name": "Test"},
        ])
        assert r.confidence_score == 1.0
        assert r.conflict_count == 0
        assert len(r.agreed_fields) == 2
        assert len(r.field_diffs) == 2

    def test_near_match_within_tolerance(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [
            {"source": "a", "revenue": 1000000},
            {"source": "b", "revenue": 1000500},  # 0.05% diff < 1% tolerance
        ])
        assert r.confidence_score == 1.0
        assert r.conflict_count == 0

    def test_conflict_beyond_tolerance(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [
            {"source": "a", "revenue": 1000000},
            {"source": "b", "revenue": 500000},  # 50% diff >> 1% tolerance
        ])
        assert r.conflict_count == 1
        assert "revenue" in r.conflict_fields
        assert r.confidence_score < 0.5

    def test_custom_tolerance(self):
        tol = ToleranceConfig(numeric_relative_tol=0.5)  # 50% tolerance
        engine = ComparisonEngine(tol)
        r = engine.compare("bk", "ds", [
            {"source": "a", "revenue": 100},
            {"source": "b", "revenue": 140},  # 40% diff < 50% tolerance
        ])
        assert r.conflict_count == 0

    def test_per_field_tolerance_override(self):
        tol = ToleranceConfig(
            numeric_relative_tol=0.01,
            field_tolerances={"revenue": 0.5},  # 50% for revenue
        )
        engine = ComparisonEngine(tol)
        r = engine.compare("bk", "ds", [
            {"source": "a", "revenue": 100, "eps": 3.5},
            {"source": "b", "revenue": 130, "eps": 3.7},  # revenue OK, eps conflict
        ])
        assert "revenue" not in r.conflict_fields
        assert "eps" in r.conflict_fields

    def test_single_source(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [
            {"source": "akshare", "revenue": 100},
        ])
        assert r.confidence_score == 0.7  # moderate for single source
        assert r.conflict_count == 0

    def test_empty_candidates(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [])
        assert r.confidence_score == 0.0
        assert len(r.sources_compared) == 0

    def test_string_case_insensitive(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [
            {"source": "a", "name": "Kweichow Moutai"},
            {"source": "b", "name": "kweichow moutai"},
        ])
        assert r.conflict_count == 0

    def test_string_case_sensitive(self):
        tol = ToleranceConfig(string_case_sensitive=True)
        engine = ComparisonEngine(tol)
        r = engine.compare("bk", "ds", [
            {"source": "a", "name": "Kweichow Moutai"},
            {"source": "b", "name": "kweichow moutai"},
        ])
        assert r.conflict_count == 1

    def test_ignore_fields(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [
            {"source": "a", "revenue": 100, "_source": "a", "fetched_at": "2024-01-01"},
            {"source": "b", "revenue": 100, "_source": "b", "fetched_at": "2024-01-02"},
        ])
        assert r.conflict_count == 0  # _source and fetched_at ignored

    def test_three_sources(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [
            {"source": "a", "revenue": 1000000},
            {"source": "b", "revenue": 1001000},
            {"source": "c", "revenue": 999000},
        ])
        assert r.conflict_count == 0
        assert len(r.sources_compared) == 3

    def test_nan_values_equal(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [
            {"source": "a", "value": float("nan")},
            {"source": "b", "value": float("nan")},
        ])
        # NaN == NaN in our comparison
        assert r.conflict_count == 0

    def test_none_values_equal(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [
            {"source": "a", "value": None},
            {"source": "b", "value": None},
        ])
        assert r.conflict_count == 0

    def test_has_conflicts_property(self):
        engine = ComparisonEngine()
        r = engine.compare("bk", "ds", [
            {"source": "a", "revenue": 100},
            {"source": "b", "revenue": 500},
        ])
        assert r.has_conflicts is True

        r2 = engine.compare("bk", "ds", [
            {"source": "a", "revenue": 100},
            {"source": "b", "revenue": 100},
        ])
        assert r2.has_conflicts is False


# ============================================================
# Validation Engine Tests
# ============================================================


class TestValidationEngine:
    @pytest.mark.asyncio
    async def test_no_rules_auto_pass(self):
        engine = ValidationEngine()
        result = await engine.validate("test", "bk", {"revenue": 100})
        assert result.passed is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_not_null_pass(self):
        engine = ValidationEngine()
        engine.register("test", NotNullRule("symbol", "ERROR"))
        result = await engine.validate("test", "bk", {"symbol": "600519"})
        assert result.passed is True
        assert result.error_count == 0

    @pytest.mark.asyncio
    async def test_not_null_fail(self):
        engine = ValidationEngine()
        engine.register("test", NotNullRule("symbol", "ERROR"))
        result = await engine.validate("test", "bk", {"symbol": None})
        assert result.passed is False
        assert result.error_count == 1

    @pytest.mark.asyncio
    async def test_not_empty_string(self):
        engine = ValidationEngine()
        engine.register("test", NotEmptyStringRule("name", "ERROR"))
        r1 = await engine.validate("test", "bk", {"name": "茅台"})
        assert r1.passed is True
        r2 = await engine.validate("test", "bk", {"name": "  "})
        assert r2.passed is False

    @pytest.mark.asyncio
    async def test_field_type(self):
        engine = ValidationEngine()
        engine.register("test", FieldTypeRule("revenue", float, "WARNING"))
        r1 = await engine.validate("test", "bk", {"revenue": 1000000.0})
        assert r1.passed is True
        r2 = await engine.validate("test", "bk", {"revenue": "not_a_number"})
        assert r2.warning_count == 1
        # int should pass for float fields
        r3 = await engine.validate("test", "bk", {"revenue": 1000000})
        assert r3.warning_count == 0

    @pytest.mark.asyncio
    async def test_range_rule(self):
        engine = ValidationEngine()
        engine.register("test", RangeRule("pe_ratio", 0, 1000, "WARNING"))
        r1 = await engine.validate("test", "bk", {"pe_ratio": 35.5})
        assert r1.passed is True
        r2 = await engine.validate("test", "bk", {"pe_ratio": 5000})
        assert r2.warning_count == 1
        r3 = await engine.validate("test", "bk", {"pe_ratio": -10})
        assert r3.warning_count == 1

    @pytest.mark.asyncio
    async def test_positive_number(self):
        engine = ValidationEngine()
        engine.register("test", PositiveNumberRule("revenue", "WARNING"))
        r1 = await engine.validate("test", "bk", {"revenue": 100})
        assert r1.warning_count == 0
        r2 = await engine.validate("test", "bk", {"revenue": 0})
        assert r2.warning_count == 1
        r3 = await engine.validate("test", "bk", {"revenue": -50})
        assert r3.warning_count == 1

    @pytest.mark.asyncio
    async def test_field_comparison(self):
        engine = ValidationEngine()
        engine.register("test", FieldComparisonRule("revenue", "cost", ">=", "WARNING"))
        r1 = await engine.validate("test", "bk", {"revenue": 100, "cost": 80})
        assert r1.warning_count == 0
        r2 = await engine.validate("test", "bk", {"revenue": 50, "cost": 80})
        assert r2.warning_count == 1

    @pytest.mark.asyncio
    async def test_allowed_values(self):
        engine = ValidationEngine()
        engine.register("test", AllowedValuesRule(
            "type", {"income_statement", "balance_sheet", "cash_flow"}, "ERROR",
        ))
        r1 = await engine.validate("test", "bk", {"type": "income_statement"})
        assert r1.passed is True
        r2 = await engine.validate("test", "bk", {"type": "unknown"})
        assert r2.passed is False

    @pytest.mark.asyncio
    async def test_multiple_rules_mixed_severity(self):
        engine = ValidationEngine()
        engine.register_many("test", [
            NotNullRule("symbol", "ERROR"),
            RangeRule("pe", 0, 1000, "WARNING"),
            PositiveNumberRule("revenue", "WARNING"),
        ])
        result = await engine.validate("test", "bk", {
            "symbol": None,  # ERROR
            "pe": 5000,       # WARNING
            "revenue": 100,   # OK
        })
        assert result.passed is False
        assert result.error_count == 1
        assert result.warning_count == 1

    @pytest.mark.asyncio
    async def test_score_calculation(self):
        engine = ValidationEngine()
        engine.register_many("test", [
            NotNullRule("a", "ERROR"),
            NotNullRule("b", "ERROR"),
            RangeRule("c", 0, 100, "WARNING"),
        ])
        # All pass
        r1 = await engine.validate("test", "bk", {"a": 1, "b": 2, "c": 50})
        assert r1.score == 1.0
        # One error
        r2 = await engine.validate("test", "bk", {"a": None, "b": 2, "c": 50})
        assert r2.score < 1.0

    @pytest.mark.asyncio
    async def test_null_values_ok_for_optional(self):
        """Rules that check values should treat None as OK (field absent)."""
        engine = ValidationEngine()
        engine.register_many("test", [
            PositiveNumberRule("revenue", "WARNING"),
            RangeRule("pe", 0, 100, "WARNING"),
        ])
        r = await engine.validate("test", "bk", {"revenue": None, "pe": None})
        assert r.passed is True
        assert r.warning_count == 0
