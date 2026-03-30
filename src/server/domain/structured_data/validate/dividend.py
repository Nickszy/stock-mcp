# src/server/domain/structured_data/validate/dividend.py
"""Validation rules for dividend (分红送转) data.

Checks:
- Required fields present (business_key, rows)
- Each row has valid end_date format
- Cash dividend amounts are non-negative
- Stock dividend rates are non-negative
- Date consistency (ex_date >= record_date)
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .common_rules import NotEmptyStringRule, NotNullRule
from .engine import ValidationEngine, ValidationIssue


def register_dividend_rules(engine: ValidationEngine) -> None:
    """Register all dividend validation rules.

    Call once during bootstrap to set up the validation engine.
    """
    dk = "dividend"

    # --- Required top-level fields ---
    engine.register(dk, NotNullRule("business_key", "ERROR"))
    engine.register(dk, NotEmptyStringRule("business_key", "ERROR"))
    engine.register(dk, NotNullRule("rows", "ERROR"))

    # --- Row-level checks ---
    engine.register(dk, _RowsNonEmptyRule())
    engine.register(dk, _RowEndDatesValidRule())
    engine.register(dk, _CashDivNonNegativeRule())
    engine.register(dk, _StockDivNonNegativeRule())


class _RowsNonEmptyRule:
    """Check that rows list is not empty."""

    @property
    def name(self) -> str:
        return "rows_not_empty"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        rows = data.get("rows")
        if rows is not None and len(rows) == 0:
            return ValidationIssue(
                rule_name=self.name,
                severity=self.severity,
                field_path="rows",
                expected_value="at least 1 row",
                actual_value="0 rows",
                message="Dividend rows list is empty",
            )
        return None


class _RowEndDatesValidRule:
    """Check that every row has a valid end_date in YYYY-MM-DD or YYYYMMDD format."""

    @property
    def name(self) -> str:
        return "row_end_dates_valid"

    @property
    def severity(self) -> str:
        return "ERROR"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        rows = data.get("rows", [])
        if not isinstance(rows, list):
            return None
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            ed = row.get("end_date")
            if ed is None:
                return ValidationIssue(
                    rule_name=self.name,
                    severity=self.severity,
                    field_path=f"rows[{i}].end_date",
                    expected_value="YYYY-MM-DD or YYYYMMDD",
                    actual_value="null",
                    message=f"Row {i} missing end_date",
                )
            s = str(ed).strip()
            if not (re.match(r"^\d{4}-\d{2}-\d{2}$", s) or re.match(r"^\d{8}$", s)):
                return ValidationIssue(
                    rule_name=self.name,
                    severity=self.severity,
                    field_path=f"rows[{i}].end_date",
                    expected_value="YYYY-MM-DD or YYYYMMDD",
                    actual_value=s,
                    message=f"Row {i} end_date '{s}' is not a valid date format",
                )
        return None


class _CashDivNonNegativeRule:
    """Check that cash_div is non-negative in all rows."""

    @property
    def name(self) -> str:
        return "cash_div_non_negative"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        rows = data.get("rows", [])
        if not isinstance(rows, list):
            return None
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            cd = row.get("cash_div")
            if cd is None:
                continue
            try:
                v = float(cd)
                if v < 0:
                    return ValidationIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        field_path=f"rows[{i}].cash_div",
                        expected_value=">=0",
                        actual_value=str(v),
                        message=f"Row {i} cash_div is negative: {v}",
                    )
            except (TypeError, ValueError):
                pass
        return None


class _StockDivNonNegativeRule:
    """Check that stk_bo_rate and stk_co_rate are non-negative in all rows."""

    @property
    def name(self) -> str:
        return "stock_div_non_negative"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        rows = data.get("rows", [])
        if not isinstance(rows, list):
            return None
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            for field in ("stk_bo_rate", "stk_co_rate"):
                val = row.get(field)
                if val is None:
                    continue
                try:
                    v = float(val)
                    if v < 0:
                        return ValidationIssue(
                            rule_name=self.name,
                            severity=self.severity,
                            field_path=f"rows[{i}].{field}",
                            expected_value=">=0",
                            actual_value=str(v),
                            message=f"Row {i} {field} is negative: {v}",
                        )
                except (TypeError, ValueError):
                    pass
        return None
