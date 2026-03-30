# src/server/mcp/tools/fixed_income_tools.py
"""MCP tools for fixed income / bond research (COL-244).

Dedicated tool group for bond yield curves, convertible bonds,
credit spreads, and fixed income market overview.

Tool list (6):
  - get_cn_bond_yield_curve      — government + corporate yield curves
  - get_cn_convertible_bonds      — real-time convertible bond list
  - get_cn_convertible_bond_history — individual CB historical K-line
  - get_cn_convertible_bond_detail  — CB terms and analytics
  - get_cn_credit_spread          — credit spread (AAA-CGB etc)
  - get_cn_fixed_income_overview  — aggregated FI dashboard
"""

from __future__ import annotations

from typing import Any, Dict

from fastmcp import Context, FastMCP

from src.server.core.use_cases import fixed_income as fi_uc
from src.server.mcp.tools.artifact_utils import (
    create_artifact_envelope,
    create_artifact_response,
)
from src.server.utils.logger import logger


def _fmt_bp(v: Any) -> str:
    """Format value as basis points."""
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.2f}bp"
    except Exception:
        return "N/A"


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return "N/A"


def _fmt_num(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return "N/A"


def register_fixed_income_tools(mcp: FastMCP):
    """Register fixed income research tools."""

    # ------------------------------------------------------------------
    # 1. Bond Yield Curve
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fixed-income", "bond"})
    async def get_cn_bond_yield_curve(
        start_date: str = "",
        end_date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国债券收益率曲线(国债/国开债/信用债).

        WHEN TO USE: 用户问"收益率曲线""十年期国债利率""利率期限结构""信用债利率".
        CONCEPT: 收益率曲线展示不同期限的到期收益率, 是所有资产定价的折现率基础.
          正常向上倾斜; 倒挂预示衰退风险.
        DIFFERENTIATION: 收益率曲线/期限结构; 政策利率(SHIBOR/LPR)看 get_cn_interest_rates;
          货币供应看 get_cn_money_supply; 信用利差看 get_cn_credit_spread.
        next_recommended_tools: get_cn_credit_spread -> get_cn_interest_rates -> get_cn_convertible_bonds

        Args:
            start_date: 起始日期 YYYYMMDD (默认近90天)
            end_date: 截止日期 YYYYMMDD (默认今天)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📈 固收-收益率曲线")
        try:
            result = await fi_uc.get_bond_yield_curve(start_date=start_date, end_date=end_date)
            rows = result.get("data", []) if isinstance(result, dict) else []
            summary = f"债券收益率曲线: {len(rows)}条记录"
            if rows:
                latest = rows[-1]
                ten_y = latest.get("10年")
                summary += f", 最新10年期={_fmt_pct(ten_y)}"

            artifact = create_artifact_envelope(
                component_type="bond_yield_curve",
                name="债券收益率曲线",
                content={"data": rows},
                description=summary,
                metadata={"type": "cn_bond_yield_curve"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_bond_yield_curve error", error=str(e))
            summary = f"获取收益率曲线失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="bond_yield_curve",
                    name="债券收益率曲线",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 2. Convertible Bonds List
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fixed-income", "bond"})
    async def get_cn_convertible_bonds(
        bond_code: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取可转债实时行情列表.

        WHEN TO USE: 用户问"可转债行情""转债市场概况""哪些可转债在交易".
        CONCEPT: 可转债是A股市唯一T+0品种, 兼具债底保护和转股弹性.
          双低策略(低价格+低溢价率)是经典可转债策略.
        DIFFERENTIATION: 全市场可转债列表; 个券历史K线看 get_cn_convertible_bond_history;
          个券条款/转股价看 get_cn_convertible_bond_detail.
        next_recommended_tools: get_cn_convertible_bond_detail -> get_cn_convertible_bond_history -> get_cn_bond_yield_curve

        Args:
            bond_code: 可转债代码筛选 (可选)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📈 固收-可转债列表")
        try:
            result = await fi_uc.get_convertible_bonds(bond_code=bond_code)
            total = result.get("total", 0) if isinstance(result, dict) else 0
            summary = f"可转债市场: 共{total}只"
            artifact = create_artifact_envelope(
                component_type="convertible_bonds",
                name="可转债行情",
                content=result,
                description=summary,
                metadata={"type": "cn_convertible_bonds", "bond_code": bond_code},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_convertible_bonds error", error=str(e))
            summary = f"获取可转债数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="convertible_bonds",
                    name="可转债行情",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 3. Convertible Bond History
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fixed-income", "bond"})
    async def get_cn_convertible_bond_history(
        symbol: str = "sz123138",
        days: int = 120,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取单只可转债历史K线行情.

        WHEN TO USE: 用户问"某可转债走势""转债K线""123138历史行情".
        CONCEPT: 历史K线展示价格/成交量趋势, 用于技术分析和溢价率变化追踪.
        DIFFERENTIATION: 单只可转债历史K线; 全市场列表看 get_cn_convertible_bonds;
          条款/转股价看 get_cn_convertible_bond_detail.
        next_recommended_tools: get_cn_convertible_bond_detail -> get_cn_convertible_bonds -> get_cn_bond_yield_curve

        Args:
            symbol: 债券代码(带市场前缀, 如 sz123138)
            days: 返回天数 (default 120)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"📈 固收-可转债历史: {symbol}")
        try:
            result = await fi_uc.get_convertible_bond_history(symbol=symbol, days=days)
            rows = result.get("data", []) if isinstance(result, dict) else []
            summary = f"可转债{symbol}历史({len(rows)}天)"
            artifact = create_artifact_envelope(
                component_type="convertible_bond_history",
                name=f"可转债 {symbol}",
                content={"data": rows},
                description=summary,
                metadata={"type": "cn_cb_history", "symbol": symbol},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_convertible_bond_history error", error=str(e))
            summary = f"获取可转债历史失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="convertible_bond_history",
                    name=f"可转债 {symbol}",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 4. Convertible Bond Detail
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fixed-income", "bond"})
    async def get_cn_convertible_bond_detail(
        symbol: str = "123138",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取可转债条款详情(转股价/溢价率/到期收益率/评级等).

        WHEN TO USE: 用户问"可转债转股价多少""溢价率""某转债条款""转债评级".
        CONCEPT: 转股价/溢价率/赎回触发/回售触发是可转债核心条款, 直接影响投资决策.
          溢价率越低越接近"买正股的替代品".
        DIFFERENTIATION: 单只可转债条款深度分析; 全市场列表看 get_cn_convertible_bonds;
          历史K线看 get_cn_convertible_bond_history.
        next_recommended_tools: get_cn_convertible_bond_history -> get_cn_convertible_bonds -> get_cn_bond_yield_curve

        Args:
            symbol: 债券代码(纯数字, 如 123138)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"📈 固收-可转债详情: {symbol}")
        try:
            result = await fi_uc.get_convertible_bond_detail(symbol=symbol)
            detail = result.get("data", {}) if isinstance(result, dict) else {}
            name = detail.get("bond_name", symbol)
            premium = detail.get("transfer_premium_ratio")
            coupon = detail.get("coupon_rate")
            rating = detail.get("rating", "")
            summary = f"可转债{name}({symbol}): 溢价率={_fmt_pct(premium)}, 票息={_fmt_pct(coupon)}, 评级={rating}"

            artifact = create_artifact_envelope(
                component_type="convertible_bond_detail",
                name=f"可转债详情 {symbol}",
                content={"data": detail},
                description=summary,
                metadata={"type": "cn_cb_detail", "symbol": symbol},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_convertible_bond_detail error", error=str(e))
            summary = f"获取可转债详情失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="convertible_bond_detail",
                    name=f"可转债详情 {symbol}",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 5. Credit Spread
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fixed-income", "bond"})
    async def get_cn_credit_spread(
        start_date: str = "",
        end_date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国信用利差(AAA-国债, AA+-AAA等).

        WHEN TO USE: 用户问"信用利差""信用环境""融资成本""信用风险定价".
        CONCEPT: 信用利差 = 信用债收益率 - 国债收益率. 利差扩大意味着信用风险担忧上升,
          利差收窄意味着信用环境宽松. 是行业轮动和择时的重要信号.
        DIFFERENTIATION: 信用利差/风险定价; 收益率曲线看 get_cn_bond_yield_curve;
          货币环境看 get_cn_money_supply; 利率看 get_cn_interest_rates.
        next_recommended_tools: get_cn_bond_yield_curve -> get_cn_money_supply -> get_cn_pmi

        Args:
            start_date: 起始日期 YYYYMMDD
            end_date: 截止日期 YYYYMMDD
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📈 固收-信用利差")
        try:
            result = await fi_uc.get_credit_spread(start_date=start_date, end_date=end_date)
            rows = result.get("data", []) if isinstance(result, dict) else []
            summary = f"信用利差: {len(rows)}条记录"
            if rows:
                latest = rows[-1]
                aaa_1y = latest.get("AAA-1年")
                summary += f", 最新AAA-1Y={_fmt_bp(aaa_1y)}"

            artifact = create_artifact_envelope(
                component_type="credit_spread",
                name="信用利差",
                content={"data": rows},
                description=summary,
                metadata={"type": "cn_credit_spread"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_credit_spread error", error=str(e))
            summary = f"获取信用利差失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="credit_spread",
                    name="信用利差",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 6. Fixed Income Overview
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fixed-income", "bond"})
    async def get_cn_fixed_income_overview(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国固定收益全景概览.

        WHEN TO USE: 用户问"固收市场怎么样""债券市场概览""利率环境一览".
        CONCEPT: 聚合收益率曲线+可转债市场+信用利差, 提供一屏式固收快照.
        DIFFERENTIATION: 固收全景聚合; 单指标深度看 get_cn_bond_yield_curve / get_cn_credit_spread 等.
        next_recommended_tools: get_cn_bond_yield_curve -> get_cn_credit_spread -> get_cn_convertible_bonds

        Args:
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📈 固收-全景概览")
        try:
            result = await fi_uc.get_fixed_income_overview()
            indicators = result.get("indicators", {})
            errors = result.get("errors", [])

            parts: list[str] = []
            by = indicators.get("bond_yield", {})
            by_rows = by.get("data", []) if isinstance(by, dict) else []
            if by_rows:
                latest = by_rows[-1]
                parts.append(f"10Y国债={_fmt_pct(latest.get('10年'))}")

            cs = indicators.get("credit_spread", {})
            cs_rows = cs.get("data", []) if isinstance(cs, dict) else []
            if cs_rows:
                latest_cs = cs_rows[-1]
                parts.append(f"AAA-1Y利差={_fmt_bp(latest_cs.get('AAA-1年'))}")

            cb = indicators.get("convertible_bonds", {})
            cb_total = cb.get("total", 0) if isinstance(cb, dict) else 0
            if cb_total:
                parts.append(f"可转债={cb_total}只")

            summary = "固收概览: " + ", ".join(parts) if parts else "固收概览: 部分指标获取失败"
            if errors:
                summary += f" (错误: {len(errors)}项)"

            artifact = create_artifact_envelope(
                component_type="fixed_income_overview",
                name="固定收益概览",
                content={"indicators": indicators, "errors": errors},
                description=summary,
                metadata={"type": "cn_fixed_income_overview"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_fixed_income_overview error", error=str(e))
            summary = f"获取固收概览失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="fixed_income_overview",
                    name="固定收益概览",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )
