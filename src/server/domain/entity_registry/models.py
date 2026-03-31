# src/server/domain/entity_registry/models.py
"""Pydantic models for the entity registry.

Design principle: asset_master remains the canonical identity table (UUID-based).
Entity registry tables EXTEND it — adding classification, relations, events,
and market snapshots.  All tables use asset_id FK to join back.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .enums import (
    ClassificationScheme,
    EntityEventType,
    EntityStatus,
    MarketCapTier,
    RelationType,
)


# ---------------------------------------------------------------------------
# Entity Profile — enriched view layered on top of asset_master
# ---------------------------------------------------------------------------

class EntityProfile(BaseModel):
    """Enrichment layer sitting on top of asset_master.

    This stores fields that security_master doesn't carry:
    status lifecycle, Chinese/English names, listing/delisting dates, etc.
    """

    profile_id: str
    asset_id: str = Field(..., description="FK → asset_master.asset_id")
    status: EntityStatus = EntityStatus.ACTIVE
    name_zh: Optional[str] = Field(None, description="中文名 (e.g. 贵州茅台)")
    name_en: Optional[str] = Field(None, description="English name (e.g. Kweichow Moutai)")
    name_short: Optional[str] = Field(None, description="简称 (e.g. 茅台)")
    listing_date: Optional[date] = None
    delisting_date: Optional[date] = None
    isin: Optional[str] = None
    description: Optional[str] = Field(None, description="Brief business description")
    website: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Entity Classification — industry taxonomy
# ---------------------------------------------------------------------------

class EntityClassification(BaseModel):
    """Industry/sector classification for an entity.

    One entity can have multiple classifications under different schemes
    (e.g. GICS level-1, SW level-2, concept tags).
    """

    classification_id: str
    asset_id: str = Field(..., description="FK → asset_master.asset_id")
    scheme: ClassificationScheme
    level: int = Field(1, description="Hierarchy depth (1=sector, 2=industry, 3=sub-industry)")
    code: str = Field(..., description="Classification code (e.g. '10' for Energy in GICS)")
    name: Optional[str] = Field(None, description="Classification name (e.g. '能源')")
    effective_date: Optional[date] = None
    source: Optional[str] = Field(None, description="Data source (akshare, tushare, manual)")
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Entity Relation — corporate structure, cross-listing, peers
# ---------------------------------------------------------------------------

class EntityRelation(BaseModel):
    """Directed relationship between two entities."""

    relation_id: str
    from_asset_id: str = Field(..., description="FK → asset_master.asset_id (source)")
    to_asset_id: str = Field(..., description="FK → asset_master.asset_id (target)")
    relation_type: RelationType
    ownership_pct: Optional[float] = Field(None, ge=0, le=100)
    effective_date: Optional[date] = None
    end_date: Optional[date] = None
    source: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(None, description="Extra relation-specific data")
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Entity Event — historical corporate events
# ---------------------------------------------------------------------------

class EntityEvent(BaseModel):
    """A corporate event that affects an entity."""

    event_id: str
    asset_id: str = Field(..., description="FK → asset_master.asset_id")
    event_type: EntityEventType
    event_date: date
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Entity Market Snapshot — periodic market metadata
# ---------------------------------------------------------------------------

class EntityMarketSnapshot(BaseModel):
    """Point-in-time market metadata snapshot (typically end-of-day)."""

    snapshot_id: str
    asset_id: str = Field(..., description="FK → asset_master.asset_id")
    snapshot_date: date
    shares_outstanding: Optional[int] = None
    shares_float: Optional[int] = None
    market_cap: Optional[float] = None
    market_cap_tier: Optional[MarketCapTier] = None
    index_memberships: List[str] = Field(default_factory=list, description='e.g. ["hs300","csi500"]')
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Query / Response helpers
# ---------------------------------------------------------------------------

class EntitySearchResult(BaseModel):
    """Lightweight result returned by entity search."""

    asset_id: str
    name: Optional[str] = None
    name_zh: Optional[str] = None
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    asset_type: Optional[str] = None
    status: EntityStatus = EntityStatus.ACTIVE
    classifications: List[EntityClassification] = Field(default_factory=list)


class EntityDetail(BaseModel):
    """Full entity detail — profile + latest classifications + relations."""

    profile: EntityProfile
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    asset_type: Optional[str] = None
    classifications: List[EntityClassification] = Field(default_factory=list)
    relations: List[EntityRelation] = Field(default_factory=list)
    recent_events: List[EntityEvent] = Field(default_factory=list)
    latest_snapshot: Optional[EntityMarketSnapshot] = None
