# src/server/mcp/tools/option_tools.py
"""MCP tools for option market data.

Tool list (3):
  - get_option_chain        — list SSE option contracts by underlying
  - get_option_greeks       — Greeks for a specific contract
  - get_option_price_history — daily K-line for a specific contract
"""

from __future__ import annotations

from typing import Any, Dict

from fastmcp import Context, FastMCP

from src.server.core.use_cases import options as opt_uc
from src.server.mcp.tools.artifact_utils import (
    create_artifact_envelope,
    create_artifact_response,
)
from src.server.utils.logger import logger


def register_option_tools(mcp: FastMCP):
    """Register option market data tools."""

    @mcp.tool(tags={"option", "derivative"})
    async def get_option_chain(
        symbol: str = "50ETF",
        exchange: str = "null",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取上交所期权合约列表(50ETF/300ETF等).

        WHEN TO USE: 用户问"50ETF期权合约""300ETF期权有哪些""期权链""到期月份".
        CONCEPT: 期权链展示同一标的所有到期月份的合约列表, 是构建策略的基础.
          50ETF/300ETF期权是A股最活跃的场内期权品种.
        DIFFERENTIATION: 期权合约列表; Greeks看 get_option_greeks; 概览看 get_option_summary.
        next_recommended_tools: get_option_greeks -> get_option_summary -> get_cn_bond_yield_curve

        Args:
            symbol: 标的名称 (default "50ETF", 可选 "300ETF")
            exchange: 交易所 (default "null")
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📋 期权合约列表")
        try:
            result = await opt_uc.get_option_chain(symbol=symbol, exchange=exchange)
            data = result.get("data", [])
            summary = f"期权合约({symbol}): {len(data)}个到期月份"
            artifact = create_artifact_envelope(
                component_type="option_chain",
                name=f"期权合约 {symbol}",
                content={"data": data},
                description=summary,
                metadata={"type": "option_chain", "symbol": symbol},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_option_chain error", error=str(e))
            summary = f"获取期权合约列表失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="option_chain",
                    name=f"期权合约 {symbol}",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    @mcp.tool(tags={"option", "derivative"})
    async def get_option_greeks(
        contract: str = "10003045",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取单个期权合约Greeks(Delta/Gamma/Theta/Vega/Rho/IV).

        WHEN TO USE: 用户问"期权Greeks""Delta多少""隐含波动率IV""期权定价参数".
        CONCEPT: Greeks是期权风险 sensitivities: Delta=方向敞口, Gamma=凸性, Theta=时间衰减,
          Vega=波动率敏感度, IV=隐含波动率. 是期权定价和风控的核心参数.
        DIFFERENTIATION: 单合约Greeks; 合约列表看 get_option_chain; 概览看 get_option_summary.
        next_recommended_tools: get_option_chain -> get_option_price_history -> get_option_summary

        Args:
            contract: 合约代码 (如 10003045)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📐 期权Greeks")
        try:
            result = await opt_uc.get_option_greeks(contract=contract)
            data = result.get("data", [])
            summary = f"期权Greeks({contract}): {len(data)}条记录"
            artifact = create_artifact_envelope(
                component_type="option_greeks",
                name=f"期权Greeks {contract}",
                content={"data": data},
                description=summary,
                metadata={"type": "option_greeks", "contract": contract},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_option_greeks error", error=str(e))
            summary = f"获取期权Greeks失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="option_greeks",
                    name=f"期权Greeks {contract}",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    @mcp.tool(tags={"option", "derivative"})
    async def get_option_price_history(
        contract: str = "10003889",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取单个期权合约历史日K行情.

        WHEN TO USE: 用户问"期权K线""合约历史行情""期权价格走势".
        CONCEPT: 期权日K线展示合约价格随时间的变化, 用于技术分析和策略回测.
          注意期权有到期日, 历史数据仅覆盖存续期.
        DIFFERENTIATION: 单合约历史K线; Greeks看 get_option_greeks; 合约列表看 get_option_chain.
        next_recommended_tools: get_option_greeks -> get_option_chain -> get_option_summary

        Args:
            contract: 合约代码 (如 10003889)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📊 期权历史行情")
        try:
            result = await opt_uc.get_option_price_history(contract=contract)
            data = result.get("data", [])
            summary = f"期权历史({contract}): {len(data)}天"
            artifact = create_artifact_envelope(
                component_type="option_price_history",
                name=f"期权行情 {contract}",
                content={"data": data},
                description=summary,
                metadata={"type": "option_price_history", "contract": contract},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_option_price_history error", error=str(e))
            summary = f"获取期权历史行情失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="option_price_history",
                    name=f"期权行情 {contract}",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )
