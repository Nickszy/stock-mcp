# src/server/core/use_cases/money_flow.py
"""Money flow use cases shared by MCP tools and REST routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.server.core.dependencies import Container
from src.server.utils.logger import logger


async def get_money_flow(ticker: str, days: int = 20) -> Dict[str, Any]:
    service = Container.money_flow_service()
    logger.info("UseCase: get_money_flow", ticker=ticker, days=days)
    return await service.get_money_flow(ticker, days)


async def get_north_bound_flow(days: int = 30) -> Dict[str, Any]:
    service = Container.money_flow_service()
    logger.info("UseCase: get_north_bound_flow", days=days)
    return await service.get_north_bound_flow(days)


async def get_chip_distribution(ticker: str, days: int = 30) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_chip_distribution", ticker=ticker, days=days)
    return await manager.get_chip_distribution(ticker, days)


async def get_chip_distribution_detail(
    symbol: str, period_days: int = 30, price_bins: int = 100
) -> Dict[str, Any]:
    service = Container.chip_service()
    gateway = Container.market_gateway()
    resolved_symbol = await gateway.resolve_ticker(symbol)
    logger.info(
        "UseCase: get_chip_distribution_detail",
        symbol=symbol,
        resolved_symbol=resolved_symbol,
        period_days=period_days,
        price_bins=price_bins,
    )
    return await service.get_chip_distribution(resolved_symbol, period_days, price_bins)


async def get_money_supply(months: int = 60) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_money_supply", months=months)
    return await manager.get_money_supply(months)


async def get_inflation_data(months: int = 60) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_inflation_data", months=months)
    return await manager.get_inflation_data(months)


async def get_pmi_data(months: int = 60) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_pmi_data", months=months)
    return await manager.get_pmi_data(months)


async def get_gdp_data(quarters: int = 20) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_gdp_data", quarters=quarters)
    return await manager.get_gdp_data(quarters)


async def get_social_financing(months: int = 60) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_social_financing", months=months)
    return await manager.get_social_financing(months)


async def get_interest_rates(
    shibor_days: int = 252, lpr_months: int = 60
) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info(
        "UseCase: get_interest_rates",
        shibor_days=shibor_days,
        lpr_months=lpr_months,
    )
    return await manager.get_interest_rates(shibor_days, lpr_months)


async def get_market_liquidity(days: int = 60) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_market_liquidity", days=days)
    return await manager.get_market_liquidity(days)


async def get_market_money_flow(
    trade_date: Optional[str] = None,
    top_n: int = 20,
    include_outflow: bool = True,
) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info(
        "UseCase: get_market_money_flow",
        trade_date=trade_date,
        top_n=top_n,
        include_outflow=include_outflow,
    )
    return await manager.get_market_money_flow(
        trade_date=trade_date,
        top_n=top_n,
        include_outflow=include_outflow,
    )


async def get_sector_trend(
    sector_name: str = "",
    days: int = 10,
    sector_id: Optional[str] = None,
) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info(
        "UseCase: get_sector_trend",
        sector=sector_name,
        sector_id=sector_id,
        days=days,
    )
    return await manager.get_sector_trend(
        sector_name=sector_name,
        days=days,
        sector_id=sector_id,
    )


async def resolve_sector(query_text: str, intent: str = "trend") -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: resolve_sector", query=query_text, intent=intent)
    return await manager.resolve_sector(query_text=query_text, intent=intent)


async def get_sector_money_flow_history(
    sector_name: str = "",
    days: int = 20,
    sector_id: Optional[str] = None,
) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info(
        "UseCase: get_sector_money_flow_history",
        sector=sector_name,
        sector_id=sector_id,
        days=days,
    )
    return await manager.get_sector_money_flow_history(
        sector_name=sector_name,
        days=days,
        sector_id=sector_id,
    )


async def get_sector_valuation_metrics(
    sector_name: str = "",
    days: int = 250,
    sample_size: int = 60,
    sector_id: Optional[str] = None,
) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info(
        "UseCase: get_sector_valuation_metrics",
        sector=sector_name,
        sector_id=sector_id,
        days=days,
        sample_size=sample_size,
    )
    return await manager.get_sector_valuation_metrics(
        sector_name=sector_name,
        days=days,
        sample_size=sample_size,
        sector_id=sector_id,
    )


async def get_ggt_daily(days: int = 60) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_ggt_daily", days=days)
    return await manager.get_ggt_daily(days)


async def get_inflation_data(months: int = 60) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_inflation_data", months=months)
    return await manager.get_inflation_data(months)
async def get_pmi_data(months: int = 60) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_pmi_data", months=months)
    return await manager.get_pmi_data(months)
async def get_gdp_data(quarters: int = 20) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_gdp_data", quarters=quarters)
    return await manager.get_gdp_data(quarters)
async def get_social_financing(months: int = 60) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_social_financing", months=months)
    return await manager.get_social_financing(months)


async def get_us_economic_growth(quarters: int = 20) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_us_economic_growth", quarters=quarters)
    return await manager.get_us_economic_growth(quarters)


async def get_us_inflation_employment(months: int = 24) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_us_inflation_employment", months=months)
    return await manager.get_us_inflation_employment(months)


async def get_us_interest_rates(days: int = 180) -> Dict[str, Any]:
    manager = Container.market_gateway()
    logger.info("UseCase: get_us_interest_rates", days=days)
    return await manager.get_us_interest_rates(days)


async def get_market_breadth(days: int = 20) -> Dict[str, Any]:
    """Get market breadth indicators: up/down count, new high/low, median return."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_market_breadth", days=days)
    return await manager.get_market_breadth(days=days)


async def get_relative_strength(
    symbol: str, benchmark: str = "000300", days: int = 60
) -> Dict[str, Any]:
    """Get relative strength of a stock vs benchmark index."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_relative_strength", symbol=symbol, benchmark=benchmark, days=days)
    return await manager.get_relative_strength(symbol=symbol, benchmark=benchmark, days=days)


async def get_sector_valuation_metrics(
    sector_name: str = "",
    days: int = 250,
    sample_size: int = 60,
    sector_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Get sector valuation metrics with historical percentiles."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_sector_valuation_metrics", sector_name=sector_name, days=days)
    return await manager.get_sector_valuation_metrics(
        sector_name=sector_name, days=days, sample_size=sample_size, sector_id=sector_id
    )


async def calculate_technical_indicators(
    symbol: str,
    indicators: Optional[List[str]] = None,
    period: str = "daily",
    days: int = 120,
) -> Dict[str, Any]:
    """Calculate technical indicators for a stock."""
    manager = Container.market_gateway()
    logger.info("UseCase: calculate_technical_indicators", symbol=symbol, indicators=indicators, days=days)
    return await manager.calculate_technical_indicators(
        symbol=symbol, indicators=indicators, period=period, days=days
    )


# ---- Extended Quantitative Data ----


async def get_margin_trading(ticker: str, days: int = 30) -> Dict[str, Any]:
    """Get margin trading (融资融券) data for a stock."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_margin_trading", ticker=ticker, days=days)
    return await manager.get_margin_trading(ticker=ticker, days=days)


async def get_restricted_release(symbol: str = "", days: int = 90) -> Dict[str, Any]:
    """Get restricted share release (解禁) data."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_restricted_release", symbol=symbol, days=days)
    return await manager.get_restricted_release(symbol=symbol, days=days)


async def get_repurchase_info(symbol: str = "") -> Dict[str, Any]:
    """Get stock repurchase (回购) data."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_repurchase_info", symbol=symbol)
    return await manager.get_repurchase_info(symbol=symbol)


async def get_index_constituents(index_code: str = "000300") -> Dict[str, Any]:
    """Get index constituent stocks."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_index_constituents", index_code=index_code)
    return await manager.get_index_constituents(index_code=index_code)


async def get_index_constituent_weights(index_code: str = "000300") -> Dict[str, Any]:
    """Get index constituent stock weights."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_index_constituent_weights", index_code=index_code)
    return await manager.get_index_constituent_weights(index_code=index_code)


async def get_fund_nav(fund_code: str = "", days: int = 30) -> Dict[str, Any]:
    """Get fund NAV data."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_fund_nav", fund_code=fund_code, days=days)
    return await manager.get_fund_nav(fund_code=fund_code, days=days)


async def get_bond_yield() -> Dict[str, Any]:
    """Get bond yield curve data."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_bond_yield")
    return await manager.get_bond_yield()


async def get_futures_main(symbol: str = "IF0", days: int = 60) -> Dict[str, Any]:
    """Get futures main contract data."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_futures_main", symbol=symbol, days=days)
    return await manager.get_futures_main(symbol=symbol, days=days)


async def get_option_summary() -> Dict[str, Any]:
    """Get option market summary with PCR."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_option_summary")
    return await manager.get_option_summary()


async def get_sector_pe_pb_historical(
    sector_name: str = "", days: int = 250, sector_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Get sector PE/PB historical data with percentile rankings."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_sector_pe_pb_historical", sector_name=sector_name, days=days)
    return await manager.get_sector_pe_pb_historical(
        sector_name=sector_name, days=days, sector_id=sector_id
    )


async def get_etf_flow(symbol: str = "", days: int = 30) -> Dict[str, Any]:
    """Get ETF flow/subscription data."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_etf_flow", symbol=symbol, days=days)
    return await manager.get_etf_flow(symbol=symbol, days=days)


async def get_style_rotation() -> Dict[str, Any]:
    """Get style rotation indicators (large-cap vs small-cap)."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_style_rotation")
    return await manager.get_style_rotation()


async def get_futures_basis(index_code: str = "IF0", days: int = 60) -> Dict[str, Any]:
    """Get futures basis (futures price - spot index price)."""
    manager = Container.market_gateway()
    logger.info("UseCase: get_futures_basis", index_code=index_code, days=days)
    return await manager.get_futures_basis(index_code=index_code, days=days)


async def calculate_risk_metrics(
    symbol: str, indicators: Optional[List[str]] = None, days: int = 120,
) -> Dict[str, Any]:
    """Calculate quantitative risk metrics (Beta/Sharpe/VaR/CVaR/MaxDrawdown)."""
    manager = Container.market_gateway()
    logger.info("UseCase: calculate_risk_metrics", symbol=symbol, days=days)
    return await manager.calculate_risk_metrics(
        symbol=symbol, indicators=indicators, days=days
    )
