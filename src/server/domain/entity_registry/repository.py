# src/server/domain/entity_registry/repository.py
"""Entity Registry repository — extends security_master with enrichment tables.

Design decisions:
- Follows the project's `ensure_schema()` + raw asyncpg pattern (no ORM).
- All new tables FK to asset_master.asset_id — no separate identity table.
- asset_master + asset_listing + asset_alias remain in security_master; we only READ them.
- This module WRITES to: entity_profile, entity_classification, entity_relation,
  entity_event, entity_market_snapshot.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.server.utils.logger import logger


# ── SQL DDL ────────────────────────────────────────────────────────────────

_DDL_ENTITY_PROFILE = """
CREATE TABLE IF NOT EXISTS entity_profile (
    profile_id          UUID PRIMARY KEY,
    asset_id            UUID NOT NULL UNIQUE REFERENCES asset_master(asset_id) ON DELETE CASCADE,
    status              TEXT NOT NULL DEFAULT 'active',
    name_zh             TEXT,
    name_en             TEXT,
    name_short          TEXT,
    listing_date        DATE,
    delisting_date      DATE,
    isin                TEXT,
    description         TEXT,
    website             TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_entity_profile_asset_id ON entity_profile(asset_id);
CREATE INDEX IF NOT EXISTS idx_entity_profile_status ON entity_profile(status);
"""

_DDL_ENTITY_CLASSIFICATION = """
CREATE TABLE IF NOT EXISTS entity_classification (
    classification_id   UUID PRIMARY KEY,
    asset_id            UUID NOT NULL REFERENCES asset_master(asset_id) ON DELETE CASCADE,
    scheme              TEXT NOT NULL,
    level               INT NOT NULL DEFAULT 1,
    code                TEXT NOT NULL,
    name                TEXT,
    effective_date      DATE,
    source              TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(asset_id, scheme, level, effective_date)
);
CREATE INDEX IF NOT EXISTS idx_entity_classification_asset_id ON entity_classification(asset_id);
CREATE INDEX IF NOT EXISTS idx_entity_classification_scheme ON entity_classification(scheme, code);
"""

_DDL_ENTITY_RELATION = """
CREATE TABLE IF NOT EXISTS entity_relation (
    relation_id         UUID PRIMARY KEY,
    from_asset_id       UUID NOT NULL REFERENCES asset_master(asset_id) ON DELETE CASCADE,
    to_asset_id         UUID NOT NULL REFERENCES asset_master(asset_id) ON DELETE CASCADE,
    relation_type       TEXT NOT NULL,
    ownership_pct       NUMERIC(7,4),
    effective_date      DATE,
    end_date            DATE,
    source              TEXT,
    metadata            JSONB,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(from_asset_id, to_asset_id, relation_type, effective_date)
);
CREATE INDEX IF NOT EXISTS idx_entity_relation_from ON entity_relation(from_asset_id);
CREATE INDEX IF NOT EXISTS idx_entity_relation_to ON entity_relation(to_asset_id);
CREATE INDEX IF NOT EXISTS idx_entity_relation_type ON entity_relation(relation_type);
"""

_DDL_ENTITY_EVENT = """
CREATE TABLE IF NOT EXISTS entity_event (
    event_id            UUID PRIMARY KEY,
    asset_id            UUID NOT NULL REFERENCES asset_master(asset_id) ON DELETE CASCADE,
    event_type          TEXT NOT NULL,
    event_date          DATE NOT NULL,
    old_value           TEXT,
    new_value           TEXT,
    description         TEXT,
    source              TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_entity_event_asset_date ON entity_event(asset_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_entity_event_type ON entity_event(event_type);
"""

_DDL_ENTITY_MARKET_SNAPSHOT = """
CREATE TABLE IF NOT EXISTS entity_market_snapshot (
    snapshot_id         UUID PRIMARY KEY,
    asset_id            UUID NOT NULL REFERENCES asset_master(asset_id) ON DELETE CASCADE,
    snapshot_date       DATE NOT NULL,
    shares_outstanding  BIGINT,
    shares_float        BIGINT,
    market_cap          NUMERIC(20,2),
    market_cap_tier     TEXT,
    index_memberships   TEXT[],
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(asset_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_entity_market_snapshot_asset_date
    ON entity_market_snapshot(asset_id, snapshot_date DESC);
"""


class EntityRegistryRepository:
    """Repository for entity registry tables — extends security_master."""

    def __init__(self, postgres_conn):
        self._pg = postgres_conn

    async def _get_pool(self):
        if not self._pg.connected:
            ok = await self._pg.connect()
            if not ok:
                return None
        return self._pg.get_client()

    # ── Schema Management ──────────────────────────────────────────────

    async def ensure_schema(self) -> bool:
        """Create all entity_registry tables (idempotent)."""
        pool = await self._get_pool()
        if not pool:
            logger.warning("EntityRegistry: PostgreSQL not available, schema not created")
            return False

        async with pool.acquire() as conn:
            for ddl in [
                _DDL_ENTITY_PROFILE,
                _DDL_ENTITY_CLASSIFICATION,
                _DDL_ENTITY_RELATION,
                _DDL_ENTITY_EVENT,
                _DDL_ENTITY_MARKET_SNAPSHOT,
            ]:
                await conn.execute(ddl)

        logger.info("✅ EntityRegistry schema ensured")
        return True

    # ── Entity Profile ─────────────────────────────────────────────────

    async def upsert_profile(
        self,
        asset_id: str,
        *,
        status: str = "active",
        name_zh: Optional[str] = None,
        name_en: Optional[str] = None,
        name_short: Optional[str] = None,
        listing_date: Optional[date] = None,
        delisting_date: Optional[date] = None,
        isin: Optional[str] = None,
        description: Optional[str] = None,
        website: Optional[str] = None,
    ) -> str:
        """Upsert an entity profile. Returns profile_id."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        profile_id = str(uuid4())
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO entity_profile
                    (profile_id, asset_id, status, name_zh, name_en, name_short,
                     listing_date, delisting_date, isin, description, website)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (asset_id) DO UPDATE SET
                    status = COALESCE(EXCLUDED.status, entity_profile.status),
                    name_zh = COALESCE(EXCLUDED.name_zh, entity_profile.name_zh),
                    name_en = COALESCE(EXCLUDED.name_en, entity_profile.name_en),
                    name_short = COALESCE(EXCLUDED.name_short, entity_profile.name_short),
                    listing_date = COALESCE(EXCLUDED.listing_date, entity_profile.listing_date),
                    delisting_date = COALESCE(EXCLUDED.delisting_date, entity_profile.delisting_date),
                    isin = COALESCE(EXCLUDED.isin, entity_profile.isin),
                    description = COALESCE(EXCLUDED.description, entity_profile.description),
                    website = COALESCE(EXCLUDED.website, entity_profile.website),
                    updated_at = NOW()
                RETURNING profile_id
                """,
                profile_id, asset_id, status, name_zh, name_en, name_short,
                listing_date, delisting_date, isin, description, website,
            )
            return str(row["profile_id"])

    async def get_profile_by_asset_id(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """Get entity profile by asset_id."""
        pool = await self._get_pool()
        if not pool:
            return None

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM entity_profile WHERE asset_id = $1", asset_id,
            )
            return dict(row) if row else None

    async def search_profiles(
        self,
        *,
        status: Optional[str] = None,
        name_query: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Search entity profiles with optional filters."""
        pool = await self._get_pool()
        if not pool:
            return []

        conditions: List[str] = []
        params: List[Any] = []
        idx = 1

        if status:
            conditions.append(f"ep.status = ${idx}")
            params.append(status)
            idx += 1

        if name_query:
            conditions.append(
                f"(ep.name_zh ILIKE ${idx} OR ep.name_en ILIKE ${idx} "
                f"OR ep.name_short ILIKE ${idx} OR am.name ILIKE ${idx})"
            )
            params.append(f"%{name_query}%")
            idx += 1

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        params.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT ep.*, am.name AS master_name, am.asset_type,
                       al.exchange, al.ticker
                FROM entity_profile ep
                JOIN asset_master am ON am.asset_id = ep.asset_id
                LEFT JOIN asset_listing al ON al.asset_id = ep.asset_id AND al.is_primary = TRUE
                {where}
                ORDER BY ep.updated_at DESC
                LIMIT ${idx} OFFSET ${idx + 1}
                """,
                *params,
            )
            return [dict(r) for r in rows]

    # ── Classification ─────────────────────────────────────────────────

    async def upsert_classification(
        self,
        asset_id: str,
        scheme: str,
        code: str,
        *,
        level: int = 1,
        name: Optional[str] = None,
        effective_date: Optional[date] = None,
        source: Optional[str] = None,
    ) -> str:
        """Upsert a classification record. Returns classification_id."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        cid = str(uuid4())
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO entity_classification
                    (classification_id, asset_id, scheme, level, code, name,
                     effective_date, source)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (asset_id, scheme, level, effective_date) DO UPDATE SET
                    code = EXCLUDED.code,
                    name = COALESCE(EXCLUDED.name, entity_classification.name),
                    source = COALESCE(EXCLUDED.source, entity_classification.source)
                RETURNING classification_id
                """,
                cid, asset_id, scheme, level, code, name, effective_date, source,
            )
            return str(row["classification_id"])

    async def get_classifications(
        self, asset_id: str, *, scheme: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get classifications for an entity."""
        pool = await self._get_pool()
        if not pool:
            return []

        async with pool.acquire() as conn:
            if scheme:
                rows = await conn.fetch(
                    """
                    SELECT * FROM entity_classification
                    WHERE asset_id = $1 AND scheme = $2
                    ORDER BY level, effective_date DESC
                    """,
                    asset_id, scheme,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM entity_classification
                    WHERE asset_id = $1
                    ORDER BY scheme, level, effective_date DESC
                    """,
                    asset_id,
                )
            return [dict(r) for r in rows]

    async def find_by_classification(
        self,
        scheme: str,
        code: str,
        *,
        level: int = 1,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Find entities by classification (e.g. all stocks in SW industry '银行')."""
        pool = await self._get_pool()
        if not pool:
            return []

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT ec.*, am.name, am.asset_type,
                       al.exchange, al.ticker
                FROM entity_classification ec
                JOIN asset_master am ON am.asset_id = ec.asset_id
                LEFT JOIN asset_listing al ON al.asset_id = ec.asset_id AND al.is_primary = TRUE
                WHERE ec.scheme = $1 AND ec.code = $2 AND ec.level = $3
                ORDER BY am.name
                LIMIT $4
                """,
                scheme, code, level, limit,
            )
            return [dict(r) for r in rows]

    # ── Relations ──────────────────────────────────────────────────────

    async def add_relation(
        self,
        from_asset_id: str,
        to_asset_id: str,
        relation_type: str,
        *,
        ownership_pct: Optional[float] = None,
        effective_date: Optional[date] = None,
        end_date: Optional[date] = None,
        source: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a directed relationship. Returns relation_id."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        rid = str(uuid4())
        import json as _json
        meta_json = _json.dumps(metadata) if metadata else None

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO entity_relation
                    (relation_id, from_asset_id, to_asset_id, relation_type,
                     ownership_pct, effective_date, end_date, source, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                ON CONFLICT (from_asset_id, to_asset_id, relation_type, effective_date)
                    DO UPDATE SET
                        ownership_pct = COALESCE(EXCLUDED.ownership_pct, entity_relation.ownership_pct),
                        end_date = COALESCE(EXCLUDED.end_date, entity_relation.end_date),
                        source = COALESCE(EXCLUDED.source, entity_relation.source),
                        metadata = COALESCE(EXCLUDED.metadata, entity_relation.metadata)
                RETURNING relation_id
                """,
                rid, from_asset_id, to_asset_id, relation_type,
                ownership_pct, effective_date, end_date, source, meta_json,
            )
            return str(row["relation_id"])

    async def get_relations(
        self,
        asset_id: str,
        *,
        relation_type: Optional[str] = None,
        direction: str = "both",
    ) -> List[Dict[str, Any]]:
        """Get relations for an entity.

        direction: 'outgoing' (from this entity), 'incoming' (to this entity), 'both'.
        """
        pool = await self._get_pool()
        if not pool:
            return []

        clauses = []
        params: List[Any] = []
        idx = 1

        if direction in ("outgoing", "both"):
            clauses.append(f"from_asset_id = ${idx}")
        if direction in ("incoming", "both"):
            clauses.append(f"to_asset_id = ${idx}")
        params.append(asset_id)
        idx += 1

        where_entity = " OR ".join(clauses)

        type_filter = ""
        if relation_type:
            type_filter = f" AND relation_type = ${idx}"
            params.append(relation_type)
            idx += 1

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT er.*,
                       f_am.name AS from_name, f_al.ticker AS from_ticker, f_al.exchange AS from_exchange,
                       t_am.name AS to_name, t_al.ticker AS to_ticker, t_al.exchange AS to_exchange
                FROM entity_relation er
                JOIN asset_master f_am ON f_am.asset_id = er.from_asset_id
                LEFT JOIN asset_listing f_al ON f_al.asset_id = er.from_asset_id AND f_al.is_primary = TRUE
                JOIN asset_master t_am ON t_am.asset_id = er.to_asset_id
                LEFT JOIN asset_listing t_al ON t_al.asset_id = er.to_asset_id AND t_al.is_primary = TRUE
                WHERE ({where_entity}){type_filter}
                    AND (er.end_date IS NULL OR er.end_date >= CURRENT_DATE)
                ORDER BY er.created_at DESC
                """,
                *params,
            )
            return [dict(r) for r in rows]

    # ── Events ─────────────────────────────────────────────────────────

    async def add_event(
        self,
        asset_id: str,
        event_type: str,
        event_date: date,
        *,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        description: Optional[str] = None,
        source: Optional[str] = None,
    ) -> str:
        """Record a corporate event. Returns event_id."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        eid = str(uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO entity_event
                    (event_id, asset_id, event_type, event_date,
                     old_value, new_value, description, source)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                eid, asset_id, event_type, event_date,
                old_value, new_value, description, source,
            )
            return eid

    async def get_events(
        self,
        asset_id: str,
        *,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get events for an entity, newest first."""
        pool = await self._get_pool()
        if not pool:
            return []

        async with pool.acquire() as conn:
            if event_type:
                rows = await conn.fetch(
                    """
                    SELECT * FROM entity_event
                    WHERE asset_id = $1 AND event_type = $2
                    ORDER BY event_date DESC LIMIT $3
                    """,
                    asset_id, event_type, limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM entity_event
                    WHERE asset_id = $1
                    ORDER BY event_date DESC LIMIT $2
                    """,
                    asset_id, limit,
                )
            return [dict(r) for r in rows]

    # ── Market Snapshots ───────────────────────────────────────────────

    async def upsert_market_snapshot(
        self,
        asset_id: str,
        snapshot_date: date,
        *,
        shares_outstanding: Optional[int] = None,
        shares_float: Optional[int] = None,
        market_cap: Optional[float] = None,
        market_cap_tier: Optional[str] = None,
        index_memberships: Optional[List[str]] = None,
    ) -> str:
        """Upsert a market snapshot. Returns snapshot_id."""
        pool = await self._get_pool()
        if not pool:
            raise RuntimeError("PostgreSQL not available")

        sid = str(uuid4())
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO entity_market_snapshot
                    (snapshot_id, asset_id, snapshot_date,
                     shares_outstanding, shares_float, market_cap,
                     market_cap_tier, index_memberships)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (asset_id, snapshot_date) DO UPDATE SET
                    shares_outstanding = COALESCE(EXCLUDED.shares_outstanding, entity_market_snapshot.shares_outstanding),
                    shares_float = COALESCE(EXCLUDED.shares_float, entity_market_snapshot.shares_float),
                    market_cap = COALESCE(EXCLUDED.market_cap, entity_market_snapshot.market_cap),
                    market_cap_tier = COALESCE(EXCLUDED.market_cap_tier, entity_market_snapshot.market_cap_tier),
                    index_memberships = COALESCE(EXCLUDED.index_memberships, entity_market_snapshot.index_memberships)
                RETURNING snapshot_id
                """,
                sid, asset_id, snapshot_date,
                shares_outstanding, shares_float, market_cap,
                market_cap_tier, index_memberships,
            )
            return str(row["snapshot_id"])

    async def get_latest_snapshot(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent market snapshot for an entity."""
        pool = await self._get_pool()
        if not pool:
            return None

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM entity_market_snapshot
                WHERE asset_id = $1
                ORDER BY snapshot_date DESC LIMIT 1
                """,
                asset_id,
            )
            return dict(row) if row else None

    async def get_snapshot_history(
        self,
        asset_id: str,
        *,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """Get market snapshot history for an entity."""
        pool = await self._get_pool()
        if not pool:
            return []

        conditions = ["asset_id = $1"]
        params: List[Any] = [asset_id]
        idx = 2

        if start_date:
            conditions.append(f"snapshot_date >= ${idx}")
            params.append(start_date)
            idx += 1
        if end_date:
            conditions.append(f"snapshot_date <= ${idx}")
            params.append(end_date)
            idx += 1

        params.append(limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM entity_market_snapshot
                WHERE {' AND '.join(conditions)}
                ORDER BY snapshot_date DESC
                LIMIT ${idx}
                """,
                *params,
            )
            return [dict(r) for r in rows]

    # ── Aggregate Detail ───────────────────────────────────────────────

    async def get_entity_detail(self, asset_id: str) -> Optional[Dict[str, Any]]:
        """Get full entity detail: profile + classifications + relations + events + snapshot."""
        profile = await self.get_profile_by_asset_id(asset_id)
        if not profile:
            return None

        classifications = await self.get_classifications(asset_id)
        relations = await self.get_relations(asset_id)
        events = await self.get_events(asset_id, limit=10)
        snapshot = await self.get_latest_snapshot(asset_id)

        # Also fetch identity info from asset_master / asset_listing
        pool = await self._get_pool()
        identity = None
        if pool:
            async with pool.acquire() as conn:
                identity = await conn.fetchrow(
                    """
                    SELECT am.*, al.exchange, al.ticker
                    FROM asset_master am
                    LEFT JOIN asset_listing al ON al.asset_id = am.asset_id AND al.is_primary = TRUE
                    WHERE am.asset_id = $1
                    """,
                    asset_id,
                )

        return {
            "identity": dict(identity) if identity else None,
            "profile": profile,
            "classifications": classifications,
            "relations": relations,
            "recent_events": events,
            "latest_snapshot": snapshot,
        }
