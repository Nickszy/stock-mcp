# src/server/domain/structured_data/validate/common_rules.py
"""Common validation rules shared across data dimensions.

These rules are reusable building blocks. Dimension-specific rules should
be placed in their own files (e.g. financial_statements.py).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Set

from .engine import ValidationIssue, ValidationRule


# ---------------------------------------------------------------------------
# Type checking rules
# ---------------------------------------------------------------------------

class FieldTypeRule(ValidationRule):
    """Check that a field is of the expected type."""

    def __init__(
        self,
        field_name: str,
        expected_type: type,
        severity: str = "ERROR",
    ):
        self._field_name = field_name
        self._expected_type = expected_type
        self._severity = severity

    @property
    def name(self) -> str:
        return f"field_type:{self._field_name}"

    @property
    def severity(self) -> str:
        return self._severity

    async def check(
        self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        value = data.get(self._field_name)
        if value is None:
            return None  # Null is OK — use NotNullRule for required checks
        if not isinstance(value, self._expected_type):
            # Allow int for float fields
            if self._expected_type is float and isinstance(value, int):
                return None
            return ValidationIssue(
                rule_name=self.name,
                severity=self._severity,
                field_path=self._field_name,
                expected_value=self._expected_type.__name__,
                actual_value=type(value).__name__,
                message=f"Field '{self._field_name}' expected {self._expected_type.__name__}, got {type(value).__name__}",
            )
        return None


class NotNullRule(ValidationRule):
    """Check that a field is not null/None."""

    def __init__(self, field_name: str, severity: str = "ERROR"):
        self._field_name = field_name
        self._severity = severity

    @property
    def name(self) -> str:
        return f"not_null:{self._field_name}"

    @property
    def severity(self) -> str:
        return self._severity

    async def check(
        self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        value = data.get(self._field_name)
        if value is None:
            return ValidationIssue(
                rule_name=self.name,
                severity=self._severity,
                field_path=self._field_name,
                expected_value="non-null",
                actual_value="null",
                message=f"Required field '{self._field_name}' is null",
            )
        return None


class NotEmptyStringRule(ValidationRule):
    """Check that a string field is not empty."""

    def __init__(self, field_name: str, severity: str = "ERROR"):
        self._field_name = field_name
        self._severity = severity

    @property
    def name(self) -> str:
        return f"not_empty:{self._field_name}"

    @property
    def severity(self) -> str:
        return self._severity

    async def check(
        self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        value = data.get(self._field_name)
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return ValidationIssue(
                rule_name=self.name,
                severity=self._severity,
                field_path=self._field_name,
                message=f"String field '{self._field_name}' is empty",
            )
        return None


# ---------------------------------------------------------------------------
# Range rules
# ---------------------------------------------------------------------------

class RangeRule(ValidationRule):
    """Check that a numeric field falls within a range."""

    def __init__(
        self,
        field_name: str,
        min_val: Optional[float] = None,
        max_val: Optional[float] = None,
        severity: str = "WARNING",
    ):
        self._field_name = field_name
        self._min_val = min_val
        self._max_val = max_val
        self._severity = severity

    @property
    def name(self) -> str:
        return f"range:{self._field_name}"

    @property
    def severity(self) -> str:
        return self._severity

    async def check(
        self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        value = data.get(self._field_name)
        if value is None:
            return None

        try:
            num = float(value)
            if math.isnan(num) or math.isinf(num):
                return ValidationIssue(
                    rule_name=self.name,
                    severity=self._severity,
                    field_path=self._field_name,
                    actual_value=str(value),
                    message=f"Field '{self._field_name}' is NaN/Inf",
                )
        except (TypeError, ValueError):
            return None  # Non-numeric — let FieldTypeRule handle it

        if self._min_val is not None and num < self._min_val:
            return ValidationIssue(
                rule_name=self.name,
                severity=self._severity,
                field_path=self._field_name,
                expected_value=f">={self._min_val}",
                actual_value=str(num),
                message=f"Field '{self._field_name}' value {num} below minimum {self._min_val}",
            )

        if self._max_val is not None and num > self._max_val:
            return ValidationIssue(
                rule_name=self.name,
                severity=self._severity,
                field_path=self._field_name,
                expected_value=f"<={self._max_val}",
                actual_value=str(num),
                message=f"Field '{self._field_name}' value {num} above maximum {self._max_val}",
            )

        return None


class PositiveNumberRule(ValidationRule):
    """Check that a numeric field is positive (> 0)."""

    def __init__(self, field_name: str, severity: str = "WARNING"):
        self._field_name = field_name
        self._severity = severity

    @property
    def name(self) -> str:
        return f"positive:{self._field_name}"

    @property
    def severity(self) -> str:
        return self._severity

    async def check(
        self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        value = data.get(self._field_name)
        if value is None:
            return None
        try:
            num = float(value)
            if num <= 0:
                return ValidationIssue(
                    rule_name=self.name,
                    severity=self._severity,
                    field_path=self._field_name,
                    expected_value=">0",
                    actual_value=str(num),
                    message=f"Field '{self._field_name}' should be positive, got {num}",
                )
        except (TypeError, ValueError):
            pass
        return None


# ---------------------------------------------------------------------------
# Cross-field rules
# ---------------------------------------------------------------------------

class FieldComparisonRule(ValidationRule):
    """Check that field_a has a logical relationship to field_b.

    E.g. revenue >= net_income, total_assets >= total_liabilities.
    """

    def __init__(
        self,
        field_a: str,
        field_b: str,
        relation: str = ">=",  # ">=", ">", "<=", "<", "=="
        severity: str = "WARNING",
        label: str = "",
    ):
        self._field_a = field_a
        self._field_b = field_b
        self._relation = relation
        self._severity = severity
        self._label = label or f"{field_a} {relation} {field_b}"

    @property
    def name(self) -> str:
        return f"compare:{self._field_a}_{self._relation}_{self._field_b}"

    @property
    def severity(self) -> str:
        return self._severity

    async def check(
        self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        a_val = data.get(self._field_a)
        b_val = data.get(self._field_b)
        if a_val is None or b_val is None:
            return None

        try:
            a_num = float(a_val)
            b_num = float(b_val)
        except (TypeError, ValueError):
            return None

        ops = {
            ">=": lambda a, b: a >= b,
            ">": lambda a, b: a > b,
            "<=": lambda a, b: a <= b,
            "<": lambda a, b: a < b,
            "==": lambda a, b: abs(a - b) < 1e-10,
        }

        op = ops.get(self._relation)
        if op is None:
            return None

        if not op(a_num, b_num):
            return ValidationIssue(
                rule_name=self.name,
                severity=self._severity,
                field_path=f"{self._field_a} vs {self._field_b}",
                expected_value=self._label,
                actual_value=f"{self._field_a}={a_num}, {self._field_b}={b_num}",
                message=f"Cross-field check failed: {self._label} (got {a_num} vs {b_num})",
            )
        return None


class AllowedValuesRule(ValidationRule):
    """Check that a field's value is in an allowed set."""

    def __init__(
        self,
        field_name: str,
        allowed: Set[str],
        severity: str = "ERROR",
    ):
        self._field_name = field_name
        self._allowed = allowed
        self._severity = severity

    @property
    def name(self) -> str:
        return f"allowed_values:{self._field_name}"

    @property
    def severity(self) -> str:
        return self._severity

    async def check(
        self, data: Dict[str, Any], context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        value = data.get(self._field_name)
        if value is None:
            return None
        if str(value) not in self._allowed:
            return ValidationIssue(
                rule_name=self.name,
                severity=self._severity,
                field_path=self._field_name,
                expected_value=f"one of {self._allowed}",
                actual_value=str(value),
                message=f"Field '{self._field_name}' has invalid value '{value}'",
            )
        return None
