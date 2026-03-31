# src/server/domain/structured_data/validate/financial_statements_wrapper.py
"""Wrapper that adapts the ValidationEngine to the Orchestrator's validator interface.

The Orchestrator expects validator.validate(data, config) -> List[dict].
The ValidationEngine runs registered rules and returns ValidationResult.
This wrapper bridges the gap.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .engine import ValidationEngine, ValidationResult
from .financial_statements import register_financial_statement_rules


class FinancialStatementsValidator:
    """Validator wrapper for financial statements.

    Wraps ValidationEngine with registered rules and exposes the interface
    expected by the Orchestrator: validate(data, config) -> List[dict].
    """

    def __init__(self):
        self._engine = ValidationEngine()
        register_financial_statement_rules(self._engine)

    async def validate(
        self,
        data: Dict[str, Any],
        config: Any = None,
    ) -> List[Dict[str, Any]]:
        """Validate normalized financial data.

        Args:
            data: Normalized data from FinancialStatementsNormalizer
            config: DatasetConfig (unused here but required by interface)

        Returns:
            List of issue dicts with: rule_name, severity, field_path,
            expected_value, actual_value, message
        """
        dataset_key = "financial_statements"
        business_key = data.get("business_key", "unknown")

        result: ValidationResult = await self._engine.validate(
            dataset_key=dataset_key,
            business_key=business_key,
            data=data,
        )

        # Convert ValidationIssue objects to dicts for the Orchestrator
        issues = []
        for issue in result.issues:
            issues.append({
                "rule_name": issue.rule_name if hasattr(issue, "rule_name") else str(issue.get("rule_name", "unknown")),
                "severity": issue.severity if hasattr(issue, "severity") else str(issue.get("severity", "WARNING")),
                "field_path": getattr(issue, "field_path", None) or (issue.get("field_path") if isinstance(issue, dict) else None),
                "expected_value": getattr(issue, "expected_value", None) or (issue.get("expected_value") if isinstance(issue, dict) else None),
                "actual_value": getattr(issue, "actual_value", None) or (issue.get("actual_value") if isinstance(issue, dict) else None),
                "message": getattr(issue, "message", "") or (issue.get("message", "") if isinstance(issue, dict) else ""),
            })

        return issues
