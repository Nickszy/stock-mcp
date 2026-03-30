# src/server/domain/structured_data/validate/corporate_actions.py
"""Validation rules for corporate actions (公司结构化事件) data.

Checks:
- Required fields present (business_key, events)
- Event type is a recognized value
- Event dates are valid
- Amounts are non-negative where applicable
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .common_rules import NotEmptyStringRule, NotNullRule
from .engine import ValidationEngine, ValidationIssue

# Recognized event types
_VALID_EVENT_TYPES = {
    "buyback",
    "restricted_release",
    "block_trade",
    "insider_trade",
    "suspension",
    "resume",
    "rights_issue",
    "stock_split",
    "all",
}


def register_corporate_actions_rules(engine: ValidationEngine) -> None:
    """Register all corporate actions validation rules."""
    dk = "corporate_actions"

    engine.register(dk, NotNullRule("business_key", "ERROR"))
    engine.register(dk, NotEmptyStringRule("business_key", "ERROR"))
    engine.register(dk, NotNullRule("events", "ERROR"))

    engine.register(dk, _EventsNonEmptyRule())
    engine.register(dk, _EventTypeValidRule())
    engine.register(dk, _EventDatesValidRule())
    engine.register(dk, _AmountNonNegativeRule())


class _EventsNonEmptyRule:
    """Check that events list is not empty."""

    @property
    def name(self) -> str:
        return "events_not_empty"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        events = data.get("events")
        if events is not None and len(events) == 0:
            return ValidationIssue(
                rule_name=self.name,
                severity=self.severity,
                field_path="events",
                expected_value="at least 1 event",
                actual_value="0 events",
                message="Corporate actions events list is empty",
            )
        return None


class _EventTypeValidRule:
    """Check that event_type field values are recognized."""

    @property
    def name(self) -> str:
        return "event_type_valid"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        events = data.get("events", [])
        if not isinstance(events, list):
            return None
        for i, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            evt_type = event.get("event_type", "")
            if evt_type and evt_type not in _VALID_EVENT_TYPES:
                return ValidationIssue(
                    rule_name=self.name,
                    severity=self.severity,
                    field_path=f"events[{i}].event_type",
                    expected_value=f"one of {sorted(_VALID_EVENT_TYPES)}",
                    actual_value=str(evt_type),
                    message=f"Event {i} has unrecognized type: {evt_type}",
                )
        return None


class _EventDatesValidRule:
    """Check that event_date values look like valid dates."""

    @property
    def name(self) -> str:
        return "event_dates_valid"

    @property
    def severity(self) -> str:
        return "ERROR"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        events = data.get("events", [])
        if not isinstance(events, list):
            return None
        for i, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            evt_date = event.get("event_date", "")
            if not evt_date:
                continue
            # Validate YYYY-MM-DD format
            s = str(evt_date)
            if len(s) != 10 or s[4] != "-" or s[7] != "-":
                return ValidationIssue(
                    rule_name=self.name,
                    severity=self.severity,
                    field_path=f"events[{i}].event_date",
                    expected_value="YYYY-MM-DD",
                    actual_value=str(evt_date),
                    message=f"Event {i} has invalid date format: {evt_date}",
                )
            # Check date parts are numeric
            parts = s.split("-")
            try:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                if not (2000 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31):
                    raise ValueError
            except (ValueError, IndexError):
                return ValidationIssue(
                    rule_name=self.name,
                    severity=self.severity,
                    field_path=f"events[{i}].event_date",
                    expected_value="valid YYYY-MM-DD",
                    actual_value=str(evt_date),
                    message=f"Event {i} has invalid date: {evt_date}",
                )
        return None


class _AmountNonNegativeRule:
    """Check that amounts are non-negative in events."""

    @property
    def name(self) -> str:
        return "amount_non_negative"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        events = data.get("events", [])
        if not isinstance(events, list):
            return None
        for i, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            amount = event.get("amount")
            if amount is None:
                continue
            try:
                v = float(amount)
                if v < 0:
                    return ValidationIssue(
                        rule_name=self.name,
                        severity=self.severity,
                        field_path=f"events[{i}].amount",
                        expected_value=">=0",
                        actual_value=str(v),
                        message=f"Event {i} amount is negative: {v}",
                    )
            except (TypeError, ValueError):
                pass
        return None
