# src/server/domain/structured_data/validate/company_profile.py
"""Validation rules for company profile data.

Checks:
- Required fields present (short_name, industry)
- Listing date format validity
- Share count reasonableness
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .common_rules import NotNullRule, NotEmptyStringRule, PositiveNumberRule
from .engine import ValidationEngine, ValidationIssue


def register_company_profile_rules(engine: ValidationEngine) -> None:
    """Register all company profile validation rules.

    Call once during bootstrap to set up the validation engine.
    """
    dk = "company_profile"

    # --- Required fields ---
    engine.register(dk, NotNullRule("business_key", "ERROR"))
    engine.register(dk, NotEmptyStringRule("business_key", "ERROR"))
    engine.register(dk, NotNullRule("short_name", "ERROR"))
    engine.register(dk, NotEmptyStringRule("short_name", "ERROR"))
    engine.register(dk, NotNullRule("industry", "WARNING"))

    # --- Listing date format ---
    engine.register(dk, _ListingDateValidRule())

    # --- Share count reasonableness ---
    engine.register(dk, PositiveNumberRule("total_shares", "WARNING"))
    engine.register(dk, PositiveNumberRule("float_shares", "WARNING"))

    # --- Cross-field: float_shares <= total_shares ---
    engine.register(dk, _FloatNotExceedTotalRule())


class _ListingDateValidRule:
    """Check that listing_date is a valid date string (YYYY-MM-DD or YYYYMMDD)."""

    @property
    def name(self) -> str:
        return "listing_date_valid"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        ld = data.get("listing_date")
        if ld is None:
            return None
        s = str(ld).strip()
        if not s:
            return None
        # Accept YYYY-MM-DD or YYYYMMDD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s) or re.match(r"^\d{8}$", s):
            return None
        return ValidationIssue(
            rule_name=self.name,
            severity=self.severity,
            field_path="listing_date",
            expected_value="YYYY-MM-DD or YYYYMMDD",
            actual_value=s,
            message=f"listing_date '{s}' is not a valid date format",
        )


class _FloatNotExceedTotalRule:
    """Check that float_shares <= total_shares."""

    @property
    def name(self) -> str:
        return "float_not_exceed_total"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        total = data.get("total_shares")
        float_val = data.get("float_shares")
        if total is None or float_val is None:
            return None
        try:
            t = float(total)
            f = float(float_val)
        except (TypeError, ValueError):
            return None
        if f > t and t > 0:
            return ValidationIssue(
                rule_name=self.name,
                severity=self.severity,
                field_path="float_shares vs total_shares",
                expected_value="float_shares <= total_shares",
                actual_value=f"float={f}, total={t}",
                message=f"float_shares ({f}) exceeds total_shares ({t})",
            )
        return None
