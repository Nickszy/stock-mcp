# src/server/mcp/tools/watchlist_tools.py
"""MCP tools for watchlist management."""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

from src.server.domain.watchlist import RedisWatchlistRepository, WatchlistService
from src.server.core.dependencies import Container
from src.server.utils.logger import logger


def _get_service() -> WatchlistService:
    redis_conn = Container.redis()
    repo = RedisWatchlistRepository(redis_conn)
    return WatchlistService(repo)


def register_watchlist_tools(mcp: FastMCP) -> None:

    @mcp.tool()
    async def create_watchlist(
        user_id: str,
        name: str,
        description: Optional[str] = None,
    ) -> dict:
        """创建自选股组合。用户可以创建多个组合来管理不同的投资策略。"""
        service = _get_service()
        watchlist = await service.create_watchlist(
            user_id=user_id,
            name=name,
            description=description,
        )
        return watchlist.model_dump(mode="json")

    @mcp.tool()
    async def list_watchlists(user_id: str) -> dict:
        """列出用户的所有自选股组合。"""
        service = _get_service()
        watchlists = await service.list_watchlists(user_id)
        return {
            "user_id": user_id,
            "total": len(watchlists),
            "watchlists": [w.model_dump(mode="json") for w in watchlists],
        }

    @mcp.tool()
    async def add_watchlist_position(
        user_id: str,
        watchlist_id: str,
        ticker: str,
        quantity: float,
        average_cost: float,
        notes: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """向自选股组合中添加持仓。ticker 格式为 EXCHANGE:SYMBOL（如 SSE:600519）。"""
        service = _get_service()
        watchlist = await service.add_position(
            user_id=user_id,
            watchlist_id=watchlist_id,
            ticker=ticker,
            quantity=quantity,
            average_cost=average_cost,
            notes=notes,
            tags=tags,
        )
        return watchlist.model_dump(mode="json")

    @mcp.tool()
    async def remove_watchlist_position(
        user_id: str,
        watchlist_id: str,
        ticker: str,
    ) -> dict:
        """从自选股组合中移除指定持仓。"""
        service = _get_service()
        removed = await service.remove_position(user_id, watchlist_id, ticker)
        return {"removed": removed, "ticker": ticker.upper()}
