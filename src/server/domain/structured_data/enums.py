# src/server/domain/structured_data/enums.py
"""State machine and classification enums for the structured data platform.

Pipeline states flow:
    RAW_INGESTED → NORMALIZED → VALIDATED → AUTO_PUBLISHED
                                         ↘ PENDING_REVIEW → APPROVED → PUBLISHED
                                                          ↘ REJECTED
    Any state → SUPERSEDED (when a newer version replaces an older one)
"""

from enum import Enum


class PipelineState(str, Enum):
    """Canonical pipeline state for a data record."""

    RAW_INGESTED = "RAW_INGESTED"          # Raw data fetched from source, not yet normalized
    NORMALIZED = "NORMALIZED"              # Transformed to canonical schema
    VALIDATED = "VALIDATED"                # Passed validation rules
    AUTO_PUBLISHED = "AUTO_PUBLISHED"      # Auto-published to canonical table (high confidence)
    PENDING_REVIEW = "PENDING_REVIEW"      # Flagged for human review
    APPROVED = "APPROVED"                  # Human-approved, ready for publish
    REJECTED = "REJECTED"                  # Human-rejected
    PUBLISHED = "PUBLISHED"                # Published to canonical table (after approval)
    SUPERSEDED = "SUPERSEDED"              # Replaced by a newer version


# Valid state transitions (from_state -> set of allowed to_states)
VALID_TRANSITIONS: dict[PipelineState, set[PipelineState]] = {
    PipelineState.RAW_INGESTED: {
        PipelineState.NORMALIZED,
    },
    PipelineState.NORMALIZED: {
        PipelineState.VALIDATED,
    },
    PipelineState.VALIDATED: {
        PipelineState.AUTO_PUBLISHED,
        PipelineState.PENDING_REVIEW,
    },
    PipelineState.PENDING_REVIEW: {
        PipelineState.APPROVED,
        PipelineState.REJECTED,
    },
    PipelineState.APPROVED: {
        PipelineState.PUBLISHED,
    },
    PipelineState.REJECTED: set(),  # Terminal state
    PipelineState.AUTO_PUBLISHED: {
        PipelineState.SUPERSEDED,
    },
    PipelineState.PUBLISHED: {
        PipelineState.SUPERSEDED,
    },
    PipelineState.SUPERSEDED: set(),  # Terminal state
}


class JobStatus(str, Enum):
    """Status for dataset refresh jobs."""

    PENDING = "PENDING"          # Job created, not started
    RUNNING = "RUNNING"          # Job in progress
    COMPLETED = "COMPLETED"      # Job finished successfully
    FAILED = "FAILED"            # Job failed
    PARTIAL = "PARTIAL"          # Some records succeeded, some failed


class ValidationSeverity(str, Enum):
    """Severity level for validation issues."""

    ERROR = "ERROR"              # Hard rule violation — blocks auto-publish
    WARNING = "WARNING"          # Soft rule violation — allowed but flagged
    INFO = "INFO"                # Informational note


class ApprovalAction(str, Enum):
    """Action taken during approval review."""

    APPROVE = "APPROVE"          # Approve the record
    REJECT = "REJECT"            # Reject the record
    OVERRIDE_PUBLISH = "OVERRIDE_PUBLISH"  # Force publish despite issues
    COMMENT = "COMMENT"          # Add comment without changing state


class IssueStatus(str, Enum):
    """Status of a validation issue."""

    OPEN = "OPEN"                # Issue detected, not resolved
    RESOLVED = "RESOLVED"        # Issue resolved
    WONT_FIX = "WONT_FIX"        # Issue acknowledged but won't fix


def can_transition(from_state: PipelineState, to_state: PipelineState) -> bool:
    """Check if a state transition is valid."""
    allowed = VALID_TRANSITIONS.get(from_state, set())
    return to_state in allowed


def validate_transition(from_state: PipelineState, to_state: PipelineState) -> None:
    """Validate a state transition, raising ValueError if invalid."""
    if not can_transition(from_state, to_state):
        raise ValueError(
            f"Invalid state transition: {from_state.value} → {to_state.value}. "
            f"Allowed transitions from {from_state.value}: "
            f"{[s.value for s in VALID_TRANSITIONS.get(from_state, set())]}"
        )
