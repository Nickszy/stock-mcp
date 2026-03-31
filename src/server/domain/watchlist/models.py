from __future__ import annotations

from datetime import datetime, UTC
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class WatchlistPosition(BaseModel):
    ticker: str = Field(..., description="Standardized ticker format: EXCHANGE:SYMBOL")
    quantity: float = Field(..., ge=0)
    average_cost: float = Field(..., ge=0)
    notes: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    added_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("ticker")
    @classmethod
    def validate_ticker_format(cls, value: str) -> str:
        normalized = value.upper()
        if ":" not in normalized:
            raise ValueError("Ticker must be in format 'EXCHANGE:SYMBOL'")
        exchange, symbol = normalized.split(":", 1)
        if not exchange or not symbol:
            raise ValueError("Ticker must be in format 'EXCHANGE:SYMBOL'")
        return normalized


class Watchlist(BaseModel):
    watchlist_id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    name: str
    description: Optional[str] = None
    positions: list[WatchlistPosition] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
