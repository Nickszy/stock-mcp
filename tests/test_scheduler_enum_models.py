from __future__ import annotations


def test_structured_data_models_generate_json_schema_with_enum_fields():
    from src.server.domain.structured_data.models import (
        ApprovalActionRecord,
        DatasetJob,
        NormalizedCandidate,
        ValidationIssue,
    )

    job_schema = DatasetJob.model_json_schema()
    candidate_schema = NormalizedCandidate.model_json_schema()
    issue_schema = ValidationIssue.model_json_schema()
    action_schema = ApprovalActionRecord.model_json_schema()

    assert job_schema["properties"]["status"]["$ref"]
    assert candidate_schema["properties"]["state"]["$ref"]
    assert issue_schema["properties"]["severity"]["$ref"]
    assert action_schema["properties"]["action"]["$ref"]


def test_scheduler_registry_models_generate_json_schema_with_refresh_trigger_enum():
    from pydantic import BaseModel

    from src.server.domain.structured_data.registry import RefreshTrigger

    class SchedulerRequest(BaseModel):
        trigger: RefreshTrigger = RefreshTrigger.ON_DEMAND

    schema = SchedulerRequest.model_json_schema()

    assert schema["properties"]["trigger"]["$ref"]
    trigger_defs = schema.get("$defs", {})
    assert "RefreshTrigger" in trigger_defs
    assert trigger_defs["RefreshTrigger"]["type"] == "string"
    assert "on_demand" in trigger_defs["RefreshTrigger"]["enum"]
