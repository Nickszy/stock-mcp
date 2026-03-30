# src/server/domain/structured_data/validate/daily_market_data.py
"""Validation rules for daily market data (日频市场数据).

Checks:
- Required fields present (business_key, rows)
- OHLC relationship: open/high/low/close within valid range
- Volume is non-negative
- No zero close price
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .common_rules import NotEmptyStringRule, NotNullRule
from .engine import ValidationEngine, ValidationIssue


def register_daily_market_data_rules(engine: ValidationEngine) -> None:
    """Register all daily market data validation rules."""
    dk = "daily_market_data"

    engine.register(dk, NotNullRule("business_key", "ERROR"))
    engine.register(dk, NotEmptyStringRule("business_key", "ERROR"))
    engine.register(dk, NotNullRule("rows", "ERROR"))

    engine.register(dk, _RowsNonEmptyRule())
    engine.register(dk, _OhlcConsistentRule())
    engine.register(dk, _VolumeNonNegativeRule())
    engine.register(dk, _CloseNotZeroRule())


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
                message="Daily market data rows list is empty",
            )
        return None


class _OhlcConsistentRule:
    """Check OHLC consistency: high >= low, high >= open/close, low <= open/close."""

    @property
    def name(self) -> str:
        return "ohlc_consistent"

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
            o = row.get("open")
            h = row.get("high")
            l = row.get("low")
            c = row.get("close")
            if any(v is None for v in (o, h, l, c)):
                continue
            try:
                o, h, l, c = float(o), float(h), float(l), float(c)
            except (TypeError, ValueError):
                continue
            if h < l:
                return ValidationIssue(
                    rule_name=self.name,
                    severity=self.severity,
                    field_path=f"rows[{i}].high vs rows[{i}].low",
                    expected_value="high >= low",
                    actual_value=f"high={h}, low={l}",
                    message=f"Row {i} high ({h}) < low ({l})",
                )
            if h < max(o, c):
                return ValidationIssue(
                    rule_name=self.name,
                    severity=self.severity,
                    field_path=f"rows[{i}].high",
                    expected_value="high >= max(open, close)",
                    actual_value=f"high={h}, open={o}, close={c}",
                    message=f"Row {i} high ({h}) < open/close max ({max(o, c)})",
                )
            if l > min(o, c):
                return ValidationIssue(
                    rule_name=self.name,
                    severity=self.severity,
                    field_path=f"rows[{i}].low",
                    expected_value="low <= min(open, close)",
                    actual_value=f"low={l}, open={o}, close={c}",
                    message=f"Row {i} low ({l}) > open/close min ({min(o, c)})",
                )
        return None


class _VolumeNonNegativeRule:
    """Check that volume is non-negative in all rows."""

    @property
    def name(self) -> str:
        return "volume_non_negative"

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
            vol = row.get("volume")
            if vol is None:
                continue
            try:
                v = float(vol)
                if v < 0:
                    return ValidationIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        field_path=f"rows[{i}].volume",
                        expected_value=">=0",
                        actual_value=str(v),
                        message=f"Row {i} volume is negative: {v}",
                    )
            except (TypeError, ValueError):
                pass
        return None


class _CloseNotZeroRule:
    """Check that close price is not zero in any row."""

    @property
    def name(self) -> str:
        return "close_not_zero"

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
            c = row.get("close")
            if c is None:
                continue
            try:
                if float(c) == 0:
                    return ValidationIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        field_path=f"rows[{i}].close",
                        expected_value="!=0",
                        actual_value="0",
                        message=f"Row {i} close price is zero",
                    )
            except (TypeError, ValueError):
                pass
        return None
