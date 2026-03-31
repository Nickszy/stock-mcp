# src/server/domain/scheduler/models.py
"""Scheduler domain models — ScheduledAnalysisJob and AnalysisRun."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


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
        description="HH:MM for daily, DOW HH:MM for weekly, 5-field cron for cron",
    )
    analysis_types: list[str] = Field(
        default_factory=lambda: ["news", "filings"],
    )
    enabled: bool = Field(True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_schedule(self) -> "ScheduledAnalysisJob":
        import re

        daily_pattern = r"^(?:[01]?\d|2[0-3]):[0-5]\d$"
        weekly_pattern = (
            r"^(MON|TUE|WED|THU|FRI|SAT|SUN)\s+(?:[01]?\d|2[0-3]):[0-5]\d$"
        )
        cron_pattern = r"^\S+\s+\S+\s+\S+\s+\S+\s+\S+$"

        if self.schedule_type == ScheduleType.daily:
            if not re.match(daily_pattern, self.schedule_value):
                raise ValueError(
                    "daily schedule_value must be HH:MM format (e.g. '09:00')"
                )
        elif self.schedule_type == ScheduleType.weekly:
            if not re.match(weekly_pattern, self.schedule_value):
                raise ValueError(
                    "weekly schedule_value must be 'DOW HH:MM' format (e.g. 'MON 09:00')"
                )
        elif self.schedule_type == ScheduleType.cron:
            if not re.match(cron_pattern, self.schedule_value):
                raise ValueError(
                    "cron schedule_value must be a 5-field cron expression"
                )
        return self

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
    source_counts: dict[str, int] = Field(default_factory=dict)
    available_sources: list[str] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)
    coverage_ratio: float = 0.0
    data_quality: str = "low"
    key_points: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AnalysisRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    status: AnalysisRunStatus = AnalysisRunStatus.queued
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: Optional[datetime] = None
    summary: str = ""
    ai_summary: str = ""
    requested_analysis_types: list[str] = Field(default_factory=list)
    watchlist_size: int = 0
    completed_tickers: int = 0
    failed_tickers: int = 0
    coverage_summary: dict[str, int] = Field(default_factory=dict)
    data_quality_summary: dict[str, int] = Field(default_factory=dict)
    items: list[AnalysisRunItem] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
