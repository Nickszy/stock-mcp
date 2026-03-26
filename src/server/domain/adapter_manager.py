# src/server/domain/adapter_manager.py
"""Backward compatibility shim.

AdapterManager has been merged into MarketGateway.
This module provides aliases for backward compatibility.
"""

from src.server.domain.market_gateway import (
    MarketGateway,
    get_market_gateway,
    logger,
)

# Type alias for backward compatibility
AdapterManager = MarketGateway

# Backward-compatible function alias
get_adapter_manager = get_market_gateway

__all__ = ["AdapterManager", "MarketGateway", "get_adapter_manager", "get_market_gateway"]
