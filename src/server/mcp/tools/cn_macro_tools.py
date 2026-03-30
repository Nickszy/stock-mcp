# src/server/mcp/tools/cn_macro_tools.py
"""MCP tools for China macroeconomic data.

Dedicated tool group for China macro indicators.  Reuses existing use cases
from ``src.server.core.use_cases.money_flow`` and adds two new tools:
``get_cn_trade_balance`` and ``get_cn_macro_overview``.

Tool list (9):
  - get_cn_gdp             — wrap existing get_gdp_data
  - get_cn_cpi              — wrap existing get_inflation_data
  - get_cn_ppi              — wrap existing get_inflation_data (PPI only)
  - get_cn_pmi              — wrap existing get_pmi_data
  - get_cn_money_supply     — wrap existing get_money_supply
  - get_cn_interest_rates   — wrap existing get_interest_rates
  - get_cn_trade_balance    — **new** import/export trade balance
  - get_cn_social_financing — wrap existing get_social_financing
  - get_cn_macro_overview   — **new** aggregated macro dashboard
"""

from __future__ import annotations

from typing import Any, Dict

from fastmcp import Context, FastMCP

from src.server.core.use_cases import money_flow as mf_uc
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_artifact_envelope,
    create_artifact_response,
)
from src.server.utils.logger import logger


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return "N/A"


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def register_cn_macro_tools(mcp: FastMCP):
    """Register China macro tools."""

    # ------------------------------------------------------------------
    # 1. GDP
    # ------------------------------------------------------------------
    @mcp.tool(tags={"cn-macro", "macro"})
    async def get_cn_gdp(
        quarters: int = 20,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国季度 GDP 增长数据.

        WHEN TO USE: 用户问"GDP增速多少""经济增长情况""宏观经济走势".
        CONCEPT: GDP是衡量经济体总产出的核心指标. 季度同比增速反映经济整体景气.
        DIFFERENTIATION: 总量增长指标; 短期景气看 get_cn_pmi; 通胀看 get_cn_cpi.
        next_recommended_tools: get_cn_pmi -> get_cn_cpi -> get_cn_money_supply

        Args:
            quarters: 返回最近N个季度 (default 20)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"🇨🇳 宏观-GDP: 最近{quarters}季")
        try:
            result = await mf_uc.get_gdp_data(quarters)
            rows = result.get("data", []) if isinstance(result, dict) else []
            latest = rows[-1] if rows else {}
            q = latest.get("quarter", "N/A")
            yoy = latest.get("gdp_yoy")
            summary = f"中国GDP(近{quarters}季): 最新{q}同比{_fmt_pct(yoy)}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.GDP_DATA,
                name="中国 GDP",
                content={"data": rows},
                description=summary,
                metadata={"type": "cn_gdp"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_gdp error", error=str(e))
            summary = f"获取中国GDP数据失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.GDP_DATA,
                name="中国 GDP",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # 2. CPI
    # ------------------------------------------------------------------
    @mcp.tool(tags={"cn-macro", "macro"})
    async def get_cn_cpi(
        months: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国 CPI 居民消费价格指数.

        WHEN TO USE: 用户问"通胀情况如何""CPI最新多少""有没有通缩压力".
        CONCEPT: CPI反映消费端价格水平, 是判断通胀/通缩的核心指标.
        DIFFERENTIATION: 消费端通胀; 工业端看 get_cn_ppi; 货币量看 get_cn_money_supply.
        next_recommended_tools: get_cn_ppi -> get_cn_money_supply -> get_cn_interest_rates

        Args:
            months: 返回最近N个月 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"🇨🇳 宏观-CPI: 最近{months}月")
        try:
            result = await mf_uc.get_inflation_data(months)
            data = result.get("data", {}) if isinstance(result, dict) else {}
            cpi = data.get("CPI", data.get("cpi", [])) or []
            latest = cpi[-1] if cpi else {}
            m = latest.get("month", latest.get("月份", "N/A"))
            yoy = latest.get("nt_yoy", latest.get("全国当月同比", None))
            summary = f"中国CPI(近{months}月): 最新{m}同比{_fmt_pct(yoy)}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.INFLATION_DATA,
                name="中国 CPI",
                content={"cpi": cpi},
                description=summary,
                metadata={"type": "cn_cpi"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_cpi error", error=str(e))
            summary = f"获取中国CPI数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type=ComponentType.INFLATION_DATA,
                    name="中国 CPI",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 3. PPI
    # ------------------------------------------------------------------
    @mcp.tool(tags={"cn-macro", "macro"})
    async def get_cn_ppi(
        months: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国 PPI 工业品出厂价格指数.

        WHEN TO USE: 用户问"工业品价格走势""PPI数据""上游通胀如何".
        CONCEPT: PPI反映工业品出厂价格, 用于判断上游通胀/通缩压力和工业企业利润空间.
        DIFFERENTIATION: 工业端价格; 消费端看 get_cn_cpi; 经济景气看 get_cn_pmi.
        next_recommended_tools: get_cn_cpi -> get_cn_pmi -> get_cn_gdp

        Args:
            months: 返回最近N个月 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"🇨🇳 宏观-PPI: 最近{months}月")
        try:
            result = await mf_uc.get_inflation_data(months)
            data = result.get("data", {}) if isinstance(result, dict) else {}
            ppi = data.get("PPI", data.get("ppi", [])) or []
            latest = ppi[-1] if ppi else {}
            m = latest.get("month", latest.get("月份", "N/A"))
            yoy = latest.get("ppi_yoy", latest.get("工业品当月同比", None))
            summary = f"中国PPI(近{months}月): 最新{m}同比{_fmt_pct(yoy)}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.INFLATION_DATA,
                name="中国 PPI",
                content={"ppi": ppi},
                description=summary,
                metadata={"type": "cn_ppi"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_ppi error", error=str(e))
            summary = f"获取中国PPI数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type=ComponentType.INFLATION_DATA,
                    name="中国 PPI",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 4. PMI
    # ------------------------------------------------------------------
    @mcp.tool(tags={"cn-macro", "macro"})
    async def get_cn_pmi(
        months: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国官方 PMI (制造业/非制造业).

        WHEN TO USE: 用户问"制造业景气度如何""PMI最新多少""经济在扩张还是收缩".
        CONCEPT: PMI以50为荣枯线, >50扩张, <50收缩. 制造业PMI是实体经济短期景气核心指标.
        DIFFERENTIATION: 景气/实体经济口径; 经济增长看 get_cn_gdp; 通胀看 get_cn_cpi.
        next_recommended_tools: get_cn_gdp -> get_cn_cpi -> get_cn_social_financing

        Args:
            months: 返回最近N个月 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"🇨🇳 宏观-PMI: 最近{months}月")
        try:
            result = await mf_uc.get_pmi_data(months)
            rows = result.get("data", []) if isinstance(result, dict) else []
            latest = rows[-1] if rows else {}
            mfg = latest.get("pmi", latest.get("PMI010000"))
            summary = f"中国PMI(近{months}月): 最新制造业{_fmt_pct(mfg)}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.PMI_DATA,
                name="中国 PMI",
                content={"data": rows},
                description=summary,
                metadata={"type": "cn_pmi"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_pmi error", error=str(e))
            summary = f"获取中国PMI数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type=ComponentType.PMI_DATA,
                    name="中国 PMI",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 5. Money Supply (M0/M1/M2)
    # ------------------------------------------------------------------
    @mcp.tool(tags={"cn-macro", "macro"})
    async def get_cn_money_supply(
        months: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国货币供应量 (M0/M1/M2).

        WHEN TO USE: 用户问"货币环境宽松还是收紧""M2增速多少""流动性状况".
        CONCEPT: M1/M2同比反映货币宽松程度. M1-M2剪刀差反映企业活期 vs 资金沉淀.
        DIFFERENTIATION: 货币量口径; 利率看 get_cn_interest_rates; 信用看 get_cn_social_financing.
        next_recommended_tools: get_cn_interest_rates -> get_cn_social_financing -> get_cn_cpi

        Args:
            months: 返回最近N个月 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"🇨🇳 宏观-货币供应: 最近{months}月")
        try:
            result = await mf_uc.get_money_supply(months)
            rows = result.get("data", []) if isinstance(result, dict) else []
            latest = rows[-1] if rows else {}
            m1 = latest.get("m1_yoy")
            m2 = latest.get("m2_yoy")
            summary = f"中国货币供应(近{months}月): M1同比{_fmt_pct(m1)}, M2同比{_fmt_pct(m2)}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.MONEY_SUPPLY,
                name="中国 货币供应量",
                content={"data": rows},
                description=summary,
                metadata={"type": "cn_money_supply"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_money_supply error", error=str(e))
            summary = f"获取中国货币供应数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type=ComponentType.MONEY_SUPPLY,
                    name="中国 货币供应量",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 6. Interest Rates (SHIBOR + LPR)
    # ------------------------------------------------------------------
    @mcp.tool(tags={"cn-macro", "macro"})
    async def get_cn_interest_rates(
        shibor_days: int = 252,
        lpr_months: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国利率数据 (SHIBOR + LPR).

        WHEN TO USE: 用户问"利率水平""央行降息/加息了吗""Shibor/LPR走势".
        CONCEPT: SHIBOR是银行间短端利率, LPR是贷款基准利率. 两者结合看利率曲线与政策信号.
        DIFFERENTIATION: 利率/资金价格口径; 货币量看 get_cn_money_supply; 信用看 get_cn_social_financing.
        next_recommended_tools: get_cn_money_supply -> get_cn_social_financing -> get_cn_cpi

        Args:
            shibor_days: Shibor返回天数 (default 252)
            lpr_months: LPR返回月数 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("🇨🇳 宏观-利率")
        try:
            result = await mf_uc.get_interest_rates(shibor_days, lpr_months)
            data = result.get("data", {}) if isinstance(result, dict) else {}
            shibor = data.get("shibor", [])
            lpr = data.get("lpr", [])
            s_latest = shibor[0] if shibor else {}
            l_latest = lpr[0] if lpr else {}
            s_1w = s_latest.get("1w", s_latest.get("week_1"))
            l_1y = l_latest.get("lpr_1y", l_latest.get("1y"))
            summary = f"中国利率: Shibor-1W={_fmt_pct(s_1w)}, LPR-1Y={_fmt_pct(l_1y)}"
            artifact = create_artifact_envelope(
                component_type="cn_interest_rates",
                name="中国 利率",
                content={"shibor": shibor, "lpr": lpr},
                description=summary,
                metadata={"type": "cn_interest_rates"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_interest_rates error", error=str(e))
            summary = f"获取中国利率数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="cn_interest_rates",
                    name="中国 利率",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 7. Trade Balance (NEW)
    # ------------------------------------------------------------------
    @mcp.tool(tags={"cn-macro", "macro"})
    async def get_cn_trade_balance(
        months: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国进出口贸易差额.

        WHEN TO USE: 用户问"贸易顺差多少""进出口数据""外贸情况".
        CONCEPT: 贸易差额=出口-进口. 顺差扩大意味着外需强或内需弱, 对汇率和GDP都有影响.
        DIFFERENTIATION: 外贸口径; 内需景气看 get_cn_pmi; 经济增长看 get_cn_gdp.
        next_recommended_tools: get_cn_pmi -> get_cn_gdp -> get_cn_money_supply

        Args:
            months: 返回最近N个月 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"🇨🇳 宏观-贸易差额: 最近{months}月")
        try:
            result = await mf_uc.get_trade_balance(months)
            rows = result.get("data", []) if isinstance(result, dict) else []
            latest = rows[-1] if rows else {}
            # Akshare returns Chinese column names; pick first numeric-looking value
            balance = None
            for k, v in latest.items():
                fv = _to_float(v)
                if fv is not None and k not in ("日期", "date"):
                    balance = fv
                    break
            summary = (
                f"中国贸易差额(近{months}月): 最新值={_fmt_pct(balance) if balance else 'N/A'}"
            )
            artifact = create_artifact_envelope(
                component_type="cn_trade_balance",
                name="中国 贸易差额",
                content={"data": rows},
                description=summary,
                metadata={"type": "cn_trade_balance"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_trade_balance error", error=str(e))
            summary = f"获取中国贸易差额失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type="cn_trade_balance",
                    name="中国 贸易差额",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 8. Social Financing
    # ------------------------------------------------------------------
    @mcp.tool(tags={"cn-macro", "macro"})
    async def get_cn_social_financing(
        months: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国社会融资规模.

        WHEN TO USE: 用户问"社融数据""信用环境宽松还是偏紧""新增信贷".
        CONCEPT: 社融衡量实体从金融体系获得资金总量. 存量同比增速判断信用周期.
        DIFFERENTIATION: 信用/融资口径; 货币量看 get_cn_money_supply; 利率看 get_cn_interest_rates.
        next_recommended_tools: get_cn_money_supply -> get_cn_interest_rates -> get_cn_pmi

        Args:
            months: 返回最近N个月 (default 60)
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info(f"🇨🇳 宏观-社融: 最近{months}月")
        try:
            result = await mf_uc.get_social_financing(months)
            rows = result.get("data", []) if isinstance(result, dict) else []
            latest = rows[0] if rows else {}
            stk_yoy = latest.get("stk_yoy")
            summary = f"中国社融(近{months}月): 存量同比{_fmt_pct(stk_yoy)}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.SOCIAL_FINANCING,
                name="中国 社会融资规模",
                content={"data": rows},
                description=summary,
                metadata={"type": "cn_social_financing"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_social_financing error", error=str(e))
            summary = f"获取中国社融数据失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type=ComponentType.SOCIAL_FINANCING,
                    name="中国 社会融资规模",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )

    # ------------------------------------------------------------------
    # 9. Macro Overview (NEW — aggregated dashboard)
    # ------------------------------------------------------------------
    @mcp.tool(tags={"cn-macro", "macro"})
    async def get_cn_macro_overview(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取中国宏观经济全景概览.

        WHEN TO USE: 用户问"中国经济整体情况""宏观面怎么样""给个宏观概览".
        CONCEPT: 聚合GDP/CPI/PMI/M2/社融/贸易差额/LPR等核心指标, 提供一屏式宏观快照.
        DIFFERENTIATION: 聚合全景; 单指标深度看 get_cn_gdp / get_cn_cpi 等.
        next_recommended_tools: get_cn_gdp -> get_cn_cpi -> get_cn_pmi -> get_cn_money_supply

        Args:
            ctx: FastMCP Context
        """
        if ctx:
            await ctx.info("🇨🇳 宏观-全景概览")
        try:
            indicators: Dict[str, Any] = {}
            errors: list[str] = []

            async def _safe(label: str, coro):
                try:
                    indicators[label] = await coro
                except Exception as exc:
                    errors.append(f"{label}: {exc}")

            import asyncio
            await asyncio.gather(
                _safe("gdp", mf_uc.get_gdp_data(4)),
                _safe("inflation", mf_uc.get_inflation_data(12)),
                _safe("pmi", mf_uc.get_pmi_data(12)),
                _safe("money_supply", mf_uc.get_money_supply(12)),
                _safe("social_financing", mf_uc.get_social_financing(12)),
                _safe("interest_rates", mf_uc.get_interest_rates(30, 12)),
                _safe("trade_balance", mf_uc.get_trade_balance(12)),
            )

            # Build summary text
            parts: list[str] = []

            gdp_data = indicators.get("gdp", {})
            gdp_rows = gdp_data.get("data", []) if isinstance(gdp_data, dict) else []
            if gdp_rows:
                g = gdp_rows[-1]
                parts.append(f"GDP同比{_fmt_pct(g.get('gdp_yoy'))}")

            infl = indicators.get("inflation", {})
            infl_data = infl.get("data", {}) if isinstance(infl, dict) else {}
            cpi_rows = infl_data.get("CPI", infl_data.get("cpi", [])) or []
            ppi_rows = infl_data.get("PPI", infl_data.get("ppi", [])) or []
            if cpi_rows:
                c = cpi_rows[-1]
                parts.append(f"CPI同比{_fmt_pct(c.get('nt_yoy'))}")
            if ppi_rows:
                p = ppi_rows[-1]
                parts.append(f"PPI同比{_fmt_pct(p.get('ppi_yoy'))}")

            pmi_data = indicators.get("pmi", {})
            pmi_rows = pmi_data.get("data", []) if isinstance(pmi_data, dict) else []
            if pmi_rows:
                pm = pmi_rows[-1]
                mfg = pm.get("pmi", pm.get("PMI010000"))
                parts.append(f"PMI={_fmt_pct(mfg)}")

            ms_data = indicators.get("money_supply", {})
            ms_rows = ms_data.get("data", []) if isinstance(ms_data, dict) else []
            if ms_rows:
                ms = ms_rows[-1]
                parts.append(f"M2同比{_fmt_pct(ms.get('m2_yoy'))}")

            summary = "中国宏观概览: " + ", ".join(parts) if parts else "中国宏观概览: 部分指标获取失败"
            if errors:
                summary += f" (错误: {len(errors)}项)"

            artifact = create_artifact_envelope(
                component_type=ComponentType.MACRO_INDICATOR,
                name="中国 宏观经济概览",
                content={"indicators": indicators, "errors": errors},
                description=summary,
                metadata={"type": "cn_macro_overview"},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except Exception as e:
            logger.error("get_cn_macro_overview error", error=str(e))
            summary = f"获取中国宏观概览失败: {e}"
            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type=ComponentType.MACRO_INDICATOR,
                    name="中国 宏观经济概览",
                    content={"error": str(e)},
                    description=summary,
                    visible_to_llm=True,
                ),
            )
