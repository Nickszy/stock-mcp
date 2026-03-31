# src/server/domain/scheduler/models.py
"""Scheduler domain models — ScheduledAnalysisJob and AnalysisRun."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class ScheduleType(str, Enum):
    daily = "daily"
    weekly = "weekly"
    cron = "cron"


class AnalysisType(str, Enum):
    news = "news"
    filings = "filings"
    research_reports = "research_reports"
    fact_pack = "fact_pack"

    @classmethod
    def validate_list(cls, values: list[str]) -> list[str]:
        valid = {e.value for e in cls.__members__.values()}
        for v in values:
            if v not in valid:
                raise ValueError(
                    f"Invalid analysis type: {v}. Must be one of {sorted(valid)}"
                )
        return values


class AnalysisRunStatus(str, Enum):
    queued = "queued"
    running = "running"
    success = "success"
    partial = "partial"
    failed = "failed"


class ScheduledAnalysisJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    name: str
    watchlist_id: str
    schedule_type: ScheduleType = ScheduleType.daily
    schedule_value: str = Field(
        default="09:00",
        description="HH:MM for daily, cron expression for weekly/cron",
    )
    analysis_types: list[str] = Field(
        default_factory=lambda: ["news", "filings"],
    )
    enabled: bool = Field(True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    @field_validator("schedule_value")
    @classmethod
    def validate_schedule_value(cls, v: str) -> str:
        import re
        if not re.match(r"^\d{1,2}:\d{2}$", v):
            raise ValueError("schedule_value must be HH:MM format (e.g. '09:00')")
        return v

    @field_validator("analysis_types")
    @classmethod
    def validate_analysis_types(cls, v: list[str]) -> list[str]:
        return AnalysisType.validate_list(v)


class AnalysisRunItem(BaseModel):
    ticker: str
    headline_risks: list[str] = Field(default_factory=list)
    headline_opportunities: list[str] = Field(default_factory=list)
    news_items: list[dict] = Field(default_factory=list)
    filing_items: list[dict] = Field(default_factory=list)
    report_items: list[dict] = Field(default_factory=list)
    fact_snapshot: dict = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AnalysisRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    status: AnalysisRunStatus = AnalysisRunStatus.queued
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: Optional[datetime] = None
    summary: str = ""
    items: list[AnalysisRunItem] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
