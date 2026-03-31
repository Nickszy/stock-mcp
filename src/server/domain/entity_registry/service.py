# src/server/domain/entity_registry/service.py
"""Entity Registry service — business logic on top of the repository.

Key responsibilities:
- Bulk import from existing security_master data
- Enrichment orchestration (fetch classifications from adapters)
- Cross-system entity resolution (for research-brain integration)
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger

from .repository import EntityRegistryRepository


class EntityRegistryService:
    """High-level operations on the entity registry."""

    def __init__(
        self,
        repo: EntityRegistryRepository,
        security_master_repo=None,
    ):
        self._repo = repo
        self._sm = security_master_repo

    # ── Bulk import ────────────────────────────────────────────────────

    async def import_from_security_master(self, *, limit: int = 500) -> int:
        """Scan asset_master for entities without a profile and create one.

        This bridges the lazy-populated security_master to the entity registry.
        Returns count of newly created profiles.
        """
        pool = await self._repo._get_pool()
        if not pool:
            return 0

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT am.asset_id, am.name, am.asset_type, am.country,
                       al.exchange, al.ticker
                FROM asset_master am
                LEFT JOIN asset_listing al ON al.asset_id = am.asset_id AND al.is_primary = TRUE
                LEFT JOIN entity_profile ep ON ep.asset_id = am.asset_id
                WHERE ep.profile_id IS NULL
                ORDER BY am.created_at DESC
                LIMIT $1
                """,
                limit,
            )

        count = 0
        for row in rows:
            try:
                await self._repo.upsert_profile(
                    asset_id=str(row["asset_id"]),
                    status="active",
                    name_zh=row["name"],
                )
                count += 1
            except Exception as e:
                logger.warning(
                    "Failed to import entity profile",
                    asset_id=str(row["asset_id"]),
                    error=str(e),
                )

        if count:
            logger.info("EntityRegistry: imported from security_master", count=count)
        return count

    # ── Entity lookup helpers (for research-brain) ─────────────────────

    async def resolve_entity(
        self,
        *,
        ticker: Optional[str] = None,
        name: Optional[str] = None,
        asset_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve an entity by ticker, name, or asset_id.

        This is the primary integration point for research-brain:
        given a fuzzy reference from a PDF/opinion, find the canonical entity.
        """
        if asset_id:
            return await self._repo.get_entity_detail(asset_id)

        if not self._sm:
            return None

        # Try security_master lookup first
        candidates = []

        if ticker:
            # Try direct listing lookup
            parts = ticker.split(":")
            if len(parts) == 2:
                result = await self._sm.find_by_listing(parts[0], parts[1])
                if result:
                    candidates.append(result)

        if not candidates and name:
            # Try alias/fuzzy search
            candidates = await self._sm.find_candidates(name)

        if not candidates and ticker:
            candidates = await self._sm.find_candidates(ticker)

        if not candidates:
            return None

        # Pick best candidate
        best = candidates[0]
        aid = str(best.get("asset_id", ""))
        if not aid:
            return None

        # Ensure profile exists
        profile = await self._repo.get_profile_by_asset_id(aid)
        if not profile:
            await self._repo.upsert_profile(
                asset_id=aid,
                name_zh=best.get("name"),
            )

        return await self._repo.get_entity_detail(aid)

    # ── Classification helpers ─────────────────────────────────────────

    async def set_industry(
        self,
        asset_id: str,
        *,
        sw_name: Optional[str] = None,
        sw_code: Optional[str] = None,
        citic_name: Optional[str] = None,
        citic_code: Optional[str] = None,
        citic_level: int = 1,
        source: str = "manual",
    ) -> None:
        """Convenience: set 申万 + 中信 industry in one call.

        Best practice: 一级看申万, 细分看中信.
        """
        if sw_code:
            await self._repo.upsert_classification(
                asset_id, scheme="sw_industry", code=sw_code,
                level=1, name=sw_name, source=source,
            )
        if citic_code:
            await self._repo.upsert_classification(
                asset_id, scheme="citic", code=citic_code,
                level=citic_level, name=citic_name, source=source,
            )

    async def get_peers(
        self,
        asset_id: str,
        *,
        scheme: str = "sw_industry",
        level: int = 1,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Find peer entities — same industry classification."""
        classifications = await self._repo.get_classifications(
            asset_id, scheme=scheme,
        )
        if not classifications:
            return []

        # Use the latest classification at the requested level
        target = None
        for c in classifications:
            if c.get("level") == level:
                target = c
                break

        if not target:
            return []

        peers = await self._repo.find_by_classification(
            scheme=scheme,
            code=target["code"],
            level=level,
            limit=limit + 1,  # +1 to exclude self
        )

        # Exclude self
        return [p for p in peers if str(p.get("asset_id")) != asset_id][:limit]

    # ── Cross-listing / A+H helper ─────────────────────────────────────

    async def link_cross_listed(
        self,
        a_share_asset_id: str,
        h_share_asset_id: str,
        *,
        source: str = "manual",
    ) -> None:
        """Link A-share and H-share of the same company."""
        await self._repo.add_relation(
            from_asset_id=a_share_asset_id,
            to_asset_id=h_share_asset_id,
            relation_type="cross_listed",
            source=source,
        )
        # Bidirectional
        await self._repo.add_relation(
            from_asset_id=h_share_asset_id,
            to_asset_id=a_share_asset_id,
            relation_type="cross_listed",
            source=source,
        )

    # ── Stats ──────────────────────────────────────────────────────────

    async def get_stats(self) -> Dict[str, Any]:
        """Get entity registry statistics."""
        pool = await self._repo._get_pool()
        if not pool:
            return {}

        async with pool.acquire() as conn:
            profile_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_profile"
            )
            classification_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_classification"
            )
            relation_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_relation"
            )
            event_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_event"
            )
            snapshot_count = await conn.fetchval(
                "SELECT COUNT(*) FROM entity_market_snapshot"
            )

        return {
            "profiles": profile_count or 0,
            "classifications": classification_count or 0,
            "relations": relation_count or 0,
            "events": event_count or 0,
            "market_snapshots": snapshot_count or 0,
        }
