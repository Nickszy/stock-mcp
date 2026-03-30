# src/server/domain/structured_data/validate/financial_statements.py
"""Validation rules specific to financial statements.

Implements the dimension-specific rules referenced in the dataset registry:
- revenue_positive: revenue should be non-negative
- net_income_reasonable: net income should be within reasonable bounds relative to revenue
- balance_sheet_balanced: total_assets ≈ total_liabilities + total_equity
- field_type_check: key fields should be numeric
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .common_rules import (
    AllowedValuesRule,
    FieldComparisonRule,
    FieldTypeRule,
    NotNullRule,
    RangeRule,
)
from .engine import ValidationEngine

# Tolerance for balance sheet equation check (relative)
BALANCE_SHEET_TOLERANCE = 0.02  # 2% relative tolerance


def _flatten_financial_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten nested financial statement data for rule checking.

    The normalizer produces:
      {"income_statement": {"revenue": 123, ...}, "balance_sheet": {...}, ...}

    This helper merges the sub-dicts into a flat dict so that common rules
    (NotNullRule, FieldTypeRule, RangeRule) can find fields regardless of nesting.
    """
    flat: Dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            # Merge nested statement dict fields into flat
            for k, v in value.items():
                if k not in flat:
                    flat[k] = v
        else:
            flat[key] = value
    return flat


class _NestedAwareRuleWrapper:
    """Wraps a common rule so it checks flattened data.

    The normalizer produces nested data (income_statement.revenue),
    but common rules check flat fields (revenue). This wrapper
    flattens the data before delegating to the inner rule.
    """

    def __init__(self, inner):
        self._inner = inner

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def severity(self) -> str:
        return self._inner.severity

    async def check(self, data: Dict[str, Any], context=None):
        flat = _flatten_financial_data(data)
        return await self._inner.check(flat, context)


def register_financial_statement_rules(engine: ValidationEngine) -> None:
    """Register all financial statement validation rules.

    Call once during bootstrap to set up the validation engine.
    Rules are wrapped with _NestedAwareRuleWrapper so they handle
    both flat and nested data from the normalizer.
    """
    dk = "financial_statements"

    # --- Field type checks ---
    numeric_fields = [
        "revenue", "operating_cost", "gross_profit", "operating_profit",
        "total_profit", "net_income", "net_income_attr_p",
        "total_assets", "total_liabilities", "total_equity",
        "monetary_capital", "inventory", "accounts_receivable",
        "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
    ]
    for field in numeric_fields:
        engine.register(dk, _NestedAwareRuleWrapper(FieldTypeRule(field, float, "WARNING")))

    # --- Not-null checks for critical fields ---
    critical_fields = [
        "revenue", "net_income", "total_assets", "total_liabilities",
    ]
    for field in critical_fields:
        engine.register(dk, _NestedAwareRuleWrapper(NotNullRule(field, "ERROR")))

    # --- Revenue positive check ---
    engine.register(dk, _NestedAwareRuleWrapper(RangeRule("revenue", min_val=0, severity="WARNING")))

    # --- Net income reasonableness ---
    # Net income attr_p should be <= revenue (in absolute terms, excluding edge cases)
    engine.register(dk, _NetIncomeReasonableRule())

    # --- Balance sheet equation ---
    engine.register(dk, _BalanceSheetBalancedRule())

    # --- Statement type validation ---
    engine.register(dk, AllowedValuesRule(
        "statement_type",
        {"income_statement", "balance_sheet", "cash_flow", "financial_indicators", "all", "unknown"},
        severity="WARNING",
    ))

    # --- Cross-field sanity checks ---
    engine.register(dk, _NestedAwareRuleWrapper(FieldComparisonRule(
        "total_assets", "total_liabilities",
        relation=">=",
        severity="WARNING",
        label="total_assets >= total_liabilities",
    )))
    engine.register(dk, _NestedAwareRuleWrapper(FieldComparisonRule(
        "total_assets", "total_equity",
        relation=">=",
        severity="WARNING",
        label="total_assets >= total_equity",
    )))


class _NetIncomeReasonableRule:
    """Check that net income is within reasonable bounds relative to revenue.

    For normal companies: |net_income| should be < revenue * 5
    (This catches data entry errors where net_income has wrong magnitude)
    """

    @property
    def name(self) -> str:
        return "net_income_reasonable"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[dict]:
        # Support both flat and nested data
        income = data.get("income_statement") or data
        revenue = income.get("revenue")
        net_income = income.get("net_income_attr_p") or income.get("net_income")

        if revenue is None or net_income is None:
            return None

        try:
            rev = float(revenue)
            ni = float(net_income)
        except (TypeError, ValueError):
            return None

        if rev == 0:
            return None

        ratio = abs(ni) / abs(rev)
        if ratio > 5.0:
            from .engine import ValidationIssue
            return ValidationIssue(
                rule_name=self.name,
                severity=self.severity,
                field_path="net_income",
                expected_value=f"|net_income| < {abs(rev) * 5:.0f}",
                actual_value=f"{ni} (ratio={ratio:.2f}x revenue)",
                message=f"Net income ({ni}) is {ratio:.1f}x revenue ({rev}), possible data error",
            )

        return None


class _BalanceSheetBalancedRule:
    """Check that the balance sheet equation holds:
    total_assets ≈ total_liabilities + total_equity

    Uses relative tolerance to account for rounding differences between sources.
    """

    @property
    def name(self) -> str:
        return "balance_sheet_balanced"

    @property
    def severity(self) -> str:
        return "WARNING"

    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[dict]:
        # Support both flat and nested data
        balance = data.get("balance_sheet") or data

        total_assets = balance.get("total_assets")
        total_liab = balance.get("total_liabilities")
        total_equity = balance.get("total_equity") or balance.get("equity_attr_p")

        if total_assets is None or total_liab is None or total_equity is None:
            return None

        try:
            assets = float(total_assets)
            liab = float(total_liab)
            equity = float(total_equity)
        except (TypeError, ValueError):
            return None

        if assets == 0:
            return None

        lhs = assets
        rhs = liab + equity
        diff = abs(lhs - rhs) / max(abs(lhs), abs(rhs), 1e-10)

        if diff > BALANCE_SHEET_TOLERANCE:
            from .engine import ValidationIssue
            return ValidationIssue(
                rule_name=self.name,
                severity=self.severity,
                field_path="balance_sheet",
                expected_value=f"assets ≈ liabilities + equity (tol={BALANCE_SHEET_TOLERANCE*100:.0f}%)",
                actual_value=f"assets={assets:.0f}, liab+equity={rhs:.0f}, diff={diff*100:.2f}%",
                message=(
                    f"Balance sheet equation check failed: "
                    f"assets={assets:,.0f} vs liab+equity={rhs:,.0f} "
                    f"(diff={diff*100:.2f}%, tolerance={BALANCE_SHEET_TOLERANCE*100:.0f}%)"
                ),
            )

        return None
