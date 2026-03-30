# src/server/mcp/tools/fixed_income_tools.py
"""MCP tools for fixed income / bond research (COL-244).

Dedicated tool group for bond yield curves, convertible bonds,
credit spreads, and fixed income market overview.

Tool list (9):
  - get_cn_bond_yield_curve      — government + corporate yield curves
  - get_cn_convertible_bonds      — real-time convertible bond list
  - get_cn_convertible_bond_history — individual CB historical K-line
  - get_cn_convertible_bond_detail  — CB terms and analytics
  - get_cn_credit_spread          — credit spread (AAA-CGB etc)
  - get_cn_repo_rates             — repo fixing rate history
  - get_cn_interbank_rate         — interbank rate (Shibor etc)
  - get_cn_bond_issuance_overview — bond issuance overview
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
    # 6. Repo Rates
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fixed-income", "bond"})
    async def get_cn_repo_rates(
        start_date: str = "",
        end_date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取银行间回购定盘利率历史数据.

        WHEN TO USE: 用户问"回购利率""资金价格""流动性松紧""DR001/DR007".
        CONCEPT: 回购利率是银行间短期资金价格的核心指标, 直接反映市场流动性松紧.
          回购利率走高=资金紧张, 走低=资金宽松.
        DIFFERENTIATION: 回购/资金价格; 收益率曲线看 get_cn_bond_yield_curve;
          政策利率看 get_cn_interest_rates.
        next_recommended_tools: get_cn_bond_yield_curve -> get_cn_interbank_rate -> get_cn_credit_spread

        Args:
            start_date: 起始日期 YYYYMMDD (默认近90天)
            end_date: 截止日期 YYYYMMDD (默认今天)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📈 固收-回购利率")
        try:
            result = await fi_uc.get_repo_rates(start_date=start_date, end_date=end_date)
            rows = result.get("data", []) if isinstance(result, dict) else []
            summary = f"回购利率: {len(rows)}条记录"
            if rows:
                latest = rows[-1]
                # Try common column names
                for key in latest:
                    if "定盘" in str(key) or "FR" in str(key) or "利率" in str(key):
                        summary += f", 最新{key}={_fmt_pct(latest[key])}"
                        break

            artifact = create_artifact_envelope(
                component_type="repo_rates",
                name="回购定盘利率",
                content={"data": rows},
                description=summary,
                metadata={"type": "cn_repo_rates"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_repo_rates error", error=str(e))
            summary = f"获取回购利率失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="repo_rates",
                    name="回购定盘利率",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 7. Interbank Rate (Shibor etc)
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fixed-income", "bond"})
    async def get_cn_interbank_rate(
        market: str = "上海银行间同业拆借市场",
        symbol: str = "Shibor人民币",
        indicator: str = "隔夜",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取银行间同业拆借市场利率(Shibor/Chibor等).

        WHEN TO USE: 用户问"Shibor多少""银行间利率""隔夜拆借利率""同业拆借".
        CONCEPT: Shibor(上海银行间同业拆放利率)是短端利率基准, 反映银行间流动性.
          隔夜/1周/1M是最关键期限, 与央行公开市场操作高度联动.
        DIFFERENTIATION: 同业拆借利率口径; 回购利率看 get_cn_repo_rates;
          贷款基准看 get_cn_interest_rates(LPR).
        next_recommended_tools: get_cn_repo_rates -> get_cn_bond_yield_curve -> get_cn_credit_spread

        Args:
            market: 市场 (默认"上海银行间同业拆借市场")
            symbol: 币种 (默认"Shibor人民币")
            indicator: 期限 (默认"隔夜", 可选"1周"/"2周"/"1个月"/"3个月"/"6个月"/"9个月"/"1年")
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📈 固收-同业拆借利率")
        try:
            result = await fi_uc.get_interbank_rate(market=market, symbol=symbol, indicator=indicator)
            rows = result.get("data", []) if isinstance(result, dict) else []
            summary = f"同业拆借利率({indicator}): {len(rows)}条记录"
            if rows:
                latest = rows[-1]
                for key in latest:
                    if "利率" in str(key) or "rate" in str(key).lower():
                        summary += f", 最新={_fmt_pct(latest[key])}"
                        break

            artifact = create_artifact_envelope(
                component_type="interbank_rate",
                name=f"同业拆借利率({indicator})",
                content={"data": rows},
                description=summary,
                metadata={"type": "cn_interbank_rate", "market": market, "symbol": symbol, "indicator": indicator},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_interbank_rate error", error=str(e))
            summary = f"获取同业拆借利率失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="interbank_rate",
                    name=f"同业拆借利率({indicator})",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 8. Bond Issuance Overview
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fixed-income", "bond"})
    async def get_cn_bond_issuance_overview(
        days: int = 90,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取债券发行概览(国债/地方债/企业债/可转债).

        WHEN TO USE: 用户问"债券发行""发债规模""一级市场""新发债券".
        CONCEPT: 债券发行是一级市场供给, 大规模发行可能推高收益率, 供给收缩则利好.
          国债/地方债/企业债/可转债四大口径提供完整供给视角.
        DIFFERENTIATION: 债券发行供给视角; 收益率看 get_cn_bond_yield_curve;
          利差看 get_cn_credit_spread.
        next_recommended_tools: get_cn_bond_yield_curve -> get_cn_credit_spread -> get_cn_repo_rates

        Args:
            days: 统计天数 (default 90)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("📈 固收-债券发行概览")
        try:
            result = await fi_uc.get_bond_issuance_overview(days=days)
            data = result.get("data", {}) if isinstance(result, dict) else {}

            parts: list[str] = []
            labels = {"treasury": "国债", "local_government": "地方债", "corporate": "企业债", "convertible": "可转债"}
            for key, label in labels.items():
                entry = data.get(key, {})
                cnt = entry.get("count", 0) if isinstance(entry, dict) else 0
                if cnt:
                    parts.append(f"{label}={cnt}只")

            summary = "债券发行: " + ", ".join(parts) if parts else "债券发行: 暂无数据"
            summary += f" (近{days}天)"

            artifact = create_artifact_envelope(
                component_type="bond_issuance",
                name="债券发行概览",
                content={"data": data},
                description=summary,
                metadata={"type": "cn_bond_issuance", "days": days},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_bond_issuance_overview error", error=str(e))
            summary = f"获取债券发行概览失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="bond_issuance",
                    name="债券发行概览",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 9. Fixed Income Overview
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fixed-income", "bond"})
    async def get_cn_fixed_income_overview(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国固定收益全景概览.

        WHEN TO USE: 用户问"固收市场怎么样""债券市场概览""利率环境一览".
        CONCEPT: 聚合收益率曲线+可转债市场+信用利差+回购利率+债券发行, 提供一屏式固收快照.
        DIFFERENTIATION: 固收全景聚合; 单指标深度看 get_cn_bond_yield_curve / get_cn_credit_spread 等.
        next_recommended_tools: get_cn_bond_yield_curve -> get_cn_credit_spread -> get_cn_repo_rates

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

            repo = indicators.get("repo_rates", {})
            repo_rows = repo.get("data", []) if isinstance(repo, dict) else []
            if repo_rows:
                parts.append(f"回购利率={len(repo_rows)}天")

            iss = indicators.get("issuance", {})
            iss_data = iss.get("data", {}) if isinstance(iss, dict) else {}
            if iss_data:
                iss_count = sum(
                    v.get("count", 0) if isinstance(v, dict) else 0
                    for v in iss_data.values()
                )
                if iss_count:
                    parts.append(f"新发债券={iss_count}只")

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
