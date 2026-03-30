# tests/test_structured_data_models.py
"""Tests for structured data Pydantic models."""

import pytest
import sys
sys.path.insert(0, "src")

from server.domain.structured_data.models import (
    ApprovalActionRecord,
    ApprovalTask,
    CanonicalRecord,
    DatasetJob,
    DatasetRegistryEntry,
    NormalizedCandidate,
    RawSnapshot,
    ValidationIssue,
)
from server.domain.structured_data.enums import (
    ApprovalAction,
    IssueStatus,
    JobStatus,
    PipelineState,
    ValidationSeverity,
    can_transition,
    validate_transition,
    VALID_TRANSITIONS,
)


# ============================================================
# State Machine Tests
# ============================================================


class TestPipelineState:
    def test_all_states_defined(self):
        expected = {
            "RAW_INGESTED", "NORMALIZED", "VALIDATED",
            "AUTO_PUBLISHED", "PENDING_REVIEW",
            "APPROVED", "REJECTED", "PUBLISHED", "SUPERSEDED",
        }
        actual = {s.value for s in PipelineState}
        assert actual == expected

    def test_valid_happy_path(self):
        assert can_transition(PipelineState.RAW_INGESTED, PipelineState.NORMALIZED) is True
        assert can_transition(PipelineState.NORMALIZED, PipelineState.VALIDATED) is True
        assert can_transition(PipelineState.VALIDATED, PipelineState.AUTO_PUBLISHED) is True

    def test_valid_review_path(self):
        assert can_transition(PipelineState.VALIDATED, PipelineState.PENDING_REVIEW) is True
        assert can_transition(PipelineState.PENDING_REVIEW, PipelineState.APPROVED) is True
        assert can_transition(PipelineState.APPROVED, PipelineState.PUBLISHED) is True

    def test_valid_rejection(self):
        assert can_transition(PipelineState.PENDING_REVIEW, PipelineState.REJECTED) is True

    def test_valid_supersede(self):
        assert can_transition(PipelineState.AUTO_PUBLISHED, PipelineState.SUPERSEDED) is True
        assert can_transition(PipelineState.PUBLISHED, PipelineState.SUPERSEDED) is True

    def test_terminal_states(self):
        assert VALID_TRANSITIONS[PipelineState.REJECTED] == set()
        assert VALID_TRANSITIONS[PipelineState.SUPERSEDED] == set()

    def test_invalid_transitions(self):
        assert not can_transition(PipelineState.RAW_INGESTED, PipelineState.PUBLISHED)
        assert not can_transition(PipelineState.RAW_INGESTED, PipelineState.VALIDATED)
        assert not can_transition(PipelineState.NORMALIZED, PipelineState.AUTO_PUBLISHED)
        assert not can_transition(PipelineState.REJECTED, PipelineState.APPROVED)

        assert not can_transition(PipelineState.VALIDATED, PipelineState.NORMALIZED)
        assert not can_transition(PipelineState.AUTO_PUBLISHED, PipelineState.VALIDATED)

    def test_validate_transition_raises(self):
        with pytest.raises(ValueError, match="Invalid state transition"):
            validate_transition(PipelineState.RAW_INGESTED, PipelineState.PUBLISHED)

        with pytest.raises(ValueError, match="Invalid state transition"):
            validate_transition(PipelineState.NORMALIZED, PipelineState.PUBLISHED)

    def test_validate_transition_ok(self):
        validate_transition(PipelineState.RAW_INGESTED, PipelineState.NORMALIZED)
        validate_transition(PipelineState.VALIDATED, PipelineState.AUTO_PUBLISHED)

        validate_transition(PipelineState.VALIDATED, PipelineState.PENDING_REVIEW)
        validate_transition(PipelineState.APPROVED, PipelineState.PUBLISHED)

    def test_str_enum(self):
        assert PipelineState.RAW_INGESTED == "RAW_INGESTED"
        assert PipelineState.RAW_INGESTED.value == "RAW_INGESTED"


class TestOtherEnums:
    def test_job_status(self):
        assert JobStatus.PENDING.value == "PENDING"
        assert JobStatus.RUNNING.value == "RUNNING"
        assert JobStatus.COMPLETED.value == "COMPLETED"
        assert JobStatus.FAILED.value == "FAILED"
        assert JobStatus.PARTIAL.value == "PARTIAL"

    def test_validation_severity(self):
        assert ValidationSeverity.ERROR.value == "ERROR"
        assert ValidationSeverity.WARNING.value == "WARNING"
        assert ValidationSeverity.INFO.value == "INFO"

    def test_approval_action(self):
        assert ApprovalAction.APPROVE.value == "APPROVE"
        assert ApprovalAction.REJECT.value == "REJECT"
        assert ApprovalAction.OVERRIDE_PUBLISH.value == "OVERRIDE_PUBLISH"
        assert ApprovalAction.COMMENT.value == "COMMENT"

    def test_issue_status(self):
        assert IssueStatus.OPEN.value == "OPEN"
        assert IssueStatus.RESOLVED.value == "RESOLVED"
        assert IssueStatus.WONT_FIX.value == "WONT_FIX"


# ============================================================
# Model Tests
# ============================================================


class TestDatasetJobModel:
    def test_defaults(self):
        job = DatasetJob(job_id="j1", dataset_key="financial_statements")
        assert job.status == JobStatus.PENDING
        assert job.triggered_by == "manual"
        assert job.total_records == 0
        assert job.success_count == 0
        assert job.fail_count == 0

    def test_with_optional_fields(self):
        job = DatasetJob(
            job_id="j1",
            dataset_key="financial_statements",
            source="akshare",
            triggered_by="scheduled",
        )
        assert job.source == "akshare"
        assert job.triggered_by == "scheduled"

    def test_from_dict(self):
        data = {"job_id": "j1", "dataset_key": "test_ds"}
        job = DatasetJob(**data)
        assert job.dataset_key == "test_ds"


class TestRawSnapshotModel:
    def test_creation(self):
        snap = RawSnapshot(
            snapshot_id="s1",
            job_id="j1",
            dataset_key="financial_statements",
            source="akshare",
            business_key="600519:2024Q3",
            raw_data={"revenue": 1000000},
        )
        assert snap.raw_data == {"revenue": 1000000}
        assert snap.dataset_key == "financial_statements"


        assert snap.business_key == "600519:2024Q3"


class TestNormalizedCandidateModel:
    def test_defaults(self):
        c = NormalizedCandidate(
            candidate_id="c1",
            snapshot_id="s1",
            job_id="j1",
            dataset_key="financial_statements",
            source="akshare",
            business_key="SSE:600519:2024Q3:income_statement",
        )
        assert c.state == PipelineState.RAW_INGESTED
        assert c.version == 1
        assert c.confidence_score is None

    def test_with_confidence(self):
        c = NormalizedCandidate(
            candidate_id="c1",
            snapshot_id="s1",
            job_id="j1",
            dataset_key="financial_statements",
            source="akshare",
            business_key="SSE:600519:2024Q3:income_statement",
            confidence_score=0.85,
            comparison_result={"fields_changed": 3},
        )
        assert c.confidence_score == 0.85
        assert c.comparison_result == {"fields_changed": 3}

    def test_confidence_score_bounds_high(self):
        with pytest.raises(Exception):
            NormalizedCandidate(
                candidate_id="c1",
                snapshot_id="s1",
                job_id="j1",
                dataset_key="test",
                source="akshare",
                business_key="test",
                confidence_score=1.5,
            )

    def test_confidence_score_negative(self):
        with pytest.raises(Exception):
            NormalizedCandidate(
                candidate_id="c1",
                snapshot_id="s1",
                job_id="j1",
                dataset_key="test",
                source="akshare",
                business_key="test",
                confidence_score=-0.1,
            )

    def test_valid_confidence_range(self):
        c = NormalizedCandidate(
            candidate_id="c1",
            snapshot_id="s1",
            job_id="j1",
            dataset_key="test",
            source="akshare",
            business_key="test",
            confidence_score=0.0,
        )
        assert c.confidence_score == 0.0

        c = NormalizedCandidate(
            candidate_id="c2",
            snapshot_id="s1",
            job_id="j1",
            dataset_key="test",
            source="akshare",
            business_key="test",
            confidence_score=1.0,
        )
        assert c.confidence_score == 1.0


class TestCanonicalRecordModel:
    def test_defaults(self):
        r = CanonicalRecord(
            canonical_id="can1",
            dataset_key="financial_statements",
            business_key="SSE:600519:2024Q3:income_statement",
        )
        assert r.version == 1
        assert r.source == "auto"
        assert r.data == {}

    def test_with_data(self):
        r = CanonicalRecord(
            canonical_id="can1",
            dataset_key="financial_statements",
            business_key="SSE:600519:2024Q3:income_statement",
            data={"revenue": 1000000},
            version=2,
            source="approved",
        )
        assert r.version == 2
        assert r.source == "approved"


class TestValidationIssueModel:
    def test_defaults(self):
        v = ValidationIssue(
            issue_id="v1",
            candidate_id="c1",
            dataset_key="financial_statements",
            rule_name="revenue_positive",
        )
        assert v.severity == ValidationSeverity.WARNING
        assert v.status == IssueStatus.OPEN


class TestApprovalTaskModel:
    def test_defaults(self):
        t = ApprovalTask(
            task_id="t1",
            candidate_id="c1",
            dataset_key="financial_statements",
            business_key="SSE:600519:2024Q3:income_statement",
        )
        assert t.is_resolved is False


class TestApprovalActionRecordModel:
    def test_defaults(self):
        a = ApprovalActionRecord(
            action_id="a1",
            task_id="t1",
            reviewer="admin",
        )
        assert a.action == ApprovalAction.COMMENT


class TestDatasetRegistryEntry:
    def test_defaults(self):
        e = DatasetRegistryEntry(dataset_key="financial_statements")
        assert e.soft_ttl_hours == 24
        assert e.hard_ttl_hours == 168
        assert e.auto_publish_threshold == 0.8
        assert e.source_priority == ["akshare", "tushare"]
        assert e.is_active is True
