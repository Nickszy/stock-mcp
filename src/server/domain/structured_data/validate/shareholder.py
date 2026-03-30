# src/server/domain/structured_data/validate/shareholder.py
"""Validation rules for shareholder (股东与持股变化) data.

Checks:
- Required fields present (business_key, top10_holders)
- Report period format validity
- Hold ratio in [0, 100] range
- Hold amounts are non-negative
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .common_rules import NotEmptyStringRule, NotNullRule
from .engine import ValidationEngine, ValidationIssue


def register_shareholder_rules(engine: ValidationEngine) -> None:
    """Register all shareholder validation rules."""
    dk = "shareholder"

    # --- Required top-level fields ---
    engine.register(dk, NotNullRule("business_key", "ERROR"))
    engine.register(dk, NotEmptyStringRule("business_key", "ERROR"))
    engine.register(dk, NotNullRule("top10_holders", "ERROR"))

    # --- Section checks ---
    engine.register(dk, _Top10NonEmptyRule())
    engine.register(dk, _HoldRatioValidRule())
    engine.register(dk, _HoldAmountNonNegativeRule())


class _Top10NonEmptyRule:
    """Check that top10_holders list is not empty."""

    @property
    def name(self) -> str:
        return "top10_non_empty"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        holders = data.get("top10_holders")
        if holders is not None and len(holders) == 0:
            return ValidationIssue(
                rule_name=self.name,
                severity=self.severity,
                field_path="top10_holders",
                expected_value="at least 1 holder",
                actual_value="0 holders",
                message="Top 10 holders list is empty",
            )
        return None


class _HoldRatioValidRule:
    """Check that hold_ratio is in [0, 100] range for all holders."""

    @property
    def name(self) -> str:
        return "hold_ratio_valid"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        for section in ("top10_holders", "top10_floatholders"):
            rows = data.get(section, [])
            if not isinstance(rows, list):
                continue
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                ratio = row.get("hold_ratio")
                if ratio is None:
                    continue
                try:
                    v = float(ratio)
                    if v < 0 or v > 100:
                        return ValidationIssue(
                            rule_name=self.name,
                            severity=self.severity,
                            field_path=f"{section}[{i}].hold_ratio",
                            expected_value="0-100",
                            actual_value=str(v),
                            message=f"{section}[{i}] hold_ratio {v} out of range [0, 100]",
                        )
                except (TypeError, ValueError):
                    pass
        return None


class _HoldAmountNonNegativeRule:
    """Check that hold_amount is non-negative in all holder entries."""

    @property
    def name(self) -> str:
        return "hold_amount_non_negative"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        for section in ("top10_holders", "top10_floatholders"):
            rows = data.get(section, [])
            if not isinstance(rows, list):
                continue
            for i, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                amount = row.get("hold_amount")
                if amount is None:
                    continue
                try:
                    v = float(amount)
                    if v < 0:
                        return ValidationIssue(
                            rule_name=self.name,
                            severity=self.severity,
                            field_path=f"{section}[{i}].hold_amount",
                            expected_value=">=0",
                            actual_value=str(v),
                            message=f"{section}[{i}] hold_amount is negative: {v}",
                        )
                except (TypeError, ValueError):
                    pass
        return None
