# src/server/mcp/tools/commodity_tools.py
"""MCP tools for commodity asset data (COL-244).

Tool list (6):
  - get_gold_price                — gold futures (AU)
  - get_silver_price              — silver futures (AG)
  - get_crude_oil_price           — crude oil futures (SC)
  - get_copper_price              — copper futures (CU)
  - get_industrial_metals_overview — copper + aluminum + zinc + rebar
  - get_commodity_overview        — aggregated commodity dashboard
"""

from __future__ import annotations

from typing import Any, Dict

from fastmcp import Context, FastMCP

from src.server.core.use_cases import commodities as comm_uc
from src.server.mcp.tools.artifact_utils import (
    create_artifact_envelope,
    create_artifact_response,
)
from src.server.utils.logger import logger


def _fmt_num(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return "N/A"


def register_commodity_tools(mcp: FastMCP):
    """Register commodity asset tools."""

    @mcp.tool(tags={"commodity", "asset"})
    async def get_gold_price(
        days: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取黄金期货主力合约行情.

        WHEN TO USE: 用户问"金价多少""黄金走势""金价历史".
        CONCEPT: 黄金是核心避险资产, 与美元/利率/通胀负相关, 是跨资产配置的压舱石.
        DIFFERENTIATION: 黄金期货; 白银看 get_silver_price; 原油看 get_crude_oil_price.
        next_recommended_tools: get_silver_price -> get_crude_oil_price -> get_cn_bond_yield_curve

        Args:
            days: 返回天数 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("🥇 黄金行情")
        try:
            result = await comm_uc.get_commodity_price("AU0", days)
            rows = result.get("data", []) if isinstance(result, dict) else []
            latest = rows[-1] if rows else {}
            price = latest.get("收盘价")
            summary = f"黄金期货(近{days}天): 最新收盘={_fmt_num(price)}"
            artifact = create_artifact_envelope(
                component_type="commodity_gold",
                name="黄金期货",
                content={"data": rows},
                description=summary,
                metadata={"type": "commodity_gold"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_gold_price error", error=str(e))
            summary = f"获取黄金数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="commodity_gold",
                    name="黄金期货",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    @mcp.tool(tags={"commodity", "asset"})
    async def get_silver_price(
        days: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取白银期货主力合约行情.

        WHEN TO USE: 用户问"银价多少""白银走势""贵金属行情".
        CONCEPT: 白银兼具贵金属和工业属性, 波动率大于黄金, 是贵金属投机和工业需求的晴雨表.
        DIFFERENTIATION: 白银期货; 黄金看 get_gold_price; 原油看 get_crude_oil_price.
        next_recommended_tools: get_gold_price -> get_crude_oil_price -> get_cn_bond_yield_curve

        Args:
            days: 返回天数 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("⚪ 白银行情")
        try:
            result = await comm_uc.get_commodity_price("AG0", days)
            rows = result.get("data", []) if isinstance(result, dict) else []
            latest = rows[-1] if rows else {}
            price = latest.get("收盘价")
            summary = f"白银期货(近{days}天): 最新收盘={_fmt_num(price)}"
            artifact = create_artifact_envelope(
                component_type="commodity_silver",
                name="白银期货",
                content={"data": rows},
                description=summary,
                metadata={"type": "commodity_silver"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_silver_price error", error=str(e))
            summary = f"获取白银数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="commodity_silver",
                    name="白银期货",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    @mcp.tool(tags={"commodity", "asset"})
    async def get_crude_oil_price(
        days: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取原油期货主力合约行情(上海原油SC).

        WHEN TO USE: 用户问"油价多少""原油走势""能源价格".
        CONCEPT: 原油是"工业血液", 影响通胀/运输成本/化工产业链. SC是人民币计价原油期货.
        DIFFERENTIATION: 上海原油期货(SC); 黄金看 get_gold_price; 利率看 get_cn_bond_yield_curve.
        next_recommended_tools: get_gold_price -> get_cn_bond_yield_curve -> get_cn_cpi

        Args:
            days: 返回天数 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("🛢️ 原油行情")
        try:
            result = await comm_uc.get_commodity_price("SC0", days)
            rows = result.get("data", []) if isinstance(result, dict) else []
            latest = rows[-1] if rows else {}
            price = latest.get("收盘价")
            summary = f"原油期货SC(近{days}天): 最新收盘={_fmt_num(price)}"
            artifact = create_artifact_envelope(
                component_type="commodity_crude_oil",
                name="原油期货",
                content={"data": rows},
                description=summary,
                metadata={"type": "commodity_crude_oil"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_crude_oil_price error", error=str(e))
            summary = f"获取原油数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="commodity_crude_oil",
                    name="原油期货",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    @mcp.tool(tags={"commodity", "asset"})
    async def get_copper_price(
        days: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取铜期货主力合约行情.

        WHEN TO USE: 用户问"铜价多少""铜走势""工业金属价格".
        CONCEPT: 铜是"铜博士", 是全球经济晴雨表, 与制造业PMI/基建/新能源高度相关.
        DIFFERENTIATION: 沪铜期货; 贵金属看 get_gold_price; 工业全貌看 get_industrial_metals_overview.
        next_recommended_tools: get_industrial_metals_overview -> get_gold_price -> get_cn_pmi

        Args:
            days: 返回天数 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("🟤 铜行情")
        try:
            result = await comm_uc.get_commodity_price("CU0", days)
            rows = result.get("data", []) if isinstance(result, dict) else []
            latest = rows[-1] if rows else {}
            price = latest.get("收盘价")
            summary = f"沪铜期货(近{days}天): 最新收盘={_fmt_num(price)}"
            artifact = create_artifact_envelope(
                component_type="commodity_copper",
                name="铜期货",
                content={"data": rows},
                description=summary,
                metadata={"type": "commodity_copper"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_copper_price error", error=str(e))
            summary = f"获取铜数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="commodity_copper",
                    name="铜期货",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    @mcp.tool(tags={"commodity", "asset"})
    async def get_industrial_metals_overview(
        days: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取工业金属全景概览(铜+铝+锌+螺纹钢).

        WHEN TO USE: 用户问"工业金属怎么样""有色金属行情""黑色系金属""基建材料价格".
        CONCEPT: 聚合铜/铝/锌/螺纹钢四大工业金属, 反映制造业/基建/房地产的真实需求景气度.
        DIFFERENTIATION: 工业金属聚合; 单品种看 get_copper_price; 贵金属看 get_gold_price.
        next_recommended_tools: get_copper_price -> get_commodity_overview -> get_cn_pmi

        Args:
            days: 各品种返回天数 (default 30)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("🏗️ 工业金属概览")
        try:
            result = await comm_uc.get_industrial_metals_overview(days)
            indicators = result.get("indicators", {})
            errors = result.get("errors", [])

            labels = {
                "copper": "铜",
                "aluminum": "铝",
                "zinc": "锌",
                "rebar": "螺纹钢",
            }
            parts: list[str] = []
            for key, label in labels.items():
                data = indicators.get(key, {})
                rows = data.get("data", []) if isinstance(data, dict) else []
                if rows:
                    latest = rows[-1]
                    parts.append(f"{label}={_fmt_num(latest.get('收盘价'))}")

            summary = "工业金属: " + ", ".join(parts) if parts else "工业金属: 部分指标获取失败"
            if errors:
                summary += f" (错误: {len(errors)}项)"

            artifact = create_artifact_envelope(
                component_type="commodity_industrial_metals",
                name="工业金属概览",
                content={"indicators": indicators, "errors": errors},
                description=summary,
                metadata={"type": "commodity_industrial_metals"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_industrial_metals_overview error", error=str(e))
            summary = f"获取工业金属概览失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="commodity_industrial_metals",
                    name="工业金属概览",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    @mcp.tool(tags={"commodity", "asset"})
    async def get_commodity_overview(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取大宗商品全景概览(黄金+白银+原油+铜).

        WHEN TO USE: 用户问"大宗商品怎么样""商品市场概览""贵金属能源一览".
        CONCEPT: 聚合黄金/白银/原油/铜等核心商品, 提供跨资产联动快照.
        DIFFERENTIATION: 商品全景聚合; 单品种深度看 get_gold_price / get_silver_price / get_crude_oil_price / get_copper_price.
        next_recommended_tools: get_gold_price -> get_copper_price -> get_industrial_metals_overview

        Args:
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📊 大宗商品概览")
        try:
            result = await comm_uc.get_commodity_overview()
            indicators = result.get("indicators", {})
            errors = result.get("errors", [])

            parts: list[str] = []
            for name, label in [("gold", "黄金"), ("silver", "白银"), ("crude_oil", "原油"), ("copper", "铜")]:
                data = indicators.get(name, {})
                rows = data.get("data", []) if isinstance(data, dict) else []
                if rows:
                    latest = rows[-1]
                    parts.append(f"{label}={_fmt_num(latest.get('收盘价'))}")

            summary = "商品概览: " + ", ".join(parts) if parts else "商品概览: 部分指标获取失败"
            if errors:
                summary += f" (错误: {len(errors)}项)"

            artifact = create_artifact_envelope(
                component_type="commodity_overview",
                name="大宗商品概览",
                content={"indicators": indicators, "errors": errors},
                description=summary,
                metadata={"type": "commodity_overview"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_commodity_overview error", error=str(e))
            summary = f"获取商品概览失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="commodity_overview",
                    name="大宗商品概览",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )
