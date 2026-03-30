# src/server/core/use_cases/options.py
"""Use cases for option market data (chain, Greeks, price history)."""

from __future__ import annotations

from typing import Any, Dict

from src.server.core.dependencies import Container
from src.server.utils.logger import logger


async def get_option_chain(
    symbol: str = "50ETF", exchange: str = "null"
) -> Dict[str, Any]:
    """Get SSE option contract list for a given underlying."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_option_chain", symbol=symbol, exchange=exchange)
    return await manager.get_option_chain(symbol=symbol, exchange=exchange)


async def get_option_greeks(contract: str) -> Dict[str, Any]:
    """Get Greeks (Delta/Gamma/Theta/Vega/Rho/IV) for a specific contract."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_option_greeks", contract=contract)
    return await manager.get_option_greeks(contract=contract)


async def get_option_price_history(contract: str) -> Dict[str, Any]:
    """Get daily price history for a specific option contract."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_option_price_history", contract=contract)
    return await manager.get_option_price_history(contract=contract)
