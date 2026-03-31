# src/server/domain/structured_data/compare/multi_source_comparator.py
"""Multi-source comparator — orchestrates cross-source comparison for candidates.

Wraps ComparisonEngine to group candidates by business_key, run field-level
comparisons, and produce a summary with confidence adjustments for the pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger

from .engine import ComparisonEngine, ComparisonResult, ToleranceConfig


class MultiSourceComparator:
    """Compare normalized candidates from multiple sources for the same entity.

    Usage:
        comparator = MultiSourceComparator()
        result = comparator.compare_candidates(
            dataset_key="financial_statements",
            business_key="SSE:600519:2024Q3:income_statement",
            candidates=[
                {"source": "akshare", "revenue": 1000000, "net_income": 500000},
                {"source": "tushare", "revenue": 1001000, "net_income": 499000},
            ],
        )
        print(result.confidence_score, result.conflict_fields)
    """

    def __init__(
        self,
        tolerance: Optional[ToleranceConfig] = None,
        confidence_boost: float = 0.15,
        confidence_penalty: float = 0.1,
    ):
        self._engine = ComparisonEngine(tolerance or ToleranceConfig())
        self._confidence_boost = confidence_boost
        self._confidence_penalty = confidence_penalty

    def compare_candidates(
        self,
        dataset_key: str,
        business_key: str,
        candidates: List[Dict[str, Any]],
    ) -> ComparisonResult:
        """Compare multiple candidates for the same business key.

        Args:
            dataset_key: Which dataset these candidates belong to.
            business_key: The entity identifier (e.g. "SSE:600519:2024Q3:income_statement").
            candidates: List of normalized candidate dicts, each tagged with "source".

        Returns:
            ComparisonResult with field-level diffs, confidence score, and conflict list.
        """
        result = self._engine.compare(
            business_key=business_key,
            dataset_key=dataset_key,
            candidates=candidates,
        )

        logger.info(
            "Multi-source comparison complete",
            dataset_key=dataset_key,
            business_key=business_key,
            sources=result.sources_compared,
            confidence=result.confidence_score,
            conflicts=result.conflict_count,
        )

        return result

    def group_and_compare(
        self,
        dataset_key: str,
        candidates_by_source: Dict[str, Dict[str, Any]],
        business_key: str,
    ) -> Dict[str, ComparisonResult]:
        """Group candidates by business_key and compare across sources.

        This is used when the orchestrator has normalized results from
        multiple sources for the same business_key.

        Args:
            dataset_key: The dataset being processed.
            candidates_by_source: Mapping of source_name -> normalized_data.
            business_key: The entity identifier.

        Returns:
            Dict mapping business_key -> ComparisonResult.
        """
        candidates = []
        for source_name, data in candidates_by_source.items():
            tagged = dict(data)
            tagged["source"] = source_name
            candidates.append(tagged)

        if len(candidates) < 2:
            # Single source — no comparison needed
            return {}

        result = self.compare_candidates(
            dataset_key=dataset_key,
            business_key=business_key,
            candidates=candidates,
        )
        return {business_key: result}

    def confidence_adjustment(self, result: Optional[ComparisonResult]) -> float:
        """Calculate confidence adjustment from comparison result.

        Returns a value to add to the base confidence:
        - Positive if sources agree (boost)
        - Negative if sources disagree (penalty)
        - Zero if no comparison available
        """
        if result is None:
            return 0.0

        if not result.has_conflicts:
            # Full agreement — boost confidence
            return self._confidence_boost * len(result.sources_compared) / 2

        # Partial or no agreement — penalty proportional to conflict ratio
        if result.field_count > 0:
            conflict_ratio = result.conflict_count / result.field_count
            return -self._confidence_penalty * conflict_ratio

        return 0.0

    def pick_best_source(
        self,
        candidates: List[Dict[str, Any]],
        comparison: Optional[ComparisonResult],
    ) -> Dict[str, Any]:
        """Pick the best candidate to use as the primary for publishing.

        Strategy:
        1. If comparison shows no conflicts, pick the first source (by priority).
        2. If there are conflicts, prefer the source with fewer missing fields
           and higher completeness.
        """
        if not candidates:
            return {}

        if len(candidates) == 1:
            return candidates[0]

        # Score each candidate by field completeness
        best = candidates[0]
        best_score = _completeness_score(best)

        for candidate in candidates[1:]:
            score = _completeness_score(candidate)
            if score > best_score:
                best = candidate
                best_score = score

        return best


def _completeness_score(data: Dict[str, Any]) -> float:
    """Calculate field completeness score for a candidate."""
    non_meta = {k: v for k, v in data.items() if not k.startswith("_")}
    if not non_meta:
        return 0.0
    filled = sum(1 for v in non_meta.values() if v is not None)
    return filled / len(non_meta)
