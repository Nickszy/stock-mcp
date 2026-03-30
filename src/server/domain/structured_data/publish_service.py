# src/server/domain/structured_data/publish_service.py
"""Publish Service for structured data pipeline.

Responsible for publishing approved candidates to the canonical_records table.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from src.server.utils.logger import logger


class PublishService:
    """Orchestrates publishing a candidate to canonical storage."""

    def __init__(self, candidate_repo, canonical_repo):
        self._candidate_repo = candidate_repo
        self._canonical_repo = canonical_repo

    async def publish_candidate(
        self,
        candidate_id: str,
        dataset_key: str,
        business_key: str,
        source: str = "approved",
    ) -> Dict[str, Any]:
        """Publish a candidate to canonical_records.

        1. Fetch candidate normalized data
        2. Call canonical_repo.publish() (atomic: supersede old + insert new)
        3. Transition candidate state to PUBLISHED

        Returns a dict with canonical_id and version.
        Raises ValueError if candidate not found.
        """
        candidate = await self._candidate_repo.get_candidate(candidate_id)
        if not candidate:
            raise ValueError(f"Candidate not found: {candidate_id}")

        # normalized_data may come back as a dict or a JSON string
        data = candidate.get("normalized_data", {})
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}

        canonical_id = await self._canonical_repo.publish(
            candidate_id=candidate_id,
            dataset_key=dataset_key,
            business_key=business_key,
            data=data,
            source=source,
        )

        # Transition candidate to PUBLISHED
        try:
            await self._candidate_repo.transition_state(candidate_id, "PUBLISHED")
        except Exception as e:
            logger.warning(
                "Could not transition candidate to PUBLISHED after publish",
                candidate_id=candidate_id,
                error=str(e),
            )

        logger.info(
            "Candidate published to canonical",
            candidate_id=candidate_id,
            dataset_key=dataset_key,
            business_key=business_key,
            source=source,
        )

        return {
            "canonical_id": str(canonical_id) if canonical_id else None,
            "candidate_id": candidate_id,
            "dataset_key": dataset_key,
            "business_key": business_key,
            "source": source,
        }

    async def rollback(
        self,
        dataset_key: str,
        business_key: str,
        target_version: int,
    ) -> Dict[str, Any]:
        """Roll back canonical to a prior version.

        Creates a new canonical record that is a copy of the target version
        so the rollback is traceable via version history.

        Returns a dict with the new canonical_id.
        Raises ValueError if target_version does not exist.
        """
        new_id = await self._canonical_repo.rollback(
            dataset_key=dataset_key,
            business_key=business_key,
            target_version=target_version,
        )
        if not new_id:
            raise ValueError(
                f"Rollback failed: version {target_version} not found for "
                f"{dataset_key}/{business_key}"
            )

        logger.info(
            "Canonical rollback complete",
            dataset_key=dataset_key,
            business_key=business_key,
            target_version=target_version,
            new_canonical_id=str(new_id),
        )
        return {
            "canonical_id": str(new_id),
            "dataset_key": dataset_key,
            "business_key": business_key,
            "rolled_back_to_version": target_version,
        }
