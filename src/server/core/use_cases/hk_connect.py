# src/server/core/use_cases/hk_connect.py
"""Use cases for HK Connect / southbound flow data."""

from __future__ import annotations

from typing import Dict, Any

from src.server.core.dependencies import Container
from src.server.utils.logger import logger


async def get_hk_connect_components() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_hk_connect_components")
    return await manager.get_hk_connect_components()


async def get_hsgt_fund_flow_summary() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_hsgt_fund_flow_summary")
    return await manager.get_hsgt_fund_flow_summary()


async def get_hsgt_hold_stock(
    market: str = "港股通", indicator: str = "5日排行"
) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_hsgt_hold_stock", market=market, indicator=indicator)
    return await manager.get_hsgt_hold_stock(market=market, indicator=indicator)


async def get_hk_connect_overview() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_hk_connect_overview")
    return await manager.get_hk_connect_overview()
