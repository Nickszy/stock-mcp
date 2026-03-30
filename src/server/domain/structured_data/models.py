# src/server/domain/structured_data/models.py
"""Pydantic models for the structured data platform.

These models represent the domain objects and their database-backed representations.
Tables are created via `ensure_schema()` in repository classes (following the project's
existing pattern — no ORM, raw asyncpg SQL).
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .enums import (
    ApprovalAction,
    IssueStatus,
    JobStatus,
    PipelineState,
    ValidationSeverity,
)


# ---------------------------------------------------------------------------
# Dataset Job — tracks refresh/sync jobs per data dimension
# ---------------------------------------------------------------------------

class DatasetJob(BaseModel):
    """A refresh job for a specific data dimension."""

    job_id: str
    dataset_key: str = Field(
        ...,
        description="Logical dataset identifier, e.g. 'financial_statements', 'company_profile'",
    )
    status: JobStatus = JobStatus.PENDING
    triggered_by: str = Field(
        "manual",
        description="How the job was triggered: 'manual', 'scheduled', 'event'",
    )
    source: Optional[str] = Field(
        None,
        description="Data source for this job (e.g. 'akshare', 'tushare')",
    )
    total_records: int = 0
    success_count: int = 0
    fail_count: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Raw Snapshot — raw data fetched from source, stored as-is
# ---------------------------------------------------------------------------

class RawSnapshot(BaseModel):
    """Raw data snapshot from a source, stored before normalization."""

    snapshot_id: str
    job_id: str
    dataset_key: str
    source: str = Field(..., description="Data source name (akshare, tushare, etc.)")
    business_key: str = Field(
        ...,
        description="Source-specific business key, e.g. '600519:2024Q3:income_statement'",
    )
    raw_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Raw data payload from the source (stored as JSONB)",
    )
    fetched_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Normalized Candidate — transformed to canonical schema, ready for validation
# ---------------------------------------------------------------------------

class NormalizedCandidate(BaseModel):
    """Normalized data record ready for validation and comparison."""

    candidate_id: str
    snapshot_id: str
    job_id: str
    dataset_key: str
    source: str
    business_key: str = Field(
        ...,
        description="Canonical business key after normalization, e.g. 'SSE:600519:2024Q3:income_statement'",
    )
    normalized_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Normalized data payload matching canonical schema",
    )
    state: PipelineState = PipelineState.RAW_INGESTED
    confidence_score: Optional[float] = Field(
        None,
        description="Confidence score from comparison engine (0.0-1.0)",
        ge=0.0,
        le=1.0,
    )
    comparison_result: Optional[Dict[str, Any]] = Field(
        None,
        description="Field-level diff from comparison engine",
    )
    version: int = Field(1, description="Version number for this business key")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Validation Issue — problems found during validation
# ---------------------------------------------------------------------------

class ValidationIssue(BaseModel):
    """A validation issue found during data quality checks."""

    issue_id: str
    candidate_id: str
    dataset_key: str
    rule_name: str = Field(..., description="Name of the validation rule that triggered")
    severity: ValidationSeverity = ValidationSeverity.WARNING
    status: IssueStatus = IssueStatus.OPEN
    field_path: Optional[str] = Field(
        None, description="JSON path to the problematic field, e.g. 'revenue'",
    )
    expected_value: Optional[str] = None
    actual_value: Optional[str] = None
    message: Optional[str] = None
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Approval Task — item pending human review
# ---------------------------------------------------------------------------

class ApprovalTask(BaseModel):
    """A record that has been flagged for human review."""

    task_id: str
    candidate_id: str
    dataset_key: str
    business_key: str
    reason: Optional[str] = Field(
        None,
        description="Why this record was flagged (e.g. 'confidence_score_below_threshold')",
    )
    is_resolved: bool = False
    created_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Approval Action — audit trail for approval decisions
# ---------------------------------------------------------------------------

class ApprovalActionRecord(BaseModel):
    """An audit record of an approval/rejection action."""

    action_id: str
    task_id: str
    reviewer: str = Field(..., description="Who performed the action")
    action: ApprovalAction = ApprovalAction.COMMENT
    comment: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Canonical Record — the final published data
# ---------------------------------------------------------------------------

class CanonicalRecord(BaseModel):
    """A published canonical record — the source of truth for downstream consumers."""

    canonical_id: str
    dataset_key: str
    business_key: str
    data: Dict[str, Any] = Field(default_factory=dict, description="The canonical data payload")
    version: int = 1
    source: str = Field(
        "auto",
        description="How this record was published: 'auto' (auto_published) or 'approved' (human review)",
    )
    published_at: Optional[datetime] = None
    superseded_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Dataset Registry Entry — config per data dimension (used by COL-223)
# ---------------------------------------------------------------------------

class DatasetRegistryEntry(BaseModel):
    """Configuration entry for a data dimension in the registry."""

    dataset_key: str = Field(..., description="Unique key, e.g. 'financial_statements'")
    display_name: str = Field("", description="Human-readable name")
    description: str = ""
    primary_key_template: str = Field(
        "",
        description="Template for canonical business key, e.g. '{exchange}:{symbol}:{report_period}:{statement_type}'",
    )
    source_priority: List[str] = Field(
        default_factory=lambda: ["akshare", "tushare"],
        description="Ordered list of preferred data sources",
    )
    soft_ttl_hours: int = Field(
        24,
        description="Hours before a soft refresh is triggered",
    )
    hard_ttl_hours: int = Field(
        168,
        description="Hours before data is considered stale (7 days default)",
    )
    auto_publish_threshold: float = Field(
        0.8,
        description="Confidence score threshold for auto-publish (below this → PENDING_REVIEW)",
    )
    validation_rules: List[str] = Field(
        default_factory=list,
        description="List of validation rule names to apply",
    )
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
