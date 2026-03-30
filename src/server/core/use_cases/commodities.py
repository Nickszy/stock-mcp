# src/server/core/use_cases/commodities.py
"""Use cases for commodity asset data (gold, silver, crude oil, copper, industrial metals)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from src.server.core.dependencies import Container
from src.server.utils.logger import logger


async def get_commodity_price(
    symbol: str = "AU0", days: int = 60
) -> Dict[str, Any]:
    """Get commodity futures price history."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_commodity_price", symbol=symbol, days=days)
    return await manager.get_futures_main(symbol=symbol, days=days)


async def get_industrial_metals_overview(days: int = 30) -> Dict[str, Any]:
    """Get aggregated industrial metals overview (copper, aluminum, zinc, rebar)."""
    indicators: Dict[str, Any] = {}
    errors: list[str] = []

    async def _safe(label: str, coro):
        try:
            indicators[label] = await coro
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    await asyncio.gather(
        _safe("copper", get_commodity_price("CU0", days)),
        _safe("aluminum", get_commodity_price("AL0", days)),
        _safe("zinc", get_commodity_price("ZN0", days)),
        _safe("rebar", get_commodity_price("RB0", days)),
    )

    return {"indicators": indicators, "errors": errors, "source": "akshare"}


async def get_commodity_overview() -> Dict[str, Any]:
    """Get aggregated commodity market overview."""
    indicators: Dict[str, Any] = {}
    errors: list[str] = []

    async def _safe(label: str, coro):
        try:
            indicators[label] = await coro
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    await asyncio.gather(
        _safe("gold", get_commodity_price("AU0", 30)),
        _safe("silver", get_commodity_price("AG0", 30)),
        _safe("crude_oil", get_commodity_price("SC0", 30)),
        _safe("copper", get_commodity_price("CU0", 30)),
    )

    return {"indicators": indicators, "errors": errors, "source": "akshare"}
