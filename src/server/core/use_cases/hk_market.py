# src/server/core/use_cases/hk_market.py
"""Use cases for Hong Kong market data."""

from __future__ import annotations

from typing import Dict, Any

from src.server.core.dependencies import Container
from src.server.utils.logger import logger


async def get_hk_market_spot() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_hk_market_spot")
    return await manager.get_hk_market_spot()


async def get_hk_hot_rank() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_hk_hot_rank")
    return await manager.get_hk_hot_rank()


async def get_hk_main_board() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_hk_main_board")
    return await manager.get_hk_main_board()


async def get_hk_market_overview() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_hk_market_overview")
    return await manager.get_hk_market_overview()
