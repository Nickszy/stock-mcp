# src/server/domain/board_catalog/service.py
"""Board catalog service — merges PostgreSQL catalog with Redis real-time snapshot."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.server.utils.logger import logger


class BoardCatalogService:
    """Orchestrates board catalog persistence and query.

    - refresh_catalog(): fetch fresh board list from akshare adapter, persist to PG
    - get_concept_list(): read catalog from PG, merge with real-time snapshot from Redis
    """

    def __init__(self, repo, gateway, cache):
        self._repo = repo
        self._gateway = gateway
        self._cache = cache

    async def refresh_catalog(self) -> Dict[str, Any]:
        """Fetch fresh board catalog from akshare and persist to PostgreSQL.

        Returns dict with refresh statistics.
        """
        adapter = self._gateway._akshare_adapter
        if adapter is None:
            raise RuntimeError("akshare adapter not available")

        rows = await adapter.fetch_board_catalog_fresh()
        if not rows:
            return {"total": 0, "upserted": 0, "error": "no data fetched"}

        result = await self._repo.replace_catalog(rows, source="akshare")
        logger.info(
            "BoardCatalog: refresh completed",
            total=result["total"],
            upserted=result["upserted"],
        )
        return result

    async def get_concept_list(self, keyword: str = "") -> Dict[str, Any]:
        """Get concept board list by merging PG catalog + Redis real-time snapshot.

        Falls back to direct gateway call if PG read fails.
        """
        try:
            catalog_rows = await self._repo.list_boards(
                board_type="concept",
                keyword=keyword,
                active_only=True,
            )
        except Exception as e:
            logger.warning(f"BoardCatalog: PG read failed, falling back: {e}")
            return await self._gateway.get_concept_list(keyword=keyword)

        if not catalog_rows:
            # PG table may be empty, fall back
            return await self._gateway.get_concept_list(keyword=keyword)

        # Fetch real-time snapshot from Redis cache
        snapshot_map = await self._load_concept_snapshot()

        results = []
        for row in catalog_rows:
            code = row.get("code", "")
            snap = snapshot_map.get(code, {})
            entry = {
                "code": code,
                "name": row.get("name", ""),
                "board_type": row.get("board_type", ""),
                "change_pct": snap.get("change_pct"),
                "stock_count": snap.get("stock_count"),
                "rise_count": snap.get("rise_count"),
                "fall_count": snap.get("fall_count"),
                "turnover_rate": snap.get("turnover_rate"),
                "amplitude": snap.get("amplitude"),
                "top_stock": snap.get("top_stock", ""),
                "top_stock_change": snap.get("top_stock_change"),
            }
            if "total_market_cap" in snap:
                entry["total_market_cap"] = snap["total_market_cap"]
            results.append(entry)

        return {
            "data": results,
            "total": len(results),
            "source": "postgres+akshare",
        }

    async def _load_concept_snapshot(self) -> Dict[str, Dict[str, Any]]:
        """Load real-time concept snapshot from Redis cache and index by code."""
        try:
            cached = await self._cache.get("akshare:concept_list:snapshot")
            if cached and isinstance(cached, list):
                return {item.get("code", ""): item for item in cached if isinstance(item, dict)}
        except Exception as e:
            logger.warning(f"BoardCatalog: failed to load concept snapshot from Redis: {e}")

        # Cache miss — fetch fresh and build snapshot
        try:
            result = await self._gateway.get_concept_list(keyword="")
            data = result.get("data", [])
            if isinstance(data, list):
                return {item.get("code", ""): item for item in data if isinstance(item, dict)}
        except Exception as e:
            logger.warning(f"BoardCatalog: failed to fetch concept snapshot: {e}")

        return {}
