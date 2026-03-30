# src/server/domain/structured_data/validate/index_constituents.py
"""Validation rules for index constituents (指数成分与权重) data.

Checks:
- Required fields present (business_key, index_code, constituents)
- Constituents list is not empty
- Weight sum is within reasonable range
- No duplicate symbols in constituents
- All weights are non-negative
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .common_rules import NotEmptyStringRule, NotNullRule
from .engine import ValidationEngine, ValidationIssue


def register_index_constituents_rules(engine: ValidationEngine) -> None:
    """Register all index constituents validation rules."""
    dk = "index_constituents"

    engine.register(dk, NotNullRule("business_key", "ERROR"))
    engine.register(dk, NotEmptyStringRule("business_key", "ERROR"))
    engine.register(dk, NotNullRule("index_code", "ERROR"))
    engine.register(dk, NotNullRule("constituents", "ERROR"))

    engine.register(dk, _ConstituentsNonEmptyRule())
    engine.register(dk, _NoDuplicateSymbolsRule())
    engine.register(dk, _WeightSumInRangeRule())
    engine.register(dk, _WeightsNonNegativeRule())


class _ConstituentsNonEmptyRule:
    """Check that constituents list is not empty."""

    @property
    def name(self) -> str:
        return "constituents_not_empty"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        constituents = data.get("constituents")
        if constituents is not None and len(constituents) == 0:
            return ValidationIssue(
                rule_name=self.name,
                severity=self.severity,
                field_path="constituents",
                expected_value="at least 1 constituent",
                actual_value="0 constituents",
                message="Index constituents list is empty",
            )
        return None


class _NoDuplicateSymbolsRule:
    """Check that there are no duplicate symbols in constituents."""

    @property
    def name(self) -> str:
        return "no_duplicate_symbols"

    @property
    def severity(self) -> str:
        return "ERROR"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        constituents = data.get("constituents", [])
        if not isinstance(constituents, list):
            return None
        symbols = []
        for c in constituents:
            if isinstance(c, dict):
                sym = c.get("symbol")
                if sym:
                    symbols.append(str(sym))
        if len(symbols) != len(set(symbols)):
            seen = set()
            for s in symbols:
                if s in seen:
                    return ValidationIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        field_path="constituents",
                        expected_value="unique symbols",
                        actual_value=f"duplicate: {s}",
                        message=f"Duplicate symbol found in constituents: {s}",
                    )
                seen.add(s)
        return None


class _WeightSumInRangeRule:
    """Check that the sum of weights is within reasonable range [95, 105]."""

    @property
    def name(self) -> str:
        return "weight_sum_in_range"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        constituents = data.get("constituents", [])
        if not isinstance(constituents, list):
            return None
        weights = []
        for c in constituents:
            if isinstance(c, dict):
                w = c.get("weight")
                if w is not None:
                    try:
                        weights.append(float(w))
                    except (TypeError, ValueError):
                        pass
        if not weights:
            return None
        total = sum(weights)
        if total < 95 or total > 105:
            return ValidationIssue(
                rule_name=self.name,
                severity=self.severity,
                field_path="constituents[*].weight",
                expected_value="95-105%",
                actual_value=f"{total:.2f}%",
                message=f"Weight sum is {total:.2f}%, expected ~100%",
            )
        return None


class _WeightsNonNegativeRule:
    """Check that all weights are non-negative."""

    @property
    def name(self) -> str:
        return "weights_non_negative"

    @property
    def severity(self) -> str:
        return "ERROR"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        constituents = data.get("constituents", [])
        if not isinstance(constituents, list):
            return None
        for i, c in enumerate(constituents):
            if not isinstance(c, dict):
                continue
            w = c.get("weight")
            if w is None:
                continue
            try:
                v = float(w)
                if v < 0:
                    return ValidationIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        field_path=f"constituents[{i}].weight",
                        expected_value=">=0",
                        actual_value=str(v),
                        message=f"Constituent {i} weight is negative: {v}",
                    )
            except (TypeError, ValueError):
                pass
        return None
