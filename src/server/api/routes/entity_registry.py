# src/server/api/routes/entity_registry.py
"""REST API routes for the Entity Registry.

Provides endpoints for entity profile management, classification lookup,
relation queries, and market snapshot retrieval.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.server.utils.logger import logger


router = APIRouter(prefix="/entity", tags=["entity-registry"])

# Module-level service reference — injected by bootstrap
_service = None
_repo = None


def set_entity_registry_components(*, service, repo) -> None:
    """Called by bootstrap to inject service + repo."""
    global _service, _repo
    _service = service
    _repo = repo


# ── Profile endpoints ──────────────────────────────────────────────────

@router.get("/search")
async def search_entities(
    q: Optional[str] = Query(None, description="Name query (fuzzy)"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Search entity profiles."""
    if not _repo:
        raise HTTPException(503, "Entity registry not initialized")

    results = await _repo.search_profiles(
        status=status, name_query=q, limit=limit, offset=offset,
    )
    return {"data": results, "count": len(results)}


@router.get("/resolve")
async def resolve_entity(
    ticker: Optional[str] = Query(None, description="EXCHANGE:SYMBOL"),
    name: Optional[str] = Query(None, description="Entity name (fuzzy)"),
    asset_id: Optional[str] = Query(None, description="Asset UUID"),
):
    """Resolve an entity by ticker, name, or asset_id.

    Primary integration point for research-brain.
    """
    if not _service:
        raise HTTPException(503, "Entity registry not initialized")

    if not ticker and not name and not asset_id:
        raise HTTPException(400, "Provide at least one of: ticker, name, asset_id")

    result = await _service.resolve_entity(
        ticker=ticker, name=name, asset_id=asset_id,
    )
    if not result:
        raise HTTPException(404, "Entity not found")

    return {"data": result}


@router.get("/{asset_id}")
async def get_entity_detail(asset_id: str):
    """Get full entity detail: profile + classifications + relations + events + snapshot."""
    if not _repo:
        raise HTTPException(503, "Entity registry not initialized")

    detail = await _repo.get_entity_detail(asset_id)
    if not detail:
        raise HTTPException(404, "Entity not found")

    return {"data": detail}


# ── Classification endpoints ───────────────────────────────────────────

@router.get("/{asset_id}/classifications")
async def get_classifications(
    asset_id: str,
    scheme: Optional[str] = Query(None, description="Filter by scheme (sw_industry, citic, gics, concept)"),
):
    """Get classifications for an entity."""
    if not _repo:
        raise HTTPException(503, "Entity registry not initialized")

    result = await _repo.get_classifications(asset_id, scheme=scheme)
    return {"data": result}


@router.get("/classification/members")
async def get_classification_members(
    scheme: str = Query(..., description="Classification scheme"),
    code: str = Query(..., description="Classification code"),
    level: int = Query(1, description="Hierarchy level"),
    limit: int = Query(100, ge=1, le=500),
):
    """Find all entities in a given classification."""
    if not _repo:
        raise HTTPException(503, "Entity registry not initialized")

    result = await _repo.find_by_classification(
        scheme=scheme, code=code, level=level, limit=limit,
    )
    return {"data": result, "count": len(result)}


# ── Peers endpoint ─────────────────────────────────────────────────────

@router.get("/{asset_id}/peers")
async def get_peers(
    asset_id: str,
    scheme: str = Query("sw_industry", description="Classification scheme for peer matching"),
    level: int = Query(1, description="Classification level"),
    limit: int = Query(20, ge=1, le=100),
):
    """Find peer entities in the same industry."""
    if not _service:
        raise HTTPException(503, "Entity registry not initialized")

    peers = await _service.get_peers(
        asset_id, scheme=scheme, level=level, limit=limit,
    )
    return {"data": peers, "count": len(peers)}


# ── Relations endpoint ─────────────────────────────────────────────────

@router.get("/{asset_id}/relations")
async def get_relations(
    asset_id: str,
    relation_type: Optional[str] = Query(None, description="Filter by type"),
    direction: str = Query("both", description="outgoing, incoming, or both"),
):
    """Get relations for an entity."""
    if not _repo:
        raise HTTPException(503, "Entity registry not initialized")

    result = await _repo.get_relations(
        asset_id, relation_type=relation_type, direction=direction,
    )
    return {"data": result}


# ── Events endpoint ────────────────────────────────────────────────────

@router.get("/{asset_id}/events")
async def get_events(
    asset_id: str,
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    limit: int = Query(50, ge=1, le=200),
):
    """Get corporate events for an entity."""
    if not _repo:
        raise HTTPException(503, "Entity registry not initialized")

    result = await _repo.get_events(
        asset_id, event_type=event_type, limit=limit,
    )
    return {"data": result}


# ── Market Snapshot endpoint ───────────────────────────────────────────

@router.get("/{asset_id}/snapshot")
async def get_latest_snapshot(asset_id: str):
    """Get the latest market snapshot for an entity."""
    if not _repo:
        raise HTTPException(503, "Entity registry not initialized")

    result = await _repo.get_latest_snapshot(asset_id)
    if not result:
        raise HTTPException(404, "No snapshot found")

    return {"data": result}


@router.get("/{asset_id}/snapshots")
async def get_snapshot_history(
    asset_id: str,
    limit: int = Query(30, ge=1, le=365),
):
    """Get market snapshot history for an entity."""
    if not _repo:
        raise HTTPException(503, "Entity registry not initialized")

    result = await _repo.get_snapshot_history(asset_id, limit=limit)
    return {"data": result, "count": len(result)}


# ── Admin: import + stats ──────────────────────────────────────────────

@router.post("/admin/import-from-security-master")
async def import_from_security_master(limit: int = Query(500, ge=1, le=5000)):
    """Bulk import entities from security_master that don't have profiles yet."""
    if not _service:
        raise HTTPException(503, "Entity registry not initialized")

    count = await _service.import_from_security_master(limit=limit)
    return {"imported": count}


@router.get("/admin/stats")
async def get_stats():
    """Get entity registry statistics."""
    if not _service:
        raise HTTPException(503, "Entity registry not initialized")

    stats = await _service.get_stats()
    return {"data": stats}
