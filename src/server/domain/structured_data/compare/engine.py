# src/server/domain/structured_data/compare/engine.py
"""Comparison engine — field-level diff between multi-source candidates.

Given multiple normalized candidates for the same business key (from different
sources), this engine compares them field-by-field, producing:
- Field-level diff with values from each source
- Confidence score (how much the sources agree)
- Conflict list (fields where sources disagree beyond tolerance)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.server.utils.logger import logger


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FieldDiff:
    """Difference for a single field between sources."""
    field_name: str
    values: Dict[str, Any]           # source_name -> value
    is_conflict: bool = False        # disagreement beyond tolerance
    tolerance_used: Optional[float] = None
    max_relative_diff: float = 0.0   # max relative difference between any pair


@dataclass
class ComparisonResult:
    """Result of comparing multiple candidates for the same business key."""
    business_key: str
    dataset_key: str
    sources_compared: List[str]
    field_diffs: List[FieldDiff] = field(default_factory=list)
    confidence_score: float = 0.0    # 0.0 (total disagreement) to 1.0 (perfect)
    conflict_fields: List[str] = field(default_factory=list)
    agreed_fields: List[str] = field(default_factory=list)
    field_count: int = 0
    conflict_count: int = 0

    @property
    def has_conflicts(self) -> bool:
        return self.conflict_count > 0


# ---------------------------------------------------------------------------
# Tolerance configuration
# ---------------------------------------------------------------------------

@dataclass
class ToleranceConfig:
    """Tolerance settings for field comparison.

    - numeric_relative_tol: relative tolerance for numeric fields (e.g. 0.01 = 1%)
    - numeric_absolute_tol: absolute tolerance for numeric fields
    - string_case_sensitive: whether string comparison is case-sensitive
    - ignore_fields: fields to skip during comparison
    - field_tolerances: per-field override tolerances {field_name: relative_tol}
    """
    numeric_relative_tol: float = 0.01     # 1%
    numeric_absolute_tol: float = 0.01      # absolute
    string_case_sensitive: bool = False
    ignore_fields: List[str] = field(default_factory=lambda: [
        "_source", "_normalized_at", "source", "fetched_at",
    ])
    field_tolerances: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Comparison Engine
# ---------------------------------------------------------------------------

class ComparisonEngine:
    """Compare multiple normalized candidates field-by-field.

    Usage:
        engine = ComparisonEngine()
        result = engine.compare(
            business_key="SSE:600519:2024Q3:income_statement",
            dataset_key="financial_statements",
            candidates=[
                {"source": "akshare", "revenue": 1000000, "net_income": 500000},
                {"source": "tushare", "revenue": 1001000, "net_income": 499000},
            ],
        )
        print(result.confidence_score, result.conflict_fields)
    """

    def __init__(self, tolerance: Optional[ToleranceConfig] = None):
        self.tolerance = tolerance or ToleranceConfig()

    def compare(
        self,
        business_key: str,
        dataset_key: str,
        candidates: List[Dict[str, Any]],
    ) -> ComparisonResult:
        """Compare multiple candidates for the same business key."""
        if not candidates:
            return ComparisonResult(
                business_key=business_key,
                dataset_key=dataset_key,
                sources_compared=[],
                confidence_score=0.0,
            )

        # Single source = auto high confidence
        if len(candidates) == 1:
            src = candidates[0].get("source", candidates[0].get("_source", "single"))
            return ComparisonResult(
                business_key=business_key,
                dataset_key=dataset_key,
                sources_compared=[src],
                confidence_score=0.7,  # Single source = moderate confidence
                field_count=len(candidates[0]),
                agreed_fields=list(candidates[0].keys()),
            )

        # Build source map
        source_map = {}
        for c in candidates:
            src_name = c.get("source", c.get("_source", f"source_{len(source_map)}"))
            source_map[src_name] = c

        sources = list(source_map.keys())

        # Collect all canonical fields (union of all candidates)
        all_fields = set()
        for data in source_map.values():
            all_fields.update(data.keys())
        all_fields -= set(self.tolerance.ignore_fields)

        # Compare field by field
        field_diffs: List[FieldDiff] = []
        conflict_fields: List[str] = []
        agreed_fields: List[str] = []
        total_fields = 0
        agreed_count = 0

        for fname in sorted(all_fields):
            # Collect values from each source
            values: Dict[str, Any] = {}
            for src_name, data in source_map.items():
                if fname in data:
                    values[src_name] = data[fname]

            if len(values) < 2:
                # Only one source has this field — no comparison possible
                continue

            total_fields += 1

            # Check if values agree
            diff = self._compare_field(fname, values)
            field_diffs.append(diff)

            if diff.is_conflict:
                conflict_fields.append(fname)
            else:
                agreed_fields.append(fname)
                agreed_count += 1

        # Calculate confidence score
        confidence = self._calculate_confidence(total_fields, agreed_count, field_diffs)

        result = ComparisonResult(
            business_key=business_key,
            dataset_key=dataset_key,
            sources_compared=sources,
            field_diffs=field_diffs,
            confidence_score=round(confidence, 3),
            conflict_fields=conflict_fields,
            agreed_fields=agreed_fields,
            field_count=total_fields,
            conflict_count=len(conflict_fields),
        )

        logger.debug(
            "Comparison complete",
            business_key=business_key,
            dataset_key=dataset_key,
            sources=sources,
            confidence=round(confidence, 3),
            conflicts=len(conflict_fields),
        )

        return result

    def _compare_field(self, field_name: str, values: Dict[str, Any]) -> FieldDiff:
        """Compare values for a single field across sources."""
        val_list = list(values.values())

        # Check if all values are identical
        if self._values_equal(val_list):
            return FieldDiff(
                field_name=field_name,
                values=values,
                is_conflict=False,
                max_relative_diff=0.0,
            )

        # Numeric comparison with tolerance
        if all(self._is_numeric(v) for v in val_list):
            nums = [float(v) for v in val_list]
            rel_tol = self.tolerance.field_tolerances.get(
                field_name, self.tolerance.numeric_relative_tol,
            )
            abs_tol = self.tolerance.numeric_absolute_tol

            max_rel_diff = self._max_relative_diff(nums)
            is_conflict = max_rel_diff > rel_tol

            # Also check absolute tolerance for near-zero values
            if not is_conflict:
                max_abs_diff = max(abs(a - b) for a, b in self._pairs(nums))
                if max_abs_diff > abs_tol and max(nums) < 1.0:
                    is_conflict = True

            return FieldDiff(
                field_name=field_name,
                values=values,
                is_conflict=is_conflict,
                tolerance_used=rel_tol,
                max_relative_diff=round(max_rel_diff, 6),
            )

        # String comparison
        str_vals = [str(v).strip() for v in val_list]
        if not self.tolerance.string_case_sensitive:
            str_vals = [s.lower() for s in str_vals]

        is_conflict = len(set(str_vals)) > 1
        return FieldDiff(
            field_name=field_name,
            values=values,
            is_conflict=is_conflict,
        )

    def _values_equal(self, values: List[Any]) -> bool:
        """Check if all values are equal."""
        if not values:
            return True
        first = values[0]
        return all(self._safe_eq(first, v) for v in values[1:])

    @staticmethod
    def _safe_eq(a: Any, b: Any) -> bool:
        """Safe equality check handling None, NaN, etc."""
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        try:
            if isinstance(a, float) and isinstance(b, float):
                import math
                if math.isnan(a) and math.isnan(b):
                    return True
                return abs(a - b) < 1e-10
        except (TypeError, ValueError):
            pass
        return a == b

    @staticmethod
    def _is_numeric(value: Any) -> bool:
        """Check if a value can be treated as numeric."""
        if isinstance(value, (int, float)):
            return True
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _max_relative_diff(nums: List[float]) -> float:
        """Calculate max relative difference between any pair."""
        if len(nums) < 2:
            return 0.0
        max_diff = 0.0
        for a, b in ComparisonEngine._pairs(nums):
            denom = max(abs(a), abs(b))
            if denom < 1e-10:
                if abs(a - b) > 1e-10:
                    return float("inf")
                continue
            rel = abs(a - b) / denom
            max_diff = max(max_diff, rel)
        return max_diff

    @staticmethod
    def _pairs(items: List[float]) -> List[Tuple[float, float]]:
        """Generate all pairs from a list."""
        result = []
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                result.append((items[i], items[j]))
        return result

    @staticmethod
    def _calculate_confidence(
        total_fields: int,
        agreed_count: int,
        diffs: List[FieldDiff],
    ) -> float:
        """Calculate confidence score from comparison results.

        1.0 = all fields agree across all sources
        0.5+ = most fields agree, some near-tolerance diffs
        <0.5 = significant disagreement
        """
        if total_fields == 0:
            return 0.5

        # Base: ratio of agreed fields
        base = agreed_count / total_fields

        # Bonus: for fields that conflict but are within 2x tolerance
        near_miss_bonus = 0.0
        for diff in diffs:
            if diff.is_conflict and diff.max_relative_diff > 0:
                # Partial credit for near misses
                near_miss_bonus += 0.1 * (1.0 - diff.max_relative_diff)

        # Source count bonus: more sources agreeing = higher confidence
        source_bonus = 0.05 * max(0, len(set(
            v for d in diffs for v in d.values.values()
        )) - 2)

        return min(1.0, base + near_miss_bonus + source_bonus)
