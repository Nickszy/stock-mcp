# src/server/domain/structured_data/orchestrator.py
"""Orchestrator — coordinates the full pipeline from raw to canonical.

The orchestrator ties together: fetch → normalize → validate → publish.
It uses the registry to find the right normalizer/validator for each dataset,
and delegates to the appropriate repositories.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger

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
        2. Normalize each snapshot → candidate
        3. Validate each candidate
        4. Auto-publish or route to approval
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
        }

        for snapshot in snapshots:
            try:
                result = await self._process_snapshot(
                    snapshot=snapshot,
                    config=config,
                    normalizer=normalizer,
                    validator=validator,
                )
                for key in stats:
                    stats[key] += result.get(key, 0)
            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    "Failed to process snapshot",
                    snapshot_id=snapshot.get("snapshot_id"),
                    error=str(e),
                )

        return {"status": "completed", "processed": len(snapshots), **stats}

    async def _process_snapshot(
        self,
        snapshot: Dict[str, Any],
        config: Any,
        normalizer: Any,
        validator: Any = None,
    ) -> Dict[str, Any]:
        """Process a single raw snapshot through the pipeline."""
        result = {
            "normalized": 0,
            "validated": 0,
            "auto_published": 0,
            "pending_review": 0,
            "rejected": 0,
        }

        snapshot_id = snapshot.get("snapshot_id", "")
        job_id = snapshot.get("job_id", "")
        source = snapshot.get("source", "")
        raw_data = snapshot.get("raw_data", {})

        # Step 1: Normalize
        if hasattr(normalizer, "normalize"):
            normalized = await normalizer.normalize(raw_data, source=source)
        else:
            normalized = raw_data  # Passthrough if no method

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

        # Step 4: Publish decision
        # If hard errors exist → reject with low confidence
        if error_count > 0:
            # Confidence degrades with each ERROR-level validation issue
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
            result["pending_review"] = 1
            return result

        # Calculate confidence dynamically:
        # - Base confidence from field completeness
        # - Penalty for WARNING-level validation issues
        # - Bonus for multi-source corroboration (if canonical exists)
        non_meta_keys = [k for k in normalized if not k.startswith("_")]
        total_fields = len(non_meta_keys)
        mapped_fields = sum(1 for k in non_meta_keys if normalized[k] is not None)
        completeness = mapped_fields / max(total_fields, 1) if total_fields > 0 else 0.5

        confidence = min(0.95, 0.6 + completeness * 0.25 - warning_count * 0.05)

        # Check if current canonical exists — corroboration bonus
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
            result["auto_published"] = 1
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
            result["pending_review"] = 1

        return result
