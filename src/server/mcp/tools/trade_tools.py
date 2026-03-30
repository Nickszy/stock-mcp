# src/server/mcp/tools/trade_tools.py
"""MCP tools for trade execution.
Provides capabilities to execute orders via CCXT or other adapters.
"""

from typing import Any, Dict, Optional
from decimal import Decimal
from fastmcp import FastMCP, Context

from src.server.utils.logger import logger


def register_trade_tools(mcp: FastMCP):
    """Register trade-related tools."""

    @mcp.tool(tags={"trade"})
    async def execute_order(
        symbol: str,
        side: str,
        type: str,
        quantity: float,
        price: Optional[float] = None,
        exchange_id: Optional[str] = None, ctx: Context = None) -> Dict[str, Any]:
        """Execute a trading order.

        WHEN TO USE: User explicitly wants to place a buy/sell order.
        Only use when user gives clear trading instructions.

        CONCEPT: Submits a market or limit order to a connected exchange.
        Supports crypto (CCXT) and broker integrations.

        DIFFERENTIATION: This is the only trade execution tool. All analysis tools
        are read-only; this is the only write/action tool.

        next_recommended_tools: get_account_balance, get_real_time_price

        Args:
            symbol: Trading pair symbol (e.g., "BTC/USDT", "AAPL")
            side: "buy" or "sell"
            type: "market" or "limit"
            quantity: Amount to trade
            price: Limit price (required for limit orders)
            exchange_id: Optional exchange ID (e.g., "binance", "interactive_brokers")
            ctx: FastMCP Context for logging

        Returns:
            Order execution result
        """
        if ctx:
            await ctx.info(
                f"🔧 执行交易: {side} {symbol}",
                extra={
                    "symbol": symbol,
                    "side": side,
                    "type": type,
                    "quantity": quantity,
                    "price": price
                }
            )

        try:
            logger.info(
                "MCP tool called: execute_order",
                symbol=symbol,
                side=side,
                type=type,
                quantity=quantity,
                price=price
            )

            # TODO: Implement actual trade execution logic via AdapterManager -> CCXTAdapter
            # For now, we return a simulated success response to unblock the Strategy Agent flow.
            
            result = {
                "status": "simulated_success",
                "order_id": "sim_123456789",
                "symbol": symbol,
                "side": side,
                "type": type,
                "quantity": quantity,
                "price": price,
                "message": "Order executed in simulation mode (Real trading not yet enabled)"
            }
            
            if ctx:
                await ctx.info(
                    f"✅ 交易执行完成(模拟): {side} {symbol}",
                    extra={"order_id": result["order_id"]}
                )
                
            return result
            
        except Exception as e:
            logger.error(f"Execute order failed: {e}")
            if ctx:
                await ctx.error(
                    f"❌ 交易执行失败: {symbol}",
                    extra={"error": str(e)}
                )
            return {"error": str(e)}

    @mcp.tool(tags={"trade"})
    async def get_account_balance(exchange_id: Optional[str] = None, ctx: Context = None) -> Dict[str, Any]:
        """Get account balance.

        WHEN TO USE: User asks about their portfolio balance, available funds,
        or position sizes on connected exchanges.

        CONCEPT: Returns account balance from connected exchange showing
        total equity, available margin, and per-asset positions.

        DIFFERENTIATION: This is a portfolio/account tool, not a market data tool.
        Use market data tools for prices, this for account status.

        next_recommended_tools: execute_order, get_real_time_price

        Args:
            exchange_id: Optional exchange ID
            ctx: FastMCP Context for logging

        Returns:
            Account balance information
        """
        if ctx:
            await ctx.info(f"🔧 获取账户余额", extra={"exchange_id": exchange_id})

        try:
            logger.info("MCP tool called: get_account_balance", exchange_id=exchange_id)
            
            # TODO: Implement actual balance fetch
            result = {
                "status": "simulated_success",
                "balances": {
                    "USDT": {"free": 10000.0, "used": 0.0, "total": 10000.0},
                    "BTC": {"free": 0.5, "used": 0.0, "total": 0.5}
                }
            }
            
            if ctx:
                await ctx.info(f"✅ 账户余额获取完成(模拟)")
                
            return result
            
        except Exception as e:
            logger.error(f"Get account balance failed: {e}")
            if ctx:
                await ctx.error(
                    f"❌ 获取账户余额失败",
                    extra={"error": str(e)}
                )
            return {"error": str(e)}
