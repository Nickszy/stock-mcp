# src/server/core/use_cases/fixed_income.py
"""Use cases for fixed income / bond research data."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from src.server.core.dependencies import Container
from src.server.utils.logger import logger


async def get_bond_yield_curve(
    start_date: str = "", end_date: str = ""
) -> Dict[str, Any]:
    """Get China bond yield curve data (government + corporate)."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_bond_yield_curve", start_date=start_date, end_date=end_date)
    return await manager.get_bond_yield_curve(start_date=start_date, end_date=end_date)


async def get_convertible_bonds(bond_code: str = "") -> Dict[str, Any]:
    """Get convertible bond market data."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_convertible_bonds", bond_code=bond_code)
    return await manager.get_convertible_bonds(bond_code=bond_code)


async def get_convertible_bond_history(
    symbol: str, days: int = 120
) -> Dict[str, Any]:
    """Get individual convertible bond historical K-line."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_convertible_bond_history", symbol=symbol, days=days)
    return await manager.get_convertible_bond_history(symbol=symbol, days=days)


async def get_convertible_bond_detail(symbol: str) -> Dict[str, Any]:
    """Get convertible bond terms and details."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_convertible_bond_detail", symbol=symbol)
    return await manager.get_convertible_bond_detail(symbol=symbol)


async def get_credit_spread(
    start_date: str = "", end_date: str = ""
) -> Dict[str, Any]:
    """Get credit spread data (AAA - CGB, AA+ - AAA etc)."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_credit_spread", start_date=start_date, end_date=end_date)
    return await manager.get_credit_spread(start_date=start_date, end_date=end_date)


async def get_repo_rates(
    start_date: str = "", end_date: str = ""
) -> Dict[str, Any]:
    """Get repo rate (fixing) history."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_repo_rates", start_date=start_date, end_date=end_date)
    return await manager.get_repo_rates(start_date=start_date, end_date=end_date)


async def get_interbank_rate(
    market: str = "上海银行间同业拆借市场",
    symbol: str = "Shibor人民币",
    indicator: str = "隔夜",
) -> Dict[str, Any]:
    """Get interbank rate data (Shibor etc)."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_interbank_rate", market=market, symbol=symbol, indicator=indicator)
    return await manager.get_interbank_rate(market=market, symbol=symbol, indicator=indicator)


async def get_bond_issuance_overview(days: int = 90) -> Dict[str, Any]:
    """Get bond issuance overview (treasury/local-gov/corporate/convertible)."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_bond_issuance_overview", days=days)
    return await manager.get_bond_issuance_overview(days=days)


async def get_fixed_income_overview() -> Dict[str, Any]:
    """Get aggregated fixed income market overview."""
    indicators: Dict[str, Any] = {}
    errors: list[str] = []

    async def _safe(label: str, coro):
        try:
            indicators[label] = await coro
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    await asyncio.gather(
        _safe("bond_yield", get_bond_yield_curve()),
        _safe("convertible_bonds", get_convertible_bonds()),
        _safe("credit_spread", get_credit_spread()),
        _safe("repo_rates", get_repo_rates()),
        _safe("issuance", get_bond_issuance_overview(30)),
    )

    return {"indicators": indicators, "errors": errors, "source": "akshare"}
