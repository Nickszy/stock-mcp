# src/server/domain/structured_data/validate/engine.py
"""Validation engine — rule-based quality checks on normalized data.

Supports two severity levels:
- ERROR (hard rule): blocks auto-publish, routes to approval queue
- WARNING (soft rule): flags the issue but doesn't block auto-publish

Rules are organized as:
- Common rules: reusable across dimensions (field_type_check, not_null, etc.)
- Dimension-specific rules: registered per dataset (revenue_positive, etc.)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    """A single validation issue found in data."""
    rule_name: str
    severity: str = "WARNING"       # "ERROR" or "WARNING"
    field_path: Optional[str] = None
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Aggregate result of validating a candidate."""
    dataset_key: str
    business_key: str
    issues: List[ValidationIssue] = field(default_factory=list)
    passed: bool = True              # No ERROR-severity issues
    warning_count: int = 0
    error_count: int = 0
    score: float = 1.0               # Quality score 0-1

    def add_issue(self, issue: ValidationIssue) -> None:
        self.issues.append(issue)
        if issue.severity == "ERROR":
            self.error_count += 1
            self.passed = False
        else:
            self.warning_count += 1

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def has_warnings(self) -> bool:
        return self.warning_count > 0


# ---------------------------------------------------------------------------
# Rule interface
# ---------------------------------------------------------------------------

class ValidationRule(ABC):
    """Base class for validation rules."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Rule name for identification."""
        ...

    @property
    def severity(self) -> str:
        """Default severity: WARNING or ERROR."""
        return "WARNING"

    @abstractmethod
    async def check(
        self,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[ValidationIssue]:
        """Check data against this rule.

        Returns None if the check passes, or a ValidationIssue if it fails.
        """
        ...


# ---------------------------------------------------------------------------
# Validation Engine
# ---------------------------------------------------------------------------

class ValidationEngine:
    """Run a set of validation rules against normalized data.

    Usage:
        engine = ValidationEngine()
        engine.register(NotNullRule("revenue"))
        engine.register(RangeRule("revenue", min_val=0))
        result = await engine.validate("financial_statements", "SSE:600519:2024Q3", data)
    """

    def __init__(self):
        self._rules: Dict[str, List[ValidationRule]] = {}  # dataset_key -> rules

    def register(self, dataset_key: str, rule: ValidationRule) -> None:
        """Register a validation rule for a dataset."""
        if dataset_key not in self._rules:
            self._rules[dataset_key] = []
        self._rules[dataset_key].append(rule)

    def register_many(self, dataset_key: str, rules: List[ValidationRule]) -> None:
        """Register multiple rules for a dataset."""
        for rule in rules:
            self.register(dataset_key, rule)

    async def validate(
        self,
        dataset_key: str,
        business_key: str,
        data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """Run all registered rules for a dataset against the data."""
        result = ValidationResult(
            dataset_key=dataset_key,
            business_key=business_key,
        )

        rules = self._rules.get(dataset_key, [])
        if not rules:
            # No rules = auto-pass with high score
            result.score = 1.0
            return result

        checked = 0
        for rule in rules:
            try:
                issue = await rule.check(data, context)
                checked += 1
                if issue is not None:
                    result.add_issue(issue)
            except Exception as e:
                logger.warning(
                    "Validation rule error",
                    rule=rule.name,
                    dataset_key=dataset_key,
                    error=str(e),
                )
                result.add_issue(ValidationIssue(
                    rule_name=rule.name,
                    severity="WARNING",
                    message=f"Rule execution failed: {e}",
                ))

        # Calculate quality score
        if checked > 0:
            error_penalty = result.error_count * 0.3
            warning_penalty = result.warning_count * 0.05
            result.score = max(0.0, 1.0 - error_penalty - warning_penalty)

        logger.debug(
            "Validation complete",
            dataset_key=dataset_key,
            business_key=business_key,
            passed=result.passed,
            errors=result.error_count,
            warnings=result.warning_count,
            score=result.score,
        )

        return result
