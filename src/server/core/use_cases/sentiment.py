# src/server/core/use_cases/sentiment.py
"""Use cases for market sentiment / QVIX data."""

from __future__ import annotations

from typing import Dict, Any

from src.server.core.dependencies import Container
from src.server.utils.logger import logger


async def get_qvix_50etf() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_qvix_50etf")
    return await manager.get_qvix_50etf()


async def get_qvix_300etf() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_qvix_300etf")
    return await manager.get_qvix_300etf()


async def get_qvix_1000index() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_qvix_1000index")
    return await manager.get_qvix_1000index()


async def get_qvix_cyb() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_qvix_cyb")
    return await manager.get_qvix_cyb()


async def get_market_sentiment_overview() -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_market_sentiment_overview")
    return await manager.get_market_sentiment_overview()
