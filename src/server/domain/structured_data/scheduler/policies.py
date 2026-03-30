# src/server/domain/structured_data/scheduler/policies.py
"""Refresh policies — determine whether a dataset needs refreshing.

Policies are evaluated in order. If any policy says "needs refresh", the
dataset is scheduled for refresh. This avoids scattering refresh logic
across adapters.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from src.server.utils.logger import logger

from ..registry import DatasetConfig, TTLConfig


# ---------------------------------------------------------------------------
# Policy result
# ---------------------------------------------------------------------------

class RefreshDecision:
    """Result of evaluating whether a dataset needs refresh."""

    def __init__(
        self,
        should_refresh: bool,
        reason: str = "",
        priority: str = "normal",  # "normal" | "urgent"
    ):
        self.should_refresh = should_refresh
        self.reason = reason
        self.priority = priority

    def __bool__(self) -> bool:
        return self.should_refresh

    def __repr__(self) -> str:
        if not self.should_refresh:
            return f"RefreshDecision(NO, {self.reason})"
        return f"RefreshDecision(YES, {self.reason}, priority={self.priority})"


# ---------------------------------------------------------------------------
# Policy interface
# ---------------------------------------------------------------------------

class RefreshPolicy:
    """Base class for refresh policies."""

    async def evaluate(
        self,
        config: DatasetConfig,
        last_fetched_at: Optional[datetime] = None,
        last_published_at: Optional[datetime] = None,
        **kwargs,
    ) -> RefreshDecision:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Built-in policies
# ---------------------------------------------------------------------------

class HardTTLPolicy(RefreshPolicy):
    """Refresh if data is older than hard TTL — data is stale and must be refreshed."""

    async def evaluate(
        self,
        config: DatasetConfig,
        last_fetched_at: Optional[datetime] = None,
        last_published_at: Optional[datetime] = None,
        **kwargs,
    ) -> RefreshDecision:
        reference_time = last_published_at or last_fetched_at
        if reference_time is None:
            return RefreshDecision(True, "no_previous_data", "urgent")

        age = datetime.now(timezone.utc) - reference_time
        if age > timedelta(hours=config.ttl.hard_ttl_hours):
            return RefreshDecision(
                True,
                f"hard_ttl_exceeded: {age.total_seconds()/3600:.1f}h > {config.ttl.hard_ttl_hours}h",
                "urgent",
            )
        return RefreshDecision(False, "within_hard_ttl")


class SoftTTLPolicy(RefreshPolicy):
    """Refresh if data is older than soft TTL — data is stale but still usable."""

    async def evaluate(
        self,
        config: DatasetConfig,
        last_fetched_at: Optional[datetime] = None,
        last_published_at: Optional[datetime] = None,
        **kwargs,
    ) -> RefreshDecision:
        reference_time = last_published_at or last_fetched_at
        if reference_time is None:
            return RefreshDecision(True, "no_previous_data", "normal")

        age = datetime.now(timezone.utc) - reference_time
        if age > timedelta(hours=config.ttl.soft_ttl_hours):
            return RefreshDecision(
                True,
                f"soft_ttl_exceeded: {age.total_seconds()/3600:.1f}h > {config.ttl.soft_ttl_hours}h",
                "normal",
            )
        return RefreshDecision(False, "within_soft_ttl")


class OnDemandPolicy(RefreshPolicy):
    """Always refresh when explicitly requested via API/MCP."""

    async def evaluate(
        self,
        config: DatasetConfig,
        force: bool = False,
        **kwargs,
    ) -> RefreshDecision:
        if force:
            return RefreshDecision(True, "force_refresh", "urgent")
        return RefreshDecision(False, "not_forced")


class NoDataPolicy(RefreshPolicy):
    """Refresh if there's no existing data at all."""

    async def evaluate(
        self,
        config: DatasetConfig,
        has_data: bool = True,
        **kwargs,
    ) -> RefreshDecision:
        if not has_data:
            return RefreshDecision(True, "no_existing_data", "urgent")
        return RefreshDecision(False, "data_exists")


# ---------------------------------------------------------------------------
# Policy chain evaluator
# ---------------------------------------------------------------------------

class RefreshPolicyChain:
    """Evaluates a chain of refresh policies. First YES wins."""

    def __init__(self, policies: Optional[list[RefreshPolicy]] = None):
        self.policies = policies or [
            OnDemandPolicy(),
            NoDataPolicy(),
            HardTTLPolicy(),
            SoftTTLPolicy(),
        ]

    async def should_refresh(
        self,
        config: DatasetConfig,
        **kwargs,
    ) -> RefreshDecision:
        """Evaluate all policies. Return the first YES or the last NO."""
        last_no = RefreshDecision(False, "no_policy_triggered")
        for policy in self.policies:
            decision = await policy.evaluate(config=config, **kwargs)
            logger.debug(
                "Policy evaluated",
                policy=type(policy).__name__,
                dataset_key=config.dataset_key,
                decision=str(decision),
            )
            if decision.should_refresh:
                return decision
            last_no = decision
        return last_no
