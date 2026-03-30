# src/server/domain/structured_data/orchestrator.py
"""Orchestrator — coordinates the full pipeline from raw to canonical.

The orchestrator ties together: fetch → normalize → validate → publish.
It uses the registry to find the right normalizer/validator for each dataset,
and delegates to the appropriate repositories.

Supports multi-source cross-validation: when multiple sources provide data
for the same business_key, the ComparisonEngine calculates agreement rates
and boosts confidence for auto-publishing.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger

from .compare.engine import ComparisonEngine, ComparisonResult
from .enums import PipelineState
from .registry import DatasetRegistry
from .repositories.candidate_repository import CandidateRepository
from .repositories.canonical_repository import CanonicalRepository
from .repositories.issue_repository import IssueRepository
from .repositories.raw_repository import RawRepository


class Orchestrator:
    """Coordinates the structured data pipeline for a single dataset job.

    Pipeline: raw_snapshots → normalized_candidates → validated → published
    """

    def __init__(
        self,
        registry: DatasetRegistry,
        raw_repo: RawRepository,
        candidate_repo: CandidateRepository,
        canonical_repo: CanonicalRepository,
        issue_repo: IssueRepository,
    ):
        self._registry = registry
        self._raw_repo = raw_repo
        self._candidate_repo = candidate_repo
        self._canonical_repo = canonical_repo
        self._issue_repo = issue_repo

    async def process_job(self, job_id: str, dataset_key: str) -> Dict[str, Any]:
        """Run the full pipeline for a completed job's raw snapshots.

        1. Load raw snapshots for the job
        2. Group snapshots by business_key for multi-source comparison
        3. Normalize each snapshot → candidate
        4. Validate each candidate
        5. Cross-validate multi-source candidates for same business_key
        6. Auto-publish or route to approval
        """
        config = self._registry.require(dataset_key)
        normalizer = self._registry.get_normalizer(dataset_key)
        validator = self._registry.get_validator(dataset_key)

        if not normalizer:
            return {
                "status": "error",
                "error": f"No normalizer registered for '{dataset_key}'",
            }

        # Load raw snapshots (filtered by job_id at DB level)
        snapshots = await self._raw_repo.list_snapshots(
            dataset_key=dataset_key,
            job_id=job_id,
            limit=1000,
        )

        if not snapshots:
            return {"status": "no_data", "processed": 0}

        logger.info(
            "Orchestrating pipeline",
            job_id=job_id,
            dataset_key=dataset_key,
            snapshot_count=len(snapshots),
        )

        stats = {
            "normalized": 0,
            "validated": 0,
            "auto_published": 0,
            "pending_review": 0,
            "rejected": 0,
            "errors": 0,
            "cross_validated": 0,
        }

        # Phase 1: Normalize all snapshots
        candidates: List[Dict[str, Any]] = []
        for snapshot in snapshots:
            try:
                result = await self._process_snapshot(
                    snapshot=snapshot,
                    config=config,
                    normalizer=normalizer,
                    validator=validator,
                    # Defer publish decision until cross-validation
                    defer_publish=True,
                )
                for key in ("normalized", "validated"):
                    stats[key] += result.get(key, 0)
                if result.get("candidate_info"):
                    candidates.append(result["candidate_info"])
            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    "Failed to process snapshot",
                    snapshot_id=snapshot.get("snapshot_id"),
                    error=str(e),
                )

        # Phase 2: Group by business_key for multi-source comparison
        by_biz_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for c in candidates:
            bk = c.get("business_key", "")
            if bk:
                by_biz_key[bk].append(c)

        # Phase 3: Cross-validate and publish
        comparison_engine = ComparisonEngine()
        for biz_key, group in by_biz_key.items():
            try:
                if len(group) > 1:
                    # Multi-source: run comparison for confidence boost
                    comparison = comparison_engine.compare(
                        business_key=biz_key,
                        dataset_key=dataset_key,
                        candidates=[c["normalized_data"] for c in group],
                    )
                    stats["cross_validated"] += 1

                    # Use the first (highest priority) candidate as base
                    base = group[0]
                    await self._publish_decision(
                        base_candidate=base,
                        config=config,
                        multi_source_comparison=comparison,
                    )
                    # Mark others as superseded
                    for other in group[1:]:
                        await self._candidate_repo.mark_superseded(
                            dataset_key=config.dataset_key,
                            business_key=biz_key,
                            except_candidate_id=base["candidate_id"],
                        )
                else:
                    # Single source: normal publish decision
                    await self._publish_decision(
                        base_candidate=group[0],
                        config=config,
                        multi_source_comparison=None,
                    )

                # Count results
                state = group[0].get("state", "")
                if "auto_published" in state or state == PipelineState.AUTO_PUBLISHED.value:
                    stats["auto_published"] += 1
                elif "pending" in state or state == PipelineState.PENDING_REVIEW.value:
                    stats["pending_review"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    "Failed to publish decision",
                    business_key=biz_key,
                    error=str(e),
                )

        return {"status": "completed", "processed": len(snapshots), **stats}

    async def _process_snapshot(
        self,
        snapshot: Dict[str, Any],
        config: Any,
        normalizer: Any,
        validator: Any = None,
        defer_publish: bool = False,
    ) -> Dict[str, Any]:
        """Process a single raw snapshot: normalize + validate.

        If defer_publish=True, returns candidate info without making a
        publish decision (for multi-source cross-validation).
        """
        result = {
            "normalized": 0,
            "validated": 0,
        }

        snapshot_id = snapshot.get("snapshot_id", "")
        job_id = snapshot.get("job_id", "")
        source = snapshot.get("source", "")
        raw_data = snapshot.get("raw_data", {})

        # Step 1: Normalize
        if hasattr(normalizer, "normalize"):
            normalized = await normalizer.normalize(raw_data, source=source)
        else:
            normalized = raw_data

        if not isinstance(normalized, dict):
            normalized = {"data": normalized}

        business_key = normalized.get("business_key", snapshot.get("business_key", ""))

        # Insert candidate
        candidate_id = await self._candidate_repo.insert_candidate(
            snapshot_id=snapshot_id,
            job_id=job_id,
            dataset_key=config.dataset_key,
            source=source,
            business_key=business_key,
            normalized_data=normalized,
        )
        result["normalized"] = 1

        # Step 2: Transition to NORMALIZED
        await self._candidate_repo.transition_state(
            candidate_id, PipelineState.NORMALIZED.value,
        )

        # Step 3: Validate
        error_count = 0
        warning_count = 0
        if validator:
            if hasattr(validator, "validate"):
                issues = await validator.validate(normalized, config)
                for issue in issues:
                    severity = issue.get("severity", "WARNING")
                    await self._candidate_repo.insert_issue(
                        candidate_id=candidate_id,
                        dataset_key=config.dataset_key,
                        rule_name=issue.get("rule_name", "unknown"),
                        severity=severity,
                        field_path=issue.get("field_path"),
                        expected_value=issue.get("expected_value"),
                        actual_value=issue.get("actual_value"),
                        message=issue.get("message"),
                    )
                    if severity == "ERROR":
                        error_count += 1
                    elif severity == "WARNING":
                        warning_count += 1

        # Transition to VALIDATED
        await self._candidate_repo.transition_state(
            candidate_id, PipelineState.VALIDATED.value,
        )
        result["validated"] = 1

        if defer_publish:
            # Return candidate info for multi-source cross-validation
            result["candidate_info"] = {
                "candidate_id": candidate_id,
                "business_key": business_key,
                "source": source,
                "normalized_data": normalized,
                "error_count": error_count,
                "warning_count": warning_count,
                "state": "",
            }
            return result

        # Immediate publish decision (single source, no cross-validation)
        await self._publish_decision(
            base_candidate=result.get("candidate_info", {
                "candidate_id": candidate_id,
                "business_key": business_key,
                "source": source,
                "normalized_data": normalized,
                "error_count": error_count,
                "warning_count": warning_count,
                "state": "",
            }),
            config=config,
            multi_source_comparison=None,
        )
        return result

    async def _publish_decision(
        self,
        base_candidate: Dict[str, Any],
        config: Any,
        multi_source_comparison: Optional[ComparisonResult] = None,
    ) -> None:
        """Make publish decision for a candidate.

        Uses multi-source comparison (if available) to boost confidence.
        When two sources agree on >= 85% of fields, confidence jumps to
        >= 0.85, enabling auto-publish.
        """
        candidate_id = base_candidate["candidate_id"]
        business_key = base_candidate["business_key"]
        normalized = base_candidate["normalized_data"]
        error_count = base_candidate.get("error_count", 0)
        warning_count = base_candidate.get("warning_count", 0)

        # Hard errors → reject with low confidence
        if error_count > 0:
            confidence = max(0.1, 0.5 - error_count * 0.1)
            await self._candidate_repo.transition_state(
                candidate_id, PipelineState.PENDING_REVIEW.value,
                confidence_score=confidence,
            )
            await self._issue_repo.create_task(
                candidate_id=candidate_id,
                dataset_key=config.dataset_key,
                business_key=business_key,
                reason=f"validation_errors:{error_count}",
            )
            base_candidate["state"] = PipelineState.PENDING_REVIEW.value
            return

        # Calculate base confidence from field completeness
        non_meta_keys = [k for k in normalized if not k.startswith("_")]
        total_fields = len(non_meta_keys)
        mapped_fields = sum(1 for k in non_meta_keys if normalized[k] is not None)
        completeness = mapped_fields / max(total_fields, 1) if total_fields > 0 else 0.5

        confidence = min(0.95, 0.6 + completeness * 0.25 - warning_count * 0.05)

        # Multi-source corroboration bonus
        if multi_source_comparison and multi_source_comparison.sources_compared:
            # Use the comparison engine's calculated confidence
            ms_confidence = multi_source_comparison.confidence_score

            # Boost: if comparison shows high agreement, raise base confidence
            if ms_confidence >= 0.85:
                # Sources agree well → significant boost
                confidence = min(0.98, max(confidence, 0.85))
            elif ms_confidence >= 0.7:
                # Moderate agreement → moderate boost
                confidence = min(0.95, confidence + 0.1)
            else:
                # Poor agreement → flag for review
                confidence = min(confidence, 0.75)

            # Log comparison results
            logger.info(
                "Multi-source comparison",
                business_key=business_key,
                sources=multi_source_comparison.sources_compared,
                comparison_confidence=ms_confidence,
                conflicts=multi_source_comparison.conflict_count,
                final_confidence=confidence,
            )

            # Store comparison result for audit
            if multi_source_comparison.has_conflicts:
                await self._issue_repo.create_task(
                    candidate_id=candidate_id,
                    dataset_key=config.dataset_key,
                    business_key=business_key,
                    reason=(
                        f"multi_source_conflicts:{multi_source_comparison.conflict_count} "
                        f"fields:{','.join(multi_source_comparison.conflict_fields[:5])}"
                    ),
                )
        else:
            # Single source: check if existing canonical exists (corroboration)
            existing_canonical = await self._canonical_repo.get_current(
                config.dataset_key, business_key,
            )
            if existing_canonical:
                confidence = min(0.98, confidence + 0.1)

        if confidence >= config.auto_publish_threshold:
            # Auto-publish
            await self._candidate_repo.transition_state(
                candidate_id,
                PipelineState.AUTO_PUBLISHED.value,
                confidence_score=confidence,
            )
            # Publish to canonical
            await self._canonical_repo.publish(
                candidate_id=candidate_id,
                dataset_key=config.dataset_key,
                business_key=business_key,
                data=normalized,
                source="auto",
            )
            # Mark older candidates as superseded
            await self._candidate_repo.mark_superseded(
                dataset_key=config.dataset_key,
                business_key=business_key,
                except_candidate_id=candidate_id,
            )
            base_candidate["state"] = PipelineState.AUTO_PUBLISHED.value
        else:
            # Route to approval
            await self._candidate_repo.transition_state(
                candidate_id,
                PipelineState.PENDING_REVIEW.value,
                confidence_score=confidence,
            )
            await self._issue_repo.create_task(
                candidate_id=candidate_id,
                dataset_key=config.dataset_key,
                business_key=business_key,
                reason=f"confidence_below_threshold:{confidence:.2f}<{config.auto_publish_threshold}",
            )
            base_candidate["state"] = PipelineState.PENDING_REVIEW.value
