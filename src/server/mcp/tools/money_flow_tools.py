# src/server/mcp/tools/money_flow_tools.py
"""MCP tools for money flow analysis.
Provides stock money flow and north bound (HSGT) flow data.
Supports output_format: markdown (default, human-readable) or json (structured).

使用新版 Artifact 结构:
- component_type 标准化
- 参照竞品格式
"""

from typing import Any, Dict

from fastmcp import FastMCP, Context

from src.server.core.use_cases import money_flow as money_flow_use_cases
from src.server.core.dependencies import Container
from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    create_artifact_envelope,
    create_artifact_response,
    create_artifact_list_response,
    ComponentType,
    create_chart_artifact,
    create_table_artifact,
    create_symbol_error_response,
)
from src.server.mcp.tools.output_format_utils import (
    _format_money_flow_markdown,
    OutputFormat,
)
from src.server.domain.symbols.errors import SymbolResolutionError
from src.server.domain.symbols import to_ts_code


def register_money_flow_tools(mcp: FastMCP):
    """Register money flow analysis tools."""

    async def _resolve_ts_code(raw_symbol: str) -> str:
        resolved = await Container.market_gateway().resolve_ticker(raw_symbol)
        return to_ts_code(resolved)

    def _unit_label(unit: str) -> str:
        return {
            "cny": "元",
            "10k_cny": "万元",
            "100m_cny": "亿元",
            "unknown": "原始单位",
        }.get(unit, unit or "原始单位")

    def _to_cny(val: Any, unit: str) -> float | None:
        if not isinstance(val, (int, float)):
            return None
        if unit == "cny":
            return float(val)
        if unit == "10k_cny":
            return float(val) * 1e4
        if unit == "100m_cny":
            return float(val) * 1e8
        return None

    def _fmt_amount(val: Any, unit: str = "unknown") -> str:
        cny = _to_cny(val, unit)
        if cny is not None:
            if abs(cny) >= 1e8:
                return f"{cny / 1e8:.2f}亿"
            if abs(cny) >= 1e4:
                return f"{cny / 1e4:.2f}万"
            return f"{cny:.0f}元"
        if isinstance(val, (int, float)):
            return f"{float(val):.2f}{_unit_label(unit)}"
        return "N/A"

    @mcp.tool(tags={"money-flow"})
    async def get_money_flow(
        symbol: str,
        days: int = 20,
        output_format: OutputFormat = "markdown",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取个股资金流向数据。

        WHEN TO USE:
        - 用户问“主力资金这几天是流入还是流出？”
        - 需要看单只股票近N日主力/散户净流方向
        - 想结合价格走势判断个股是否有资金承接

        CONCEPT:
        个股资金流向通常按大单/超大单、散户等口径统计净流入，用于观察短线资金偏好与交易拥挤度。

        DIFFERENTIATION:
        - 这是“个股级”资金流工具；看全市场外资请用 get_north_bound_flow
        - 看板块级资金热度请用 get_sector_money_flow_history 或 get_market_money_flow
        - 看持仓成本密集区而非资金流，请用 get_chip_distribution

        next_recommended_tools:
        - get_chip_distribution
        - get_relative_strength
        - get_margin_trading
        """
        if ctx:
            await ctx.info(
                f"🔧 获取资金流向: {symbol}", extra={"symbol": symbol, "days": days}
            )

        try:
            logger.info("MCP tool called: get_money_flow", symbol=symbol, days=days)
            result = await money_flow_use_cases.get_money_flow(symbol, days)
            result["component_type"] = "money_flow"
            ts_code = result.get("ts_code") or await _resolve_ts_code(symbol)

            # 构建摘要信息给 LLM（精简版）
            summary = result.get("summary", {})
            total_main = summary.get("total_main_net", 0)
            total_retail = summary.get("total_retail_net", 0)
            total_net = total_main + total_retail
            trend = summary.get("trend", "未知")
            amount_unit = (
                result.get("amount_unit")
                or summary.get("amount_unit")
                or "unknown"
            )

            summary_text = (
                f"{symbol}主力资金流（{days}日）:\n"
                f"- 大/超大单净流入(主力口径): {_fmt_amount(total_main, amount_unit)}\n"
                f"- 整体净流{'入' if total_net >= 0 else '出'}: {_fmt_amount(total_net, amount_unit)}\n"
                f"- 金额单位口径: {_unit_label(amount_unit)}\n"
                f"- 趋势: {trend}"
            )

            if ctx:
                await ctx.info(
                    f"✅ 资金流向获取完成: {symbol}",
                    extra={"total_main_net": total_main, "trend": trend},
                )

            # 对齐竞品格式: content = {ts_code, records:[{trade_date, main_net_inflow}]}
            records = []
            if isinstance(result.get("records"), list):
                records = result.get("records", [])
            else:
                data = result.get("data", {})
                dates = data.get("dates", [])
                main = data.get("main_net_inflow", [])
                if dates and main and len(dates) == len(main):
                    for d, v in zip(dates, main):
                        trade_date = d.replace("-", "") if isinstance(d, str) else d
                        records.append({"trade_date": trade_date, "main_net_inflow": v})

            content = {
                "ts_code": ts_code,
                "records": records,
                "amount_unit": amount_unit,
            }

            # For JSON format, return original artifact structure
            if output_format == "json":
                artifact = create_artifact_envelope(
                    component_type="money_flow",
                    name=f"Money Flow: {ts_code}",
                    content=content,
                    description=(
                        f"Main Force (Institutional) Capital Flow: {ts_code} (Last {days} days). "
                        "Visualizes daily net inflow/outflow trends of Large & Extra-Large orders. "
                        f"Overall Trend: {trend}."
                    ),
                    metadata={
                        "type": "money_flow",
                        "ts_code": ts_code,
                        "days": days,
                        "amount_unit": amount_unit,
                    },
                    visible_to_llm=False,
                    display_in_report=True,
                )
                return create_artifact_response(summary=summary_text, artifact=artifact)

            # For markdown format, render as readable text
            md_output = f"## {ts_code} 资金流向\n\n"
            md_output += f"**摘要**: {summary_text}\n\n"
            md_output += _format_money_flow_markdown(records, "主力资金净流入明细", amount_unit)

            artifact = create_artifact_envelope(
                component_type="money_flow_markdown",
                name=f"资金流向: {ts_code}",
                content={"markdown": md_output, "format": "markdown"},
                description=summary_text,
                metadata={"output_format": "markdown", "ts_code": ts_code},
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败: {symbol}", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="money_flow", name=f"{symbol} 资金流向"
            )
        except Exception as e:
            logger.error(f"Get money flow failed: {e}", exc_info=True)
            if ctx:
                await ctx.error(
                    f"❌ 获取资金流向失败: {symbol}", extra={"error": str(e)}
                )
            ts_code = to_ts_code(symbol)
            empty = {"ts_code": ts_code, "records": []}
            artifact = create_artifact_envelope(
                component_type="money_flow",
                name=f"Money Flow: {ts_code}",
                content=empty,
                description="No money flow data",
                metadata={"type": "money_flow", "ts_code": ts_code, "days": days},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(
                summary="No money flow data", artifact=artifact
            )

    @mcp.tool(tags={"money-flow"})
    async def get_north_bound_flow(
        days: int = 30, ctx: Context = None
    ) -> Dict[str, Any]:
        """获取北向资金(沪深港通)流向数据。

        WHEN TO USE:
        - 用户问“今天/近一段时间外资是净流入还是净流出？”
        - 需要判断A股是否有北向资金持续加仓或撤离
        - 想看市场级“聪明钱”风险偏好，而不是单只股票

        CONCEPT:
        北向资金指通过沪股通、深股通流入A股的境外资金，常被视为外资风险偏好与市场情绪的代表性观察口径。

        DIFFERENTIATION:
        - 这是“市场级外资总流量”；看单股北向持仓请用 get_stock_northbound_holdings
        - 看个股主力/散户资金请用 get_money_flow
        - 看A股板块整体热度而非外资单一通道，请用 get_market_money_flow

        next_recommended_tools:
        - get_market_liquidity
        - get_market_money_flow
        - get_stock_northbound_ranking
        """
        if ctx:
            await ctx.info(f"🔧 获取北向资金流向", extra={"days": days})

        try:
            logger.info("MCP tool called: get_north_bound_flow", days=days)
            result = await money_flow_use_cases.get_north_bound_flow(days)
            result["component_type"] = "north_bound_flow"

            # 构建摘要
            # moneyflow_hsgt 返回单位为万元，转换为亿元展示
            summary = result.get("summary", {})
            total_net = summary.get("total_net", 0)
            total_net_yi = (
                float(total_net) / 10000 if isinstance(total_net, (int, float)) else None
            )
            series = (result.get("data") or {}).get("total") or []
            dates = (result.get("data") or {}).get("dates") or []
            latest_total = float(series[-1]) if series else None
            prev_total = float(series[-2]) if len(series) >= 2 else None
            latest_date = str(dates[-1]) if dates else "N/A"

            latest_total_yi = latest_total / 10000 if latest_total is not None else None
            day_delta_text = (
                f"(较前一日{(latest_total - prev_total) / 10000:+.2f}亿)"
                if latest_total is not None and prev_total is not None
                else ""
            )
            if total_net_yi is None:
                flow_signal = "未知"
            elif total_net_yi >= 0:
                flow_signal = "外资阶段性净流入"
            else:
                flow_signal = "外资阶段性净流出"

            summary_text = (
                f"北向资金({days}日): 最新{latest_date}单日净流入"
                f"{f'{latest_total_yi:+.2f}亿' if latest_total_yi is not None else 'N/A'}"
                f"{day_delta_text}, 累计净流入"
                f"{f'{total_net_yi:+.2f}亿' if total_net_yi is not None else 'N/A'}; "
                f"资金信号={flow_signal}"
            )
            total_net_display = (
                f"{total_net_yi:+.2f}亿" if total_net_yi is not None else "N/A"
            )

            if ctx:
                await ctx.info(
                    f"✅ 北向资金流向获取完成", extra={"total_net": total_net_display}
                )

            artifact = create_artifact_envelope(
                component_type="north_bound_flow",
                name="北向资金流向",
                content=result,
                description=summary_text,
            )

            return create_artifact_response(summary=summary_text, artifact=artifact)

        except Exception as e:
            logger.error(f"Get north bound flow failed: {e}", exc_info=True)
            if ctx:
                await ctx.error(f"❌ 获取北向资金流向失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "north_bound_flow"}

    @mcp.tool(tags={"money-flow"})
    async def get_chip_distribution(
        symbol: str | None = None,
        ts_code: str | None = None,
        period_days: int = 120,
        price_bins: int = 50,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取筹码分布数据。

        WHEN TO USE:
        - 用户问“这只股票的主力成本区/套牢区在哪里？”
        - 需要识别支撑位、压力位、平均成本、获利盘比例
        - 想判断当前价格相对筹码峰的位置

        CONCEPT:
        筹码分布用历史成交量与价格估算不同价位的持仓密集区，可辅助理解成本结构、套牢盘和潜在抛压/支撑。

        DIFFERENTIATION:
        - 这是“成本结构/筹码位置”工具，不直接回答资金今天流入多少；短线资金流请用 get_money_flow
        - 看外资流量请用 get_north_bound_flow
        - 看个股相对指数强弱请用 get_relative_strength

        next_recommended_tools:
        - get_money_flow
        - get_relative_strength
        - calculate_risk_metrics
        """
        if not symbol and not ts_code:
            return {"error": "symbol or ts_code is required"}
        raw_symbol = ts_code or symbol
        if ctx:
            await ctx.info(
                f"🔧 获取筹码分布: {raw_symbol}",
                extra={"symbol": raw_symbol, "period_days": period_days},
            )

        try:
            logger.info(
                "MCP tool called: get_chip_distribution",
                symbol=raw_symbol,
                period_days=period_days,
                price_bins=price_bins,
            )
            result = await money_flow_use_cases.get_chip_distribution_detail(
                raw_symbol, period_days, price_bins
            )
            result["component_type"] = "chip_distribution"

            # Normalize to competitor format
            ts_code = result.get("ts_code") or result.get("symbol") or raw_symbol
            fallback_exchange = (
                raw_symbol.split(":", 1)[0] if ":" in raw_symbol else None
            )
            ts_code = to_ts_code(ts_code, fallback_exchange=fallback_exchange)

            # 构建摘要
            summary = result.get("summary", {})
            profit_ratio = summary.get("profit_ratio", 0)
            avg_cost = summary.get("avg_cost", 0)
            concentration = summary.get("concentration_90", 0)
            main_peak = summary.get("main_peak_price", 0)

            summary_text = (
                f"{ts_code}筹码分布/成本结构快照:\n"
                f"- 获利比例: {profit_ratio*100:.1f}%\n"
                f"- 平均成本: {avg_cost:.2f}元\n"
                f"- 主峰价格/成本区间: {main_peak:.2f} / {concentration:.2f}"
            )

            if ctx:
                await ctx.info(
                    f"✅ 筹码分布获取完成: {ts_code}",
                    extra={"profit_ratio": profit_ratio, "avg_cost": avg_cost},
                )

            artifact = create_artifact_envelope(
                component_type="chip_distribution",
                name=f"Chip Distribution: {ts_code}",
                content={
                    "ts_code": ts_code,
                    "trade_date": result.get("trade_date"),
                    "chip_trade_date": result.get("chip_trade_date"),
                    "price_trade_date": result.get("price_trade_date"),
                    "current_price": result.get("current_price"),
                    "avg_cost": result.get("avg_cost") or summary.get("avg_cost"),
                    "support_price": result.get("support_price"),
                    "resistance_price": result.get("resistance_price"),
                    "profit_ratio": result.get("profit_ratio")
                    or summary.get("profit_ratio"),
                    "loss_ratio": result.get("loss_ratio"),
                    "flat_ratio": result.get("flat_ratio"),
                    "distribution": result.get("distribution") or [],
                    "data": result.get("data"),
                },
                description=(
                    f"Chip Distribution (Cost Structure) Snapshot for {ts_code}. "
                    f"Chip Date: {result.get('chip_trade_date')}, "
                    f"Price Reference Date: {result.get('price_trade_date')}. "
                    f"Avg Cost: {avg_cost:.2f}. "
                    f"Key Levels: Support at {result.get('support_price')}, "
                    f"Resistance at {result.get('resistance_price')}. "
                    f"Profit Ratio: {profit_ratio*100:.1f}%."
                ),
                metadata={
                    "type": "chip_distribution",
                    "ts_code": ts_code,
                    "trade_date": result.get("trade_date"),
                    "chip_trade_date": result.get("chip_trade_date"),
                    "price_trade_date": result.get("price_trade_date"),
                },
            )

            return create_artifact_response(summary=summary_text, artifact=artifact)

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败: {symbol}", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="chip_distribution", name=f"{symbol} 筹码分布"
            )
        except Exception as e:
            logger.error(f"Get chip distribution failed: {e}", exc_info=True)
            if ctx:
                await ctx.error(
                    f"❌ 获取筹码分布失败: {symbol}", extra={"error": str(e)}
                )
            return {
                "error": str(e),
                "symbol": symbol,
                "component_type": "chip_distribution",
            }

    @mcp.tool(tags={"money-flow"})
    async def get_money_supply(months: int = 60, ctx: Context = None) -> Dict[str, Any]:
        """获取中国货币流动性 (M1/M2)。

        WHEN TO USE:
        - 用户问“当前国内货币环境偏宽松还是偏收紧？”
        - 需要看M1、M2同比及剪刀差变化
        - 想做中观/宏观流动性背景判断，而不是股票级分析

        CONCEPT:
        M1更偏企业活期与交易性资金，M2覆盖更广。M1-M2剪刀差常被用来观察实体活跃度与资金沉淀程度。

        DIFFERENTIATION:
        - 这是货币供给口径；看社融信用扩张请用 get_social_financing
        - 看利率价格信号请用 get_interest_rates
        - 看A股市场层面的交易流动性请用 get_market_liquidity

        next_recommended_tools:
        - get_social_financing
        - get_interest_rates
        - get_gdp_data
        """
        if ctx:
            await ctx.info("🔧 获取货币供应量", extra={"months": months})

        try:
            logger.info("MCP tool called: get_money_supply", months=months)
            result = await money_flow_use_cases.get_money_supply(months)
            result["component_type"] = "money_supply"

            content = result.get("data", []) or []
            content = sorted(content, key=lambda x: str(x.get("month", "")))
            if months > 0:
                content = content[-months:]

            def _to_float(v: Any) -> float | None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            def _fmt_pct(v: float | None) -> str:
                return f"{v:.1f}%" if v is not None else "N/A"

            latest = content[-1] if content else {}
            prev = content[-2] if len(content) >= 2 else {}
            latest_month = str(latest.get("month") or "N/A")

            m1_yoy = _to_float(latest.get("m1_yoy"))
            m2_yoy = _to_float(latest.get("m2_yoy"))
            prev_m1_yoy = _to_float(prev.get("m1_yoy"))
            prev_m2_yoy = _to_float(prev.get("m2_yoy"))

            spread = _to_float(latest.get("m1_m2_spread"))
            if spread is None and m1_yoy is not None and m2_yoy is not None:
                spread = m1_yoy - m2_yoy
            prev_spread = _to_float(prev.get("m1_m2_spread"))
            if (
                prev_spread is None
                and prev_m1_yoy is not None
                and prev_m2_yoy is not None
            ):
                prev_spread = prev_m1_yoy - prev_m2_yoy

            spread_delta_text = (
                f"(较上月{(spread - prev_spread):+.1f}pct)"
                if spread is not None and prev_spread is not None
                else ""
            )
            if spread is None:
                liquidity_signal = "未知"
            elif spread >= 0:
                liquidity_signal = "企业活期改善"
            else:
                liquidity_signal = "资金偏沉淀"

            summary_text = (
                f"中国货币供应(近{months}月): 最新{latest_month}M1同比{_fmt_pct(m1_yoy)}, "
                f"M2同比{_fmt_pct(m2_yoy)}, M1-M2剪刀差{_fmt_pct(spread)}{spread_delta_text}; "
                f"流动性信号={liquidity_signal}"
            )
            artifact = create_artifact_envelope(
                component_type="money_supply",
                name="Money Supply Data",
                content=content,
                description=summary_text,
                metadata={"type": "money_supply"},
            )

            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get money supply failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 获取货币供应量失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "money_supply"}

    @mcp.tool(tags={"money-flow"})
    async def get_inflation_data(
        months: int = 60, ctx: Context = None
    ) -> Dict[str, Any]:
        """获取中国月度通胀指标 (CPI/PPI)。

        WHEN TO USE:
        - 用户问"通胀情况如何""CPI/PPI最新数据""有没有通缩压力"
        - 需要判断消费端和工业端价格走势，辅助宏观环境判断

        CONCEPT:
        CPI反映消费端价格水平，PPI反映工业品出厂价格。CPI-PPI剪刀差可观察上下游利润分配格局。

        DIFFERENTIATION:
        - 这是价格/通胀口径；看货币量口径请用 get_money_supply
        - 看实体经济景气请用 get_pmi_data；看经济增长请用 get_gdp_data
        - 看利率政策信号请用 get_interest_rates

        next_recommended_tools:
        - get_money_supply
        - get_pmi_data
        - get_interest_rates
        """
        if ctx:
            await ctx.info("🔧 获取通胀指标", extra={"months": months})

        try:
            logger.info("MCP tool called: get_inflation_data", months=months)
            result = await money_flow_use_cases.get_inflation_data(months)
            result["component_type"] = "inflation_data"

            data = result.get("data", {})
            cpi = data.get("CPI", []) if isinstance(data, dict) else []
            ppi = data.get("PPI", []) if isinstance(data, dict) else []
            cpi = sorted(cpi, key=lambda x: str(x.get("month", "")))
            ppi = sorted(ppi, key=lambda x: str(x.get("month", "")))
            if months > 0:
                cpi = cpi[-months:]
                ppi = ppi[-months:]

            def _to_float(v: Any) -> float | None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            def _fmt_pct(v: float | None) -> str:
                return f"{v:.1f}%" if v is not None else "N/A"

            cpi_latest = cpi[-1] if cpi else {}
            cpi_prev = cpi[-2] if len(cpi) >= 2 else {}
            ppi_latest = ppi[-1] if ppi else {}
            ppi_prev = ppi[-2] if len(ppi) >= 2 else {}
            latest_month = str(cpi_latest.get("month") or ppi_latest.get("month") or "N/A")

            cpi_yoy = _to_float(cpi_latest.get("nt_yoy"))
            cpi_yoy_prev = _to_float(cpi_prev.get("nt_yoy"))
            cpi_mom = _to_float(cpi_latest.get("nt_mom"))
            ppi_yoy = _to_float(ppi_latest.get("ppi_yoy"))
            ppi_yoy_prev = _to_float(ppi_prev.get("ppi_yoy"))
            spread = (
                cpi_yoy - ppi_yoy
                if cpi_yoy is not None and ppi_yoy is not None
                else None
            )

            cpi_delta_text = (
                f"(较上月{(cpi_yoy - cpi_yoy_prev):+.1f}pct)"
                if cpi_yoy is not None and cpi_yoy_prev is not None
                else ""
            )
            ppi_delta_text = (
                f"(较上月{(ppi_yoy - ppi_yoy_prev):+.1f}pct)"
                if ppi_yoy is not None and ppi_yoy_prev is not None
                else ""
            )

            if cpi_yoy is None and ppi_yoy is None:
                inflation_signal = "未知"
            elif (
                cpi_yoy is not None
                and ppi_yoy is not None
                and cpi_yoy > 0
                and ppi_yoy < 0
            ):
                inflation_signal = "消费偏温和、上游偏弱"
            elif cpi_yoy is not None and cpi_yoy >= 2:
                inflation_signal = "通胀压力抬升"
            elif ppi_yoy is not None and ppi_yoy <= -2:
                inflation_signal = "工业品价格偏弱"
            else:
                inflation_signal = "价格总体平稳"

            summary_text = (
                f"中国通胀(近{months}月): 最新{latest_month}CPI同比{_fmt_pct(cpi_yoy)}"
                f"{cpi_delta_text}, 环比{_fmt_pct(cpi_mom)}; PPI同比{_fmt_pct(ppi_yoy)}"
                f"{ppi_delta_text}, CPI-PPI剪刀差{_fmt_pct(spread)}; "
                f"价格信号={inflation_signal}"
            )
            artifact = create_artifact_envelope(
                component_type="inflation_data",
                name="Inflation Data",
                content={"cpi": cpi, "ppi": ppi},
                description=summary_text,
                metadata={"type": "inflation_data"},
            )

            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get inflation data failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 获取通胀指标失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "inflation_data"}

    @mcp.tool(tags={"money-flow"})
    async def get_pmi_data(months: int = 60, ctx: Context = None) -> Dict[str, Any]:
        """获取中国官方 PMI 数据。

        WHEN TO USE:
        - 用户问"制造业景气度如何""PMI最新多少""经济在扩张还是收缩"
        - 需要判断实体经济短期景气方向（制造业/非制造业/综合）

        CONCEPT:
        PMI以50为荣枯线，>50表示扩张，<50表示收缩。制造业PMI、非制造业PMI和综合PMI共同勾勒景气全貌。

        DIFFERENTIATION:
        - 这是景气/实体经济口径；看通胀请用 get_inflation_data
        - 看经济增长总量请用 get_gdp_data；看信用扩张请用 get_social_financing

        next_recommended_tools:
        - get_gdp_data
        - get_inflation_data
        - get_social_financing
        """
        if ctx:
            await ctx.info("🔧 获取 PMI", extra={"months": months})

        try:
            logger.info("MCP tool called: get_pmi_data", months=months)
            result = await money_flow_use_cases.get_pmi_data(months)
            result["component_type"] = "pmi_data"

            content = result.get("data", []) or []

            def _month_of(row: Dict[str, Any]) -> str:
                # Tushare cn_pmi often uses uppercase MONTH.
                m = row.get("month")
                if m is None:
                    m = row.get("MONTH")
                return str(m or "")

            content = sorted(content, key=_month_of)
            if months > 0:
                content = content[-months:]

            def _to_float(v: Any) -> float | None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            latest = content[-1] if content else {}
            prev = content[-2] if len(content) >= 2 else {}
            latest_month = _month_of(latest) or "N/A"

            def _pick(row: Dict[str, Any], *keys: str) -> Any:
                for k in keys:
                    if k in row and row.get(k) is not None:
                        return row.get(k)
                return None

            # Field compatibility:
            # - Generic schema: pmi / pmi_non_mfg / pmi_composite
            # - Tushare cn_pmi schema: PMI010000 / PMI020200 / PMI030000
            mfg = _to_float(_pick(latest, "pmi", "PMI010000"))
            mfg_prev = _to_float(_pick(prev, "pmi", "PMI010000"))
            non_mfg = _to_float(
                _pick(
                    latest,
                    "pmi_non_mfg",
                    "pmi_nonmanufacturing",
                    "PMI020200",
                    "PMI020000",
                )
            )
            non_mfg_prev = _to_float(
                _pick(
                    prev,
                    "pmi_non_mfg",
                    "pmi_nonmanufacturing",
                    "PMI020200",
                    "PMI020000",
                )
            )
            composite = _to_float(_pick(latest, "pmi_composite", "PMI030000"))
            composite_prev = _to_float(_pick(prev, "pmi_composite", "PMI030000"))

            def _fmt_val(v: float | None) -> str:
                return f"{v:.1f}" if v is not None else "N/A"

            def _fmt_delta(curr: float | None, base: float | None) -> str:
                if curr is None or base is None:
                    return ""
                return f",环比{(curr - base):+.1f}"

            mfg_state = (
                "扩张"
                if isinstance(mfg, (int, float)) and mfg >= 50
                else ("收缩" if isinstance(mfg, (int, float)) else "未知")
            )
            non_mfg_state = (
                "扩张"
                if isinstance(non_mfg, (int, float)) and non_mfg >= 50
                else ("收缩" if isinstance(non_mfg, (int, float)) else "未知")
            )
            if isinstance(mfg, (int, float)) and isinstance(non_mfg, (int, float)):
                macro_state = (
                    "偏强"
                    if mfg >= 50 and non_mfg >= 50
                    else ("偏弱" if mfg < 50 and non_mfg < 50 else "分化")
                )
            elif isinstance(composite, (int, float)):
                macro_state = "偏强" if composite >= 50 else "偏弱"
            else:
                macro_state = "未知"
            summary_text = (
                f"中国PMI(近{months}月): 最新{latest_month}制造业{_fmt_val(mfg)}"
                f"({mfg_state}{_fmt_delta(mfg, mfg_prev)}), 非制造业{_fmt_val(non_mfg)}"
                f"({non_mfg_state}{_fmt_delta(non_mfg, non_mfg_prev)}), 综合{_fmt_val(composite)}"
                f"{_fmt_delta(composite, composite_prev)}; 景气判断={macro_state}"
            )
            artifact = create_artifact_envelope(
                component_type="pmi_data",
                name="PMI Data",
                content=content,
                description=summary_text,
                metadata={"type": "pmi_data"},
            )

            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get PMI data failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 获取 PMI 数据失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "pmi_data"}

    @mcp.tool(tags={"money-flow"})
    async def get_gdp_data(quarters: int = 20, ctx: Context = None) -> Dict[str, Any]:
        """获取中国季度 GDP 增长数据。

        WHEN TO USE:
        - 用户问"GDP增速多少""经济增长情况""三产结构如何"
        - 需要判断宏观经济整体增速和产业结构

        CONCEPT:
        GDP是衡量经济体总产出的核心指标。分一产(农业)/二产(工业)/三产(服务业)，可观察增长结构。

        DIFFERENTIATION:
        - 这是经济增长总量口径；看短期景气请用 get_pmi_data
        - 看通胀请用 get_inflation_data；看信用环境请用 get_social_financing

        next_recommended_tools:
        - get_pmi_data
        - get_inflation_data
        - get_money_supply
        """
        if ctx:
            await ctx.info("🔧 获取 GDP", extra={"quarters": quarters})

        try:
            logger.info("MCP tool called: get_gdp_data", quarters=quarters)
            result = await money_flow_use_cases.get_gdp_data(quarters)
            result["component_type"] = "gdp_data"

            content = result.get("data", []) or []
            content = sorted(content, key=lambda x: str(x.get("quarter", "")))
            if quarters > 0:
                content = content[-quarters:]

            def _to_float(v: Any) -> float | None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            latest = content[-1] if content else {}
            prev = content[-2] if len(content) >= 2 else {}
            latest_quarter = str(latest.get("quarter") or "N/A")

            gdp_yoy = _to_float(latest.get("gdp_yoy"))
            gdp_yoy_prev = _to_float(prev.get("gdp_yoy"))
            pi_yoy = _to_float(latest.get("pi_yoy"))
            si_yoy = _to_float(latest.get("si_yoy"))
            ti_yoy = _to_float(latest.get("ti_yoy"))

            def _fmt_pct(v: float | None) -> str:
                return f"{v:.1f}%" if v is not None else "N/A"

            gdp_delta_text = (
                f"(较上季{(gdp_yoy - gdp_yoy_prev):+.1f}pct)"
                if gdp_yoy is not None and gdp_yoy_prev is not None
                else ""
            )

            sector_candidates = []
            if pi_yoy is not None:
                sector_candidates.append(("一产", pi_yoy))
            if si_yoy is not None:
                sector_candidates.append(("二产", si_yoy))
            if ti_yoy is not None:
                sector_candidates.append(("三产", ti_yoy))
            lead_sector = (
                f"{max(sector_candidates, key=lambda x: x[1])[0]}领先"
                if sector_candidates
                else "结构未知"
            )

            summary_text = (
                f"中国GDP(近{quarters}季): 最新{latest_quarter}同比{_fmt_pct(gdp_yoy)}"
                f"{gdp_delta_text}; 三产同比一产{_fmt_pct(pi_yoy)}/二产{_fmt_pct(si_yoy)}"
                f"/三产{_fmt_pct(ti_yoy)}({lead_sector})"
            )
            artifact = create_artifact_envelope(
                component_type="gdp_data",
                name="GDP Data",
                content=content,
                description=summary_text,
                metadata={"type": "gdp_data"},
            )

            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get GDP data failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 获取 GDP 数据失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "gdp_data"}

    @mcp.tool(tags={"money-flow"})
    async def get_social_financing(
        months: int = 60, ctx: Context = None
    ) -> Dict[str, Any]:
        """获取中国社会融资总量。

        WHEN TO USE:
        - 用户问"社融数据怎么样""信用环境偏宽松还是偏紧""新增信贷情况"
        - 需要判断实体信用扩张力度和金融对经济的支持程度

        CONCEPT:
        社融(社会融资规模)衡量实体从金融体系获得资金总量。存量同比增速是判断信用周期的核心指标。
        >9%偏强扩张，<8%偏弱。

        DIFFERENTIATION:
        - 这是信用/融资口径；看货币供给请用 get_money_supply
        - 看利率价格请用 get_interest_rates；看经济增长请用 get_gdp_data

        next_recommended_tools:
        - get_money_supply
        - get_interest_rates
        - get_pmi_data
        """
        if ctx:
            await ctx.info("🔧 获取社会融资总量", extra={"months": months})

        try:
            logger.info("MCP tool called: get_social_financing", months=months)
            # Keep enough history to derive stock-yoy from stk_endval when upstream
            # does not provide explicit stk_yoy.
            fetch_months = max(months, 24)
            result = await money_flow_use_cases.get_social_financing(fetch_months)
            result["component_type"] = "social_financing"

            raw_data = result.get("data", []) or []

            def _month_of(row: Dict[str, Any]) -> str:
                m = row.get("month")
                if m is None:
                    m = row.get("MONTH")
                return str(m or "")

            # Normalize rows first so downstream logic has stable keys.
            normalized = [
                {
                    "month": _month_of(r),
                    "inc_month": r.get("inc_month"),
                    "inc_cumval": r.get("inc_cumval"),
                    "stk_endval": r.get("stk_endval"),
                    "stk_yoy": r.get("stk_yoy"),
                }
                for r in raw_data
            ]
            normalized = sorted(normalized, key=lambda x: str(x.get("month", "")), reverse=True)
            content = normalized[:months] if months and months > 0 else normalized

            def _to_float(v: Any) -> float | None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            def _derive_stk_yoy(row: Dict[str, Any]) -> float | None:
                direct = _to_float(row.get("stk_yoy"))
                if direct is not None:
                    return direct

                month = str(row.get("month") or "")
                if len(month) != 6 or not month.isdigit():
                    return None

                prev_year_month = f"{int(month[:4]) - 1:04d}{month[4:]}"
                base_row = next(
                    (r for r in normalized if str(r.get("month") or "") == prev_year_month),
                    None,
                )
                if not base_row:
                    return None

                curr = _to_float(row.get("stk_endval"))
                base = _to_float(base_row.get("stk_endval"))
                if curr is None or base is None or base == 0:
                    return None
                return (curr / base - 1.0) * 100.0

            latest = content[0] if content else {}
            prev = content[1] if len(content) >= 2 else {}
            latest_month = str(latest.get("month") or "N/A")

            inc_month = _to_float(latest.get("inc_month"))
            prev_inc_month = _to_float(prev.get("inc_month"))
            stk_yoy = _derive_stk_yoy(latest)
            prev_stk_yoy = _derive_stk_yoy(prev)

            def _fmt_num(v: float | None) -> str:
                if v is None:
                    return "N/A"
                return f"{v:,.1f}"

            inc_delta_text = (
                f"(较上月{(inc_month - prev_inc_month):+,.1f})"
                if inc_month is not None and prev_inc_month is not None
                else ""
            )
            stk_yoy_delta_text = (
                f"(较上月{(stk_yoy - prev_stk_yoy):+.1f}pct)"
                if stk_yoy is not None and prev_stk_yoy is not None
                else ""
            )

            if stk_yoy is None:
                credit_signal = "未知"
            elif stk_yoy >= 9:
                credit_signal = "信用扩张偏强"
            elif stk_yoy <= 8:
                credit_signal = "信用扩张偏弱"
            else:
                credit_signal = "信用扩张中性"

            summary_text = (
                f"中国社融(近{months}月): 最新{latest_month}新增社融{_fmt_num(inc_month)}"
                f"{inc_delta_text}, 存量同比{f'{stk_yoy:.1f}%' if stk_yoy is not None else 'N/A'}"
                f"{stk_yoy_delta_text}; 信用信号={credit_signal}"
            )
            artifact = create_artifact_envelope(
                component_type="social_financing",
                name="Social Financing Data",
                content=content,
                description=summary_text,
                metadata={"type": "social_financing"},
            )

            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get social financing failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 获取社会融资失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "social_financing"}

    @mcp.tool(tags={"money-flow"})
    async def get_interest_rates(
        shibor_days: int = 252, lpr_months: int = 60, ctx: Context = None
    ) -> Dict[str, Any]:
        """获取中国利率数据 (SHIBOR + LPR)。

        WHEN TO USE:
        - 用户问"利率水平如何""央行有没有降息/加息""Shibor走势"
        - 需要判断货币政策宽松/收紧方向和资金价格水平

        CONCEPT:
        SHIBOR是银行间拆借利率(短端)，LPR是贷款基准利率(中长端)。两者结合可观察利率曲线形态和政策信号。

        DIFFERENTIATION:
        - 这是利率/资金价格口径；看货币量口径请用 get_money_supply
        - 看信用扩张请用 get_social_financing；看国债收益率曲线请用 get_bond_yield

        next_recommended_tools:
        - get_money_supply
        - get_social_financing
        - get_bond_yield
        """
        if ctx:
            await ctx.info(
                "🔧 获取利率数据",
                extra={"shibor_days": shibor_days, "lpr_months": lpr_months},
            )

        try:
            logger.info(
                "MCP tool called: get_interest_rates",
                shibor_days=shibor_days,
                lpr_months=lpr_months,
            )
            result = await money_flow_use_cases.get_interest_rates(
                shibor_days, lpr_months
            )
            result["component_type"] = "interest_rates"

            shibor = result.get("data", {}).get("shibor", []) or []
            lpr = result.get("data", {}).get("lpr", []) or []

            shibor = sorted(shibor, key=lambda x: str(x.get("date", "")), reverse=True)
            lpr = sorted(
                lpr,
                key=lambda x: str(x.get("date") or x.get("month", "")),
                reverse=True,
            )

            if shibor_days and shibor_days > 0:
                shibor = shibor[:shibor_days]
            if lpr_months and lpr_months > 0:
                lpr = lpr[:lpr_months]

            shibor_content = [
                {
                    "date": r.get("date"),
                    "on": r.get("on"),
                    "1w": r.get("1w"),
                    "2w": r.get("2w"),
                    "1m": r.get("1m"),
                    "3m": r.get("3m"),
                    "6m": r.get("6m"),
                    "9m": r.get("9m"),
                    "1y": r.get("1y"),
                }
                for r in shibor
            ]
            lpr_content = [
                {
                    "date": r.get("date") or r.get("month"),
                    "lpr_1y": r.get("1y"),
                    "lpr_5y": r.get("5y"),
                }
                for r in lpr
            ]

            def _to_float(v: Any) -> float | None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            shibor_latest = shibor_content[0] if shibor_content else {}
            shibor_prev = shibor_content[1] if len(shibor_content) >= 2 else {}
            lpr_latest = lpr_content[0] if lpr_content else {}
            lpr_prev = lpr_content[1] if len(lpr_content) >= 2 else {}

            latest_date = str(
                shibor_latest.get("date") or lpr_latest.get("date") or "N/A"
            )
            shibor_1w = _to_float(shibor_latest.get("1w"))
            shibor_1y = _to_float(shibor_latest.get("1y"))
            prev_shibor_1w = _to_float(shibor_prev.get("1w"))

            lpr_1y = _to_float(lpr_latest.get("lpr_1y"))
            lpr_5y = _to_float(lpr_latest.get("lpr_5y"))
            prev_lpr_1y = _to_float(lpr_prev.get("lpr_1y"))
            prev_lpr_5y = _to_float(lpr_prev.get("lpr_5y"))

            curve_spread = (
                shibor_1y - shibor_1w
                if shibor_1y is not None and shibor_1w is not None
                else None
            )
            lpr_spread = (
                lpr_5y - lpr_1y if lpr_1y is not None and lpr_5y is not None else None
            )
            lpr_1y_delta = (
                lpr_1y - prev_lpr_1y
                if lpr_1y is not None and prev_lpr_1y is not None
                else None
            )
            lpr_5y_delta = (
                lpr_5y - prev_lpr_5y
                if lpr_5y is not None and prev_lpr_5y is not None
                else None
            )

            if lpr_1y_delta is None and lpr_5y_delta is None:
                policy_signal = "未知"
            elif (
                (lpr_1y_delta is None or lpr_1y_delta == 0)
                and (lpr_5y_delta is None or lpr_5y_delta == 0)
            ):
                policy_signal = "政策利率按兵不动"
            elif (
                (lpr_1y_delta is not None and lpr_1y_delta < 0)
                or (lpr_5y_delta is not None and lpr_5y_delta < 0)
            ):
                policy_signal = "政策利率偏宽松"
            else:
                policy_signal = "政策利率偏收紧"

            def _fmt_pct(v: float | None) -> str:
                return f"{v:.2f}%" if v is not None else "N/A"

            summary_text = (
                f"中国利率(Shibor+LPR): 最新{latest_date}Shibor1W/1Y="
                f"{_fmt_pct(shibor_1w)}/{_fmt_pct(shibor_1y)}, 期限利差{_fmt_pct(curve_spread)}"
                f"{f'(1W较前值{(shibor_1w - prev_shibor_1w):+.2f}pct)' if shibor_1w is not None and prev_shibor_1w is not None else ''}; "
                f"LPR1Y/5Y={_fmt_pct(lpr_1y)}/{_fmt_pct(lpr_5y)}, 挂钩利差{_fmt_pct(lpr_spread)}; "
                f"利率信号={policy_signal}"
            )

            artifacts = [
                create_artifact_envelope(
                    component_type="interest_rates_shibor",
                    name="SHIBOR Interest Rates",
                    content=shibor_content,
                    description="China Interbank Offered Rate (SHIBOR): Term Structure (Overnight to 1 Year) - Last 1 Year",
                    metadata={"type": "interest_rates_shibor"},
                ),
                create_artifact_envelope(
                    component_type="interest_rates_lpr",
                    name="LPR Interest Rates",
                    content=lpr_content,
                    description="China Loan Prime Rate (LPR, shibor_lpr): 1-Year and 5-Year Benchmark Lending Rates - Last 5 Years",
                    metadata={"type": "interest_rates_lpr"},
                ),
            ]

            return create_artifact_list_response(
                summary=summary_text, artifacts=artifacts
            )
        except Exception as e:
            logger.error(f"Get interest rates failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 获取利率失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "interest_rates"}

    @mcp.tool(tags={"money-flow"})
    async def get_market_liquidity(
        days: int = 60, ctx: Context = None
    ) -> Dict[str, Any]:
        """获取 A 股市场流动性指标。

        WHEN TO USE:
        - 用户问"市场流动性怎么样""融资融券余额多少""北向+两融整体情况"
        - 需要同时看北向资金和融资融券余额的组合流动性画面

        CONCEPT:
        综合展示北向净流入趋势和融资融券余额趋势，是A股两大核心增量资金的概览。

        DIFFERENTIATION:
        - 这是"多维度市场流动性概览"；仅看北向资金请用 get_north_bound_flow
        - 看个股融资融券请用 get_margin_trading
        - 看板块资金排名请用 get_market_money_flow

        next_recommended_tools:
        - get_north_bound_flow
        - get_margin_trading
        - get_market_money_flow
        """
        if ctx:
            await ctx.info("🔧 获取市场流动性", extra={"days": days})

        try:
            logger.info("MCP tool called: get_market_liquidity", days=days)
            result = await money_flow_use_cases.get_market_liquidity(days)
            result["component_type"] = "market_liquidity"

            data = result.get("data", {})
            north_flow = data.get("north_flow", [])
            margin = data.get("margin", [])
            latest_north = north_flow[-1] if north_flow else {}
            latest_margin = margin[-1] if margin else {}
            north_value = latest_north.get("north_money")
            margin_value = latest_margin.get("rzrqye")
            latest_date = (
                latest_north.get("trade_date")
                or latest_margin.get("trade_date")
                or "N/A"
            )
            summary_text = (
                f"A股流动性({days}日): 最新{latest_date}北向净流入="
                f"{north_value if north_value is not None else 'N/A'}, "
                f"融资融券余额={margin_value if margin_value is not None else 'N/A'}, "
                f"样本={len(north_flow)}/{len(margin)}日"
            )

            north_series = []
            if north_flow:
                north_series = [
                    {
                        "name": "北向净流入",
                        "type": "line",
                        "data": [
                            {"x": r.get("trade_date"), "y": r.get("north_money")}
                            for r in north_flow
                        ],
                    }
                ]

            margin_series = []
            if margin:
                margin_series = [
                    {
                        "name": "融资融券余额",
                        "type": "line",
                        "data": [
                            {"x": r.get("trade_date"), "y": r.get("rzrqye")}
                            for r in margin
                        ],
                    }
                ]

            artifacts = [
                create_chart_artifact(
                    title="北向资金趋势",
                    chart_type="line",
                    unit="",
                    x_label="日期",
                    y_label="净流入",
                    series=north_series,
                    description="北向资金趋势",
                    metadata={"type": "chart", "dataset": "north_flow"},
                    name="Northbound Flow",
                ),
                create_chart_artifact(
                    title="融资融券余额",
                    chart_type="line",
                    unit="",
                    x_label="日期",
                    y_label="余额",
                    series=margin_series,
                    description="融资融券余额趋势",
                    metadata={"type": "chart", "dataset": "margin"},
                    name="Margin Balance",
                ),
            ]

            return create_artifact_list_response(
                summary=summary_text, artifacts=artifacts
            )
        except Exception as e:
            logger.error(f"Get market liquidity failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 获取市场流动性失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "market_liquidity"}

    @mcp.tool(tags={"money-flow"})
    async def get_market_money_flow(
        trade_date: str = None,
        top_n: int = 20,
        include_outflow: bool = True,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取板块资金流向统计（含净流入TopN与数据新鲜度门禁）。

        WHEN TO USE:
        - 用户问"今天哪些板块资金流入最多""板块资金排名""主力在买什么板块"
        - 需要全市场板块维度的资金排名和热力概览

        CONCEPT:
        按板块统计当日资金净流入/流出排名，含新鲜度门禁（判断数据是否可用于趋势结论）。
        TopN排名可快速定位当日资金关注焦点。

        DIFFERENTIATION:
        - 这是"板块排名"视角；看单个板块的资金流历史请用 get_sector_money_flow_history
        - 看板块走势(价格)请用 get_sector_trend；看板块估值请用 get_sector_valuation_metrics
        - 看个股资金流请用 get_money_flow

        next_recommended_tools:
        - get_sector_money_flow_history
        - get_sector_trend
        - get_sector_valuation_metrics
        """
        if ctx:
            await ctx.info(
                "🔧 获取板块资金流向",
                extra={
                    "trade_date": trade_date,
                    "top_n": top_n,
                    "include_outflow": include_outflow,
                },
            )

        try:
            logger.info("MCP tool called: get_market_money_flow", trade_date=trade_date)
            result = await money_flow_use_cases.get_market_money_flow(
                trade_date=trade_date,
                top_n=top_n,
                include_outflow=include_outflow,
            )
            result["component_type"] = "market_money_flow"

            requested_trade_date = result.get("requested_trade_date") or trade_date
            as_of_trade_date = result.get("as_of_trade_date")
            data_freshness = result.get("data_freshness", "unknown")
            top_n_effective = int(result.get("top_n") or top_n or 20)
            overview = result.get("market_overview", {})
            total_net = overview.get("total_net_amount", 0.0) or 0.0
            inflow = overview.get("inflow_count", 0) or 0
            outflow = overview.get("outflow_count", 0) or 0
            top_inflow = result.get("top_inflow", []) or []
            top_outflow = result.get("top_outflow", []) or []
            gate_allowed = bool(result.get("trend_conclusion_allowed", False))
            blocked_reason = result.get("blocked_reason")

            freshness_suffix = ""
            if requested_trade_date and as_of_trade_date and requested_trade_date != as_of_trade_date:
                freshness_suffix = (
                    f"（请求{requested_trade_date}，实际返回{as_of_trade_date}）"
                )
            elif as_of_trade_date:
                freshness_suffix = f"（数据日期{as_of_trade_date}）"

            gate_text = (
                "趋势结论门禁=PASS"
                if gate_allowed
                else f"趋势结论门禁=BLOCKED({blocked_reason or 'insufficient_data'})"
            )
            summary_text = (
                f"板块资金流向Top{top_n_effective}（{requested_trade_date or '最新'}）{freshness_suffix}: "
                f"净流入{inflow}个、净流出{outflow}个，全市场净流入 {total_net:.2f}; "
                f"data_freshness={data_freshness}; {gate_text}"
            )

            inflow_rows = [
                {
                    "rank": r.get("rank"),
                    "sector_name": r.get("sector_name"),
                    "net_amount": r.get("net_amount"),
                    "pct_chg": r.get("pct_chg"),
                }
                for r in top_inflow
            ]
            outflow_rows = [
                {
                    "rank": r.get("rank"),
                    "sector_name": r.get("sector_name"),
                    "net_amount": r.get("net_amount"),
                    "pct_chg": r.get("pct_chg"),
                }
                for r in top_outflow
            ]

            artifacts = [
                create_chart_artifact(
                    title="板块资金流向",
                    chart_type="bar",
                    unit="",
                    x_label="板块",
                    y_label="净流入",
                    series=[
                        {
                            "name": "净流入",
                            "type": "bar",
                            "data": [
                                {
                                    "x": r.get("sector_name"),
                                    "y": r.get("net_amount"),
                                }
                                for r in inflow_rows
                            ],
                        }
                    ],
                    description="板块净流入 TopN",
                    metadata={
                        "type": "chart",
                        "dataset": "market_money_flow_top_inflow",
                        "requested_trade_date": requested_trade_date,
                        "as_of_trade_date": as_of_trade_date,
                        "data_freshness": data_freshness,
                        "trend_conclusion_allowed": gate_allowed,
                        "blocked_reason": blocked_reason,
                    },
                    name="Market Money Flow",
                ),
                create_table_artifact(
                    title=f"板块资金净流入 Top{top_n_effective}",
                    columns=[
                        {"key": "rank", "label": "排名"},
                        {"key": "sector_name", "label": "板块"},
                        {"key": "net_amount", "label": "净流入"},
                        {"key": "pct_chg", "label": "涨跌幅(%)"},
                    ],
                    rows=inflow_rows,
                    tag="market_money_flow_top_inflow",
                    description="Market sector capital inflow ranking",
                ),
            ]
            if include_outflow:
                artifacts.append(
                    create_table_artifact(
                        title=f"板块资金净流出 Top{top_n_effective}",
                        columns=[
                            {"key": "rank", "label": "排名"},
                            {"key": "sector_name", "label": "板块"},
                            {"key": "net_amount", "label": "净流出"},
                            {"key": "pct_chg", "label": "涨跌幅(%)"},
                        ],
                        rows=outflow_rows,
                        tag="market_money_flow_top_outflow",
                        description="Market sector capital outflow ranking",
                    )
                )

            artifacts.append(
                create_artifact_envelope(
                    component_type="market_money_flow_gate",
                    name="Market Money Flow Gate",
                    content={
                        "requested_trade_date": requested_trade_date,
                        "as_of_trade_date": as_of_trade_date,
                        "data_freshness": data_freshness,
                        "trend_conclusion_allowed": gate_allowed,
                        "blocked_reason": blocked_reason,
                        "top_n": top_n_effective,
                        "inflow_count": inflow,
                        "outflow_count": outflow,
                    },
                    description=(
                        "Trend conclusion gate derived from market money flow freshness "
                        "and rank coverage."
                    ),
                    metadata={"type": "market_money_flow_gate"},
                    visible_to_llm=True,
                    display_in_report=True,
                )
            )

            return create_artifact_list_response(
                summary=summary_text, artifacts=artifacts
            )
        except Exception as e:
            logger.error(f"Get market money flow failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 获取板块资金流向失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "market_money_flow"}

    @mcp.tool(tags={"money-flow"})
    async def resolve_sector(
        query_text: str,
        intent: str = "trend",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """解析板块查询词，返回稳定 sector_id。

        WHEN TO USE:
        - 用户用模糊/别名称呼板块（如"白酒"而非"白酒Ⅱ"），需要先解析再查询
        - 其他板块工具返回"ambiguous"时，可用于确认精确名称

        CONCEPT:
        板块名称在数据源中可能有多种写法（如"银行"/"银行Ⅰ"/"银行Ⅱ"），本工具将模糊输入映射为
        稳定的sector_id，返回resolved/ambiguous/not_found三种状态。

        DIFFERENTIATION:
        - 这是辅助工具，不直接返回数据；获取板块走势请用 get_sector_trend
        - 获取板块资金流请用 get_sector_money_flow_history

        next_recommended_tools:
        - get_sector_trend
        - get_sector_money_flow_history
        """
        if ctx:
            await ctx.info(
                "🔧 解析板块名称",
                extra={"query_text": query_text, "intent": intent},
            )

        try:
            logger.info(
                "MCP tool called: resolve_sector",
                query_text=query_text,
                intent=intent,
            )
            result = await money_flow_use_cases.resolve_sector(
                query_text=query_text,
                intent=intent,
            )
            status = result.get("status", "not_found")
            canonical_name = result.get("canonical_name", "")
            sector_id = result.get("sector_id", "")
            candidates = result.get("candidates", []) or []

            if status == "resolved":
                summary_text = (
                    f"板块解析成功: {query_text} -> {canonical_name}({sector_id})"
                )
            elif status == "ambiguous":
                candidate_names = [
                    str(x.get("canonical_name", ""))
                    for x in candidates
                    if isinstance(x, dict)
                ]
                summary_text = (
                    f'板块名称"{query_text}"不明确，候选：'
                    f"{'、'.join([x for x in candidate_names if x])}。"
                )
            else:
                summary_text = f'未找到板块: "{query_text}"'

            artifact = create_artifact_envelope(
                component_type="sector_resolve",
                name=f"Sector Resolve: {query_text}",
                content={
                    "query_text": query_text,
                    "intent": intent,
                    "status": status,
                    "sector_id": sector_id,
                    "canonical_name": canonical_name,
                    "candidates": candidates,
                    "source": result.get("source", ""),
                },
                description=summary_text,
                metadata={
                    "type": "sector_resolve",
                    "query_text": query_text,
                    "intent": intent,
                    "status": status,
                },
                visible_to_llm=True,
                display_in_report=False,
            )

            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Resolve sector failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 板块解析失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "sector_resolve"}

    @mcp.tool(tags={"money-flow"})
    async def get_sector_trend(
        sector_name: str = "",
        days: int = 10,
        sector_id: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取板块近 N 天走势与累计涨跌幅。

        WHEN TO USE:
        - 用户问"某某板块最近走势怎么样""白酒板块涨了多少"
        - 需要看板块价格走势和区间涨跌幅

        CONCEPT:
        以板块对应指数的日线收盘价为基础，展示近N天走势和累计涨跌幅。
        板块名称模糊匹配时会返回候选列表。

        DIFFERENTIATION:
        - 这是"板块价格走势"；看板块资金流请用 get_sector_money_flow_history
        - 看板块估值PE/PB请用 get_sector_valuation_metrics
        - 看全市场板块排名请用 get_market_money_flow

        next_recommended_tools:
        - get_sector_money_flow_history
        - get_sector_valuation_metrics
        - get_market_money_flow
        """
        if ctx:
            await ctx.info(
                "🔧 获取板块走势",
                extra={"sector_name": sector_name, "sector_id": sector_id, "days": days},
            )

        try:
            logger.info(
                "MCP tool called: get_sector_trend",
                sector_name=sector_name,
                sector_id=sector_id,
                days=days,
            )
            result = await money_flow_use_cases.get_sector_trend(
                sector_name=sector_name,
                sector_id=sector_id or None,
                days=days,
            )
            query_label = sector_name or sector_id or "unknown"

            # ── 候选列表：板块名称模糊匹配返回多个候选时 ──────────────────
            if result.get("candidates"):
                candidates: list = result["candidates"]
                candidates_str = "、".join(candidates)
                summary_text = (
                    f'板块名称"{query_label}"不明确，找到以下候选板块：{candidates_str}。'
                    f"请用精确名称重新查询，例如直接使用上述某个名称。"
                )
                artifact = create_artifact_envelope(
                    component_type="sector_trend",
                    name=f"Sector Trend: {query_label}",
                    content={
                        "sector_name": query_label,
                        "index_code": "",
                        "days": days,
                        "candidates": candidates,
                        "total_pct_chg": 0,
                        "trend": [],
                    },
                    description=summary_text,
                    metadata={"type": "sector_trend", "sector_name": query_label},
                    visible_to_llm=True,
                )
                return create_artifact_response(summary=summary_text, artifact=artifact)

            index_name = result.get("sector_name") or query_label
            index_code = result.get("index_code", "")
            total_pct = result.get("total_pct_chg", 0)
            name_with_code = f"{index_name}({index_code})" if index_code else index_name
            summary_text = f"{name_with_code}板块走势（最近{days}天). 累计涨跌幅: {total_pct:+.2f}%."

            artifact = create_artifact_envelope(
                component_type="sector_trend",
                name=f"Sector Trend: {index_name}",
                content={
                    "sector_name": index_name,
                    "index_code": index_code,
                    "days": days,
                    "total_pct_chg": total_pct,
                    "trend": result.get("trend", []),
                },
                description=summary_text,
                metadata={
                    "type": "sector_trend",
                    "sector_name": index_name,
                    "index_code": index_code,
                },
            )

            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get sector trend failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 获取板块走势失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "sector_trend"}

    @mcp.tool(tags={"money-flow"})
    async def get_ggt_daily(days: int = 60, ctx: Context = None) -> Dict[str, Any]:
        """获取港股通每日成交统计。

        WHEN TO USE:
        - 用户问"港股通成交情况""南向资金流向""港股通净买入"
        - 需要跟踪内地资金通过港股通投资港股的动态

        CONCEPT:
        港股通(南向资金)是内地投资者投资港股的通道。每日成交统计反映南向资金的活跃度和方向。

        DIFFERENTIATION:
        - 这是"南向(港股通)"口径；看北向(A股)请用 get_north_bound_flow
        - 看A股市场流动性请用 get_market_liquidity

        next_recommended_tools:
        - get_north_bound_flow
        - get_market_liquidity
        """
        if ctx:
            await ctx.info("🔧 获取港股通每日成交统计", extra={"days": days})

        try:
            logger.info("MCP tool called: get_ggt_daily", days=days)
            result = await money_flow_use_cases.get_ggt_daily(days)

            rows = result.get("data", [])
            columns = [
                {"key": "trade_date", "label": "日期"},
                {"key": "buy_amount", "label": "买入(亿)", "align": "right"},
                {"key": "sell_amount", "label": "卖出(亿)", "align": "right"},
                {"key": "net_amount", "label": "净买入(亿)", "align": "right"},
                {"key": "buy_volume", "label": "买入笔数(万)", "align": "right"},
                {"key": "sell_volume", "label": "卖出笔数(万)", "align": "right"},
            ]

            latest_row = rows[-1] if rows else {}
            latest_date = latest_row.get("trade_date", "N/A")
            buy_amount = latest_row.get("buy_amount")
            sell_amount = latest_row.get("sell_amount")
            net_amount = latest_row.get("net_amount")
            summary_text = (
                f"港股通成交({len(rows)}日): 最新{latest_date}净买入"
                f"{f'{net_amount:+.2f}亿' if isinstance(net_amount, (int, float)) else 'N/A'}, "
                f"买入{f'{buy_amount:.2f}亿' if isinstance(buy_amount, (int, float)) else 'N/A'}/"
                f"卖出{f'{sell_amount:.2f}亿' if isinstance(sell_amount, (int, float)) else 'N/A'}"
            )

            artifact = create_artifact_envelope(
                component_type="table",
                name="HK Stock Connect Daily",
                content={
                    "title": "港股通每日成交统计",
                    "tag": "ggt_daily",
                    "columns": columns,
                    "rows": rows,
                },
                description="Hong Kong Stock Connect daily trading statistics",
                metadata={"type": "table", "dataset": "ggt_daily"},
                visible_to_llm=False,
                display_in_report=True,
            )

            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get ggt daily failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("❌ 获取港股通成交统计失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "ggt_daily"}

    @mcp.tool(tags={"money-flow"})
    async def get_sector_money_flow_history(
        sector_name: str = "",
        days: int = 20,
        sector_id: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取板块资金流向历史数据。

        WHEN TO USE:
        - 用户问"白酒板块近期资金流怎么样""半导体板块主力资金进出情况"
        - 需要特定板块近N日的行情走势+资金流(主力/散户)组合数据

        CONCEPT:
        查询指定行业板块近N个交易日的行情走势及主力/散户资金净流入，帮助判断板块资金动向和热度。
        板块名称模糊匹配时会返回候选列表。

        DIFFERENTIATION:
        - 这是"单板块资金流历史"；看全市场板块排名请用 get_market_money_flow
        - 看板块价格走势(不含资金流)请用 get_sector_trend
        - 看板块估值PE/PB请用 get_sector_valuation_metrics
        - 看个股资金流请用 get_money_flow

        next_recommended_tools:
        - get_sector_trend
        - get_sector_valuation_metrics
        - get_market_money_flow
        """
        if ctx:
            await ctx.info(
                "🔧 获取板块资金流向",
                extra={"sector_name": sector_name, "sector_id": sector_id, "days": days},
            )

        try:
            logger.info(
                "MCP tool called: get_sector_money_flow_history",
                sector_name=sector_name,
                sector_id=sector_id,
                days=days,
            )
            result = await money_flow_use_cases.get_sector_money_flow_history(
                sector_name=sector_name,
                days=days,
                sector_id=sector_id or None,
            )
            query_label = sector_name or sector_id or "unknown"

            # ── 候选列表：板块名称模糊匹配返回多个候选时 ──────────────────
            if result.get("candidates"):
                candidates: list = result["candidates"]
                candidates_str = "、".join(candidates)
                summary_text = (
                    f'板块名称"{query_label}"不明确，找到以下候选板块：{candidates_str}。'
                    f"请用精确名称重新查询，例如直接使用上述某个名称。"
                )
                empty_artifact = create_artifact_envelope(
                    component_type="sector_flow",
                    name=f"Sector Money Flow: {query_label}",
                    content={
                        "sector_name": query_label,
                        "index_code": "",
                        "has_money_flow": False,
                        "records": [],
                        "candidates": candidates,
                    },
                    description=summary_text,
                    metadata={"type": "sector_flow", "sector_name": query_label},
                    visible_to_llm=True,
                )
                return create_artifact_response(
                    summary=summary_text,
                    artifact=empty_artifact,
                )

            if result.get("error"):
                err_msg = result["error"]
                # 如果 error 响应中同时携带了候选列表，拼入提示
                candidates = result.get("candidates") or []
                if candidates:
                    candidates_str = "、".join(candidates)
                    summary_text = (
                        f'板块名称"{query_label}"不明确，找到以下候选板块：{candidates_str}。'
                        f"请用精确名称重新查询，例如直接使用上述某个名称。"
                    )
                else:
                    summary_text = f"未找到板块数据: {err_msg}"
                empty_artifact = create_artifact_envelope(
                    component_type="sector_flow",
                    name=f"Sector Money Flow: {query_label}",
                    content={
                        "sector_name": query_label,
                        "index_code": "",
                        "has_money_flow": False,
                        "records": [],
                        "error": err_msg,
                        "candidates": candidates,
                    },
                    description=summary_text,
                    metadata={"type": "sector_flow", "sector_name": query_label},
                    visible_to_llm=bool(candidates),
                    display_in_report=True,
                )
                return create_artifact_response(
                    summary=summary_text,
                    artifact=empty_artifact,
                )

            index_name = result.get("sector_name", query_label)
            index_code = result.get("index_code", "")
            records = result.get("records", [])
            summary_info = result.get("summary", {})
            has_flow = result.get("has_money_flow", False)
            amount_unit = (
                result.get("amount_unit")
                or summary_info.get("amount_unit")
                or "unknown"
            )

            # Build summary text
            total_pct = summary_info.get("total_pct_chg", 0)
            trend = summary_info.get("trend", "")
            total_main = summary_info.get("total_main_net")
            flow_source = summary_info.get("flow_source")

            name_with_code = f"{index_name}({index_code})" if index_code else index_name
            lines = [f"{name_with_code} 板块资金流向 (近{len(records)}日):", f"- 区间涨跌幅: {total_pct:.2f}%"]
            if has_flow and total_main is not None:
                lines.append(
                    f"- 主力累计净流入: {_fmt_amount(total_main, amount_unit)}"
                )
                lines.append(f"- 金额单位口径: {_unit_label(amount_unit)}")
                if flow_source:
                    lines.append(f"- 资金流口径: {flow_source}")
            lines.append(f"- 趋势: {trend}")
            summary_text = "\n".join(lines)

            # Build artifact
            artifact = create_artifact_envelope(
                component_type="sector_flow",
                name=f"Sector Money Flow: {index_name}",
                content={
                    "sector_name": index_name,
                    "index_code": index_code,
                    "has_money_flow": has_flow,
                    "records": records,
                    "amount_unit": amount_unit,
                },
                description=summary_text,
                metadata={
                    "type": "sector_flow",
                    "sector_name": index_name,
                    "index_code": index_code,
                    "days": len(records),
                    "amount_unit": amount_unit,
                },
                visible_to_llm=False,
                display_in_report=True,
            )

            if ctx:
                await ctx.info(
                    f"✅ 板块资金流向获取完成: {index_name}",
                    extra={"days": len(records), "trend": trend},
                )

            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(
                f"Get sector money flow history failed: {e}",
                exc_info=True,
            )
            if ctx:
                await ctx.error(
                    f"❌ 获取板块资金流向失败: {sector_name or sector_id or 'unknown'}",
                    extra={"error": str(e)},
                )
            return {
                "error": str(e),
                "component_type": "sector_flow",
            }

    @mcp.tool(tags={"money-flow"})
    async def get_sector_valuation_metrics(
        sector_name: str = "",
        days: int = 250,
        sample_size: int = 60,
        sector_id: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取板块估值指标与历史分位（PE/PB）。

        WHEN TO USE:
        - 用户问"银行板块估值高不高""白酒PE在历史什么分位""某某板块便宜还是贵"
        - 需要判断板块估值安全边际（低估/合理/高估）

        CONCEPT:
        基于板块成分股聚合计算板块层面的PE(TTM)/PB，并给出历史分位。
        分位<30%通常视为低估，>70%视为高估。

        DIFFERENTIATION:
        - 这是"板块估值PE/PB"；看板块价格走势请用 get_sector_trend
        - 看板块资金流请用 get_sector_money_flow_history
        - 看行业PE/PB历史(另一实现)请用 get_sector_pe_pb_historical

        next_recommended_tools:
        - get_sector_trend
        - get_sector_money_flow_history
        - get_sector_pe_pb_historical
        """
        if ctx:
            await ctx.info(
                "🔧 获取板块估值",
                extra={
                    "sector_name": sector_name,
                    "sector_id": sector_id,
                    "days": days,
                    "sample_size": sample_size,
                },
            )

        try:
            logger.info(
                "MCP tool called: get_sector_valuation_metrics",
                sector_name=sector_name,
                sector_id=sector_id,
                days=days,
                sample_size=sample_size,
            )
            result = await money_flow_use_cases.get_sector_valuation_metrics(
                sector_name=sector_name,
                days=days,
                sample_size=sample_size,
                sector_id=sector_id or None,
            )
            query_label = sector_name or sector_id or "unknown"

            if result.get("candidates"):
                candidates = result.get("candidates", [])
                summary_text = (
                    f'板块名称"{query_label}"不明确，候选：'
                    f"{'、'.join(candidates)}。请使用精确板块名称重试。"
                )
                artifact = create_artifact_envelope(
                    component_type="sector_valuation_metrics",
                    name=f"Sector Valuation: {query_label}",
                    content={
                        "sector_name": query_label,
                        "index_code": "",
                        "candidates": candidates,
                        "history": [],
                    },
                    description=summary_text,
                    metadata={
                        "type": "sector_valuation_metrics",
                        "sector_name": query_label,
                    },
                    visible_to_llm=True,
                    display_in_report=True,
                )
                return create_artifact_response(summary=summary_text, artifact=artifact)

            if result.get("error"):
                summary_text = f"板块估值数据不可用: {result.get('error')}"
                artifact = create_artifact_envelope(
                    component_type="sector_valuation_metrics",
                    name=f"Sector Valuation: {query_label}",
                    content={
                        "sector_name": query_label,
                        "index_code": result.get("index_code", ""),
                        "history": [],
                        "error": result.get("error"),
                    },
                    description=summary_text,
                    metadata={
                        "type": "sector_valuation_metrics",
                        "sector_name": query_label,
                    },
                    visible_to_llm=True,
                    display_in_report=True,
                )
                return create_artifact_response(summary=summary_text, artifact=artifact)

            sector = result.get("sector_name", query_label)
            index_code = result.get("index_code", "")
            current = result.get("current", {}) or {}
            summary = result.get("summary", {}) or {}
            history = result.get("history", []) or []

            pe = current.get("pe_ttm")
            pb = current.get("pb")
            pe_pct = summary.get("pe_ttm_percentile")
            pb_pct = summary.get("pb_percentile")
            level = summary.get("valuation_level", "未知")
            latest_cov = summary.get("coverage_latest")
            used = result.get("member_count_used")
            total = result.get("member_count_total")
            with_data = result.get("member_count_with_data")

            def _fmt_num(v: Any, nd: int = 2) -> str:
                if isinstance(v, (int, float)):
                    return f"{v:.{nd}f}"
                return "N/A"

            def _fmt_pct(v: Any) -> str:
                if isinstance(v, (int, float)):
                    return f"{v:.1f}%"
                return "N/A"

            summary_text = (
                f"{sector}({index_code}) 板块估值(近{len(history)}日): "
                f"PE(TTM)={_fmt_num(pe)}(分位{_fmt_pct(pe_pct)}), "
                f"PB={_fmt_num(pb)}(分位{_fmt_pct(pb_pct)}), "
                f"估值判断={level}; 覆盖={latest_cov}/{used} "
                f"(样本成分{with_data}/{total})"
            )

            artifact = create_artifact_envelope(
                component_type="sector_valuation_metrics",
                name=f"Sector Valuation: {sector}",
                content={
                    "sector_name": sector,
                    "index_code": index_code,
                    "current": current,
                    "summary": summary,
                    "history": history,
                    "member_count_total": total,
                    "member_count_used": used,
                    "member_count_with_data": with_data,
                },
                description=summary_text,
                metadata={
                    "type": "sector_valuation_metrics",
                    "sector_name": sector,
                    "index_code": index_code,
                    "days": len(history),
                },
                visible_to_llm=True,
                display_in_report=True,
            )

            if ctx:
                await ctx.info(
                    f"✅ 板块估值获取完成: {sector}",
                    extra={"valuation_level": level, "days": len(history)},
                )

            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get sector valuation metrics failed: {e}", exc_info=True)
            if ctx:
                await ctx.error(
                    f"❌ 获取板块估值失败: {sector_name or sector_id or 'unknown'}",
                    extra={"error": str(e)},
                )
            return {
                "error": str(e),
                "component_type": "sector_valuation_metrics",
            }

    @mcp.tool(tags={"money-flow"})
    async def get_market_breadth(
        days: int = 20,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取A股市场广度指标。

        WHEN TO USE:
        - 用户问"市场广度怎么样""涨跌家数""今天是普涨还是普跌""市场参与度"
        - 需要判断市场整体参与度和健康程度

        CONCEPT:
        市场广度指标包括上涨/下跌家数、涨跌比(AD Ratio)、20日新高/新低、中位数收益。
        AD Ratio>1表示多头占优；新高>新低*2表示突破动能强。

        DIFFERENTIATION:
        - 这是"全市场广度/情绪"口径；看资金流向请用 get_market_money_flow
        - 看风格轮动请用 get_style_rotation；看市场流动性请用 get_market_liquidity

        next_recommended_tools:
        - get_market_money_flow
        - get_style_rotation
        - get_market_liquidity
        """
        if ctx:
            await ctx.info("获取市场广度指标", extra={"days": days})

        try:
            logger.info("MCP tool called: get_market_breadth", days=days)
            gateway = Container.market_gateway()
            result = await gateway.get_market_breadth(days=days)

            summary = result.get("summary", {})
            up_count = summary.get("up_count", 0)
            down_count = summary.get("down_count", 0)
            ad_ratio = summary.get("advance_decline_ratio", 0)
            new_high = summary.get("new_high_20d", 0)
            new_low = summary.get("new_low_20d", 0)
            median_ret = summary.get("median_return_pct", 0)
            trade_date = summary.get("trade_date", "N/A")

            # 判断市场情绪
            if ad_ratio >= 1.5:
                sentiment = "强势多头"
            elif ad_ratio >= 1.0:
                sentiment = "偏多"
            elif ad_ratio >= 0.67:
                sentiment = "偏弱"
            else:
                sentiment = "弱势空头"

            # 判断突破动能
            if new_high > new_low * 2:
                momentum = "突破向上"
            elif new_low > new_high * 2:
                momentum = "破位下行"
            else:
                momentum = "震荡整理"

            summary_text = (
                f"市场广度({trade_date}): 上涨{up_count}/下跌{down_count}, "
                f"涨跌比{ad_ratio:.2f}({sentiment}); "
                f"20日新高{new_high}/新低{new_low}({momentum}); "
                f"中位数收益{median_ret:+.2f}%"
            )

            artifact = create_artifact_envelope(
                component_type="market_breadth",
                name="Market Breadth Indicators",
                content={
                    "summary": summary,
                    "history": result.get("history", []),
                },
                description=summary_text,
                metadata={
                    "type": "market_breadth",
                    "days": days,
                    "trade_date": trade_date,
                },
            )

            if ctx:
                await ctx.info(
                    "市场广度获取完成",
                    extra={"ad_ratio": ad_ratio, "sentiment": sentiment},
                )

            return create_artifact_response(summary=summary_text, artifact=artifact)

        except Exception as e:
            logger.error(f"Get market breadth failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("获取市场广度失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "market_breadth"}

    @mcp.tool(tags={"money-flow"})
    async def get_relative_strength(
        symbol: str,
        benchmark: str = "000300",
        days: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取个股相对强弱指标(RS)。

        WHEN TO USE:
        - 用户问"这只股票跑赢大盘了吗""相对强弱怎么样""对比沪深300表现"
        - 需要筛选强势股/弱势股，或判断个股相对指数的超额收益

        CONCEPT:
        RS = 个股收益率 - 基准收益率。RS>0跑赢基准，RS<0跑输基准。
        常用于选股和判断板块轮动方向。

        DIFFERENTIATION:
        - 这是"个股vs指数"相对收益；看绝对资金流请用 get_money_flow
        - 看筹码分布请用 get_chip_distribution；看风格轮动请用 get_style_rotation

        next_recommended_tools:
        - get_money_flow
        - get_chip_distribution
        - calculate_risk_metrics
        """
        if ctx:
            await ctx.info(
                "获取相对强弱指标",
                extra={"symbol": symbol, "benchmark": benchmark, "days": days},
            )

        try:
            logger.info(
                "MCP tool called: get_relative_strength",
                symbol=symbol,
                benchmark=benchmark,
                days=days,
            )
            gateway = Container.market_gateway()
            result = await gateway.get_relative_strength(
                symbol=symbol, benchmark=benchmark, days=days
            )

            rs_pct = result.get("rs_pct", 0)
            trend = result.get("trend", "neutral")
            latest_date = result.get("latest_date", "N/A")
            stock_ret = result.get("latest_stock_return_pct", 0)
            bench_ret = result.get("latest_benchmark_return_pct", 0)
            history = result.get("history", [])

            trend_cn = {
                "outperform": "跑赢基准",
                "underperform": "跑输基准",
                "neutral": "与基准持平",
            }.get(trend, trend)

            summary_text = (
                f"{symbol} vs {benchmark}({days}日): "
                f"RS={rs_pct:+.2f}%({trend_cn}); "
                f"个股收益{stock_ret:+.2f}%, 基准收益{bench_ret:+.2f}%; "
                f"数据截至{latest_date}"
            )

            artifact = create_artifact_envelope(
                component_type="relative_strength",
                name=f"RS: {symbol} vs {benchmark}",
                content={
                    "symbol": symbol,
                    "benchmark": benchmark,
                    "days": days,
                    "rs_pct": rs_pct,
                    "trend": trend,
                    "latest_date": latest_date,
                    "latest_stock_return_pct": stock_ret,
                    "latest_benchmark_return_pct": bench_ret,
                    "history": history,
                },
                description=summary_text,
                metadata={
                    "type": "relative_strength",
                    "symbol": symbol,
                    "benchmark": benchmark,
                    "days": days,
                },
            )

            if ctx:
                await ctx.info(
                    "相对强弱计算完成",
                    extra={"rs_pct": rs_pct, "trend": trend},
                )

            return create_artifact_response(summary=summary_text, artifact=artifact)

        except Exception as e:
            logger.error(f"Get relative strength failed: {e}", exc_info=True)
            if ctx:
                await ctx.error("获取相对强弱失败", extra={"error": str(e)})
            return {"error": str(e), "component_type": "relative_strength"}

    # ==================================================================
    # Extended data tools (COL-137/138)
    # ==================================================================

    @mcp.tool(tags={"money-flow"})
    async def get_margin_trading(
        symbol: str,
        days: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取个股融资融券数据。

        WHEN TO USE:
        - 用户问"这只股票融资余额多少""融资买入情况""杠杆资金动向"
        - 需要判断个股杠杆资金的增减趋势

        CONCEPT:
        融资融券余额反映杠杆资金对个股的态度。融资余额上升通常表示看多情绪增强。

        DIFFERENTIATION:
        - 这是"个股级"融资融券；看全市场两融趋势请用 get_market_liquidity
        - 看个股资金流请用 get_money_flow

        next_recommended_tools:
        - get_money_flow
        - get_market_liquidity
        """
        if ctx:
            await ctx.info("🔧 获取融资融券数据", extra={"symbol": symbol, "days": days})
        try:
            logger.info("MCP tool called: get_margin_trading", symbol=symbol, days=days)
            gateway = Container.market_gateway()
            resolved = await gateway.resolve_ticker(symbol)
            result = await gateway.get_margin_trading(ticker=resolved, days=days)

            data = result.get("data", [])
            summary_text = f"{symbol}融资融券({len(data)}条记录)"

            artifact = create_artifact_envelope(
                component_type="margin_trading",
                name=f"融资融券: {symbol}",
                content=result,
                description=summary_text,
                metadata={"type": "margin_trading", "symbol": symbol, "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get margin trading failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "margin_trading"}

    @mcp.tool(tags={"money-flow"})
    async def get_restricted_release(
        days: int = 90,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取限售解禁数据。

        WHEN TO USE:
        - 用户问"近期有什么解禁""限售股解禁压力""解禁日历"
        - 需要评估未来N天的解禁抛压风险

        CONCEPT:
        限售股解禁后可在二级市场卖出，大规模解禁可能带来短期卖压。
        解禁量占总股本比例越高，潜在影响越大。

        DIFFERENTIATION:
        - 这是"事件型"解禁日历；看股东持仓变化请用 get_stock_shareholder_changes
        - 看股东结构请用 get_stock_top10_shareholders

        next_recommended_tools:
        - get_stock_shareholder_changes
        - get_stock_top10_shareholders
        """
        if ctx:
            await ctx.info("🔧 获取限售解禁数据", extra={"days": days})
        try:
            logger.info("MCP tool called: get_restricted_release", days=days)
            gateway = Container.market_gateway()
            result = await gateway.get_restricted_release(days=days)

            summary_text = f"限售解禁(未来{days}天)"
            artifact = create_artifact_envelope(
                component_type="restricted_release",
                name="限售解禁",
                content=result,
                description=summary_text,
                metadata={"type": "restricted_release", "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get restricted release failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "restricted_release"}

    @mcp.tool(tags={"money-flow"})
    async def get_repurchase_info(
        symbol: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取股票回购数据。

        WHEN TO USE:
        - 用户问"有哪些股票在回购""某某公司回购情况""回购计划进度"
        - 需要发现回购信号或跟踪回购实施进度

        CONCEPT:
        回购通常被视为管理层对公司价值的认可。大规模回购计划可减少流通股、提升EPS。

        DIFFERENTIATION:
        - 这是"回购事件"口径；看股东增减持统计请用 get_stock_shareholder_changes
        - 看股东结构请用 get_stock_top10_shareholders

        next_recommended_tools:
        - get_stock_shareholder_changes
        - get_stock_top10_shareholders
        """
        if ctx:
            await ctx.info("🔧 获取回购数据", extra={"symbol": symbol})
        try:
            logger.info("MCP tool called: get_repurchase_info", symbol=symbol)
            gateway = Container.market_gateway()
            result = await gateway.get_repurchase_info(symbol=symbol)

            summary_text = f"股票回购{' - ' + symbol if symbol else '全市场'}"
            artifact = create_artifact_envelope(
                component_type="repurchase",
                name=f"回购: {symbol or '全市场'}",
                content=result,
                description=summary_text,
                metadata={"type": "repurchase", "symbol": symbol},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get repurchase info failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "repurchase"}

    @mcp.tool(tags={"money-flow"})
    async def get_index_constituents(
        index_code: str = "000300",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取指数成分股列表。

        WHEN TO USE:
        - 用户问"沪深300有哪些股票""指数成分股""某某指数包含什么"
        - 需要查看指数的成分股明细

        CONCEPT:
        指数成分股是构成该指数的具体股票列表，通常按权重排序。

        DIFFERENTIATION:
        - 这是"成分股列表"；看成分股权重分布请用 get_index_constituent_weights
        - 看ETF资金流请用 get_etf_flow

        next_recommended_tools:
        - get_index_constituent_weights
        - get_etf_flow
        """
        if ctx:
            await ctx.info("🔧 获取指数成分股", extra={"index_code": index_code})
        try:
            logger.info("MCP tool called: get_index_constituents", index_code=index_code)
            gateway = Container.market_gateway()
            result = await gateway.get_index_constituents(index_code=index_code)

            data = result.get("data", [])
            summary_text = f"指数{index_code}成分股({len(data)}只)"

            artifact = create_artifact_envelope(
                component_type="index_constituents",
                name=f"成分股: {index_code}",
                content=result,
                description=summary_text,
                metadata={"type": "index_constituents", "index_code": index_code},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get index constituents failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "index_constituents"}

    @mcp.tool(tags={"money-flow"})
    async def get_index_constituent_weights(
        index_code: str = "000300",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取指数成分股权重。

        WHEN TO USE:
        - 用户问"沪深300权重分布""指数里什么股票占比最大""集中度如何"
        - 需要分析指数的行业和个股集中度

        CONCEPT:
        成分股权重反映每只股票对指数涨跌的影响力。高集中度意味着少数个股主导指数表现。

        DIFFERENTIATION:
        - 这是"权重分布"；看成分股列表请用 get_index_constituents
        - 看ETF资金流请用 get_etf_flow

        next_recommended_tools:
        - get_index_constituents
        - get_etf_flow
        """
        if ctx:
            await ctx.info("🔧 获取成分股权重", extra={"index_code": index_code})
        try:
            logger.info("MCP tool called: get_index_constituent_weights", index_code=index_code)
            gateway = Container.market_gateway()
            result = await gateway.get_index_constituent_weights(index_code=index_code)

            data = result.get("data", [])
            summary_text = f"指数{index_code}权重({len(data)}只)"

            artifact = create_artifact_envelope(
                component_type="index_weights",
                name=f"权重: {index_code}",
                content=result,
                description=summary_text,
                metadata={"type": "index_weights", "index_code": index_code},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get index weights failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "index_weights"}

    @mcp.tool(tags={"money-flow"})
    async def get_fund_nav(
        fund_code: str = "",
        days: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取基金净值数据。

        WHEN TO USE:
        - 用户问"某某ETF净值多少""基金净值走势""场内基金行情"
        - 需要查询ETF/LOF的净值和历史走势

        CONCEPT:
        基金净值(NAV)是每份基金的净资产价值。场内基金交易价格可能偏离净值产生折溢价。

        DIFFERENTIATION:
        - 这是"基金净值"；看ETF资金流向请用 get_etf_flow
        - 看基金重仓股请用 get_fund_holdings

        next_recommended_tools:
        - get_etf_flow
        - get_fund_holdings
        """
        if ctx:
            await ctx.info("🔧 获取基金净值", extra={"fund_code": fund_code, "days": days})
        try:
            logger.info("MCP tool called: get_fund_nav", fund_code=fund_code, days=days)
            gateway = Container.market_gateway()
            result = await gateway.get_fund_nav(fund_code=fund_code, days=days)

            data = result.get("data", [])
            summary_text = f"基金净值({len(data)}条记录)"

            artifact = create_artifact_envelope(
                component_type="fund_nav",
                name=f"基金净值: {fund_code or '全市场'}",
                content=result,
                description=summary_text,
                metadata={"type": "fund_nav", "fund_code": fund_code, "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get fund nav failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "fund_nav"}

    @mcp.tool(tags={"money-flow"})
    async def get_bond_yield(ctx: Context = None) -> Dict[str, Any]:
        """获取国债收益率曲线数据。

        WHEN TO USE:
        - 用户问"国债收益率曲线""期限利差""利率曲线形态"
        - 需要判断利率水平、期限结构及宏观流动性环境

        CONCEPT:
        国债收益率曲线展示不同期限的到期收益率。正常向上倾斜；倒挂可能预示经济衰退风险。

        DIFFERENTIATION:
        - 这是"国债收益率曲线"；看政策利率(SHIBOR/LPR)请用 get_interest_rates
        - 看货币供给请用 get_money_supply

        next_recommended_tools:
        - get_interest_rates
        - get_money_supply
        """
        if ctx:
            await ctx.info("🔧 获取国债收益率曲线")
        try:
            logger.info("MCP tool called: get_bond_yield")
            gateway = Container.market_gateway()
            result = await gateway.get_bond_yield()

            summary_text = "国债收益率曲线"
            artifact = create_artifact_envelope(
                component_type="bond_yield",
                name="国债收益率",
                content=result,
                description=summary_text,
                metadata={"type": "bond_yield"},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get bond yield failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "bond_yield"}

    @mcp.tool(tags={"money-flow"})
    async def get_futures_main(
        symbol: str = "IF0",
        days: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取期货主力合约行情数据。

        WHEN TO USE:
        - 用户问"股指期货行情""IF主力合约走势""期货主力连续数据"
        - 需要查看期货(股指/商品)主力合约的日级行情

        CONCEPT:
        主力合约是当前持仓量最大的合约月份，连续主力可展示长期价格走势。

        DIFFERENTIATION:
        - 这是"期货行情"；看期货基差(期现价差)请用 get_futures_basis
        - 看商品库存请用 get_commodity_inventory

        next_recommended_tools:
        - get_futures_basis
        - get_commodity_inventory
        """
        if ctx:
            await ctx.info("🔧 获取期货主力合约", extra={"symbol": symbol, "days": days})
        try:
            logger.info("MCP tool called: get_futures_main", symbol=symbol, days=days)
            gateway = Container.market_gateway()
            result = await gateway.get_futures_main(symbol=symbol, days=days)

            data = result.get("data", [])
            summary_text = f"期货{symbol}({len(data)}条)"

            artifact = create_artifact_envelope(
                component_type="futures_main",
                name=f"期货: {symbol}",
                content=result,
                description=summary_text,
                metadata={"type": "futures_main", "symbol": symbol, "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get futures main failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "futures_main"}

    @mcp.tool(tags={"money-flow"})
    async def get_option_summary(ctx: Context = None) -> Dict[str, Any]:
        """获取期权市场概览。

        WHEN TO USE:
        - 用户问"期权市场情况""ETF期权成交持仓""期权PCR"
        - 需要快速了解ETF期权市场的整体成交和持仓状况

        CONCEPT:
        期权市场概览包含总成交量、持仓量、PCR(看跌/看涨比率)等关键指标。
        PCR上升可能反映避险情绪增强。

        DIFFERENTIATION:
        - 这是"期权概览"；看股指期货请用 get_futures_main
        - 看期货基差请用 get_futures_basis

        next_recommended_tools:
        - get_futures_main
        - get_futures_basis
        """
        if ctx:
            await ctx.info("🔧 获取期权市场概览")
        try:
            logger.info("MCP tool called: get_option_summary")
            gateway = Container.market_gateway()
            result = await gateway.get_option_summary()

            summary_text = "期权市场概览"
            artifact = create_artifact_envelope(
                component_type="option_summary",
                name="期权概览",
                content=result,
                description=summary_text,
                metadata={"type": "option_summary"},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get option summary failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "option_summary"}

    # ==================================================================
    # Quantitative analysis tools (COL-127/129/130/131/135)
    # ==================================================================

    @mcp.tool(tags={"money-flow"})
    async def get_sector_pe_pb_historical(
        sector_name: str = "银行",
        days: int = 250,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取行业PE/PB历史分位数据。

        WHEN TO USE:
        - 用户问"银行PE历史分位""某某行业估值在什么水平"
        - 需要判断行业当前估值在历史中的相对位置

        CONCEPT:
        计算行业PE/PB在指定历史区间内的分位数。分位越低越"便宜"，越高越"贵"。

        DIFFERENTIATION:
        - 这是"行业估值历史分位"的另一个实现；更精细的板块估值(含成分股覆盖)请用 get_sector_valuation_metrics
        - 看板块走势请用 get_sector_trend；看板块资金流请用 get_sector_money_flow_history

        next_recommended_tools:
        - get_sector_valuation_metrics
        - get_sector_trend
        - get_sector_money_flow_history
        """
        if ctx:
            await ctx.info("🔧 获取行业估值分位", extra={"sector_name": sector_name, "days": days})
        try:
            logger.info("MCP tool called: get_sector_pe_pb_historical", sector_name=sector_name, days=days)
            gateway = Container.market_gateway()
            result = await gateway.get_sector_pe_pb_historical(
                sector_name=sector_name, days=days
            )

            current = result.get("current", {})
            pe = current.get("pe", "N/A")
            pe_pct = current.get("pe_percentile", "N/A")
            level = current.get("valuation_level", "N/A")

            summary_text = (
                f"{sector_name}估值分位: PE={pe}, 分位={pe_pct}%, 水平={level}"
            )

            artifact = create_artifact_envelope(
                component_type="sector_valuation",
                name=f"行业估值: {sector_name}",
                content=result,
                description=summary_text,
                metadata={"type": "sector_valuation", "sector_name": sector_name, "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get sector PE/PB failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "sector_valuation"}

    @mcp.tool(tags={"money-flow"})
    async def get_etf_flow(
        symbol: str = "510300",
        days: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取ETF资金流向数据。

        WHEN TO USE:
        - 用户问"沪深300ETF资金流向""ETF申赎情况""ETF净流入"
        - 需要跟踪特定ETF的资金进出和份额变化

        CONCEPT:
        ETF资金流向反映资金通过ETF工具进出特定市场/板块的情况。持续净流入表示资金看好。

        DIFFERENTIATION:
        - 这是"ETF级"资金流；看基金净值请用 get_fund_nav
        - 看基金重仓股请用 get_fund_holdings；看板块资金请用 get_sector_money_flow_history

        next_recommended_tools:
        - get_fund_nav
        - get_fund_holdings
        - get_sector_money_flow_history
        """
        if ctx:
            await ctx.info("🔧 获取ETF资金流向", extra={"symbol": symbol, "days": days})
        try:
            logger.info("MCP tool called: get_etf_flow", symbol=symbol, days=days)
            gateway = Container.market_gateway()
            result = await gateway.get_etf_flow(symbol=symbol, days=days)

            summary_text = f"ETF {symbol}资金流向"
            artifact = create_artifact_envelope(
                component_type="etf_flow",
                name=f"ETF资金: {symbol}",
                content=result,
                description=summary_text,
                metadata={"type": "etf_flow", "symbol": symbol, "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get ETF flow failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "etf_flow"}

    @mcp.tool(tags={"money-flow"})
    async def get_style_rotation(ctx: Context = None) -> Dict[str, Any]:
        """获取风格轮动指标。

        WHEN TO USE:
        - 用户问"大盘还是小盘强""成长还是价值占优""风格切换了吗"
        - 需要判断当前市场风格偏好

        CONCEPT:
        比较大盘股(上证50) vs 小盘股(中证1000)和成长股(创业板指) vs 价值股(沪深300)的近期涨跌幅。
        风格轮动信号帮助投资者在大小盘/成长价值维度上做配置决策。

        DIFFERENTIATION:
        - 这是"市场风格"口径；看市场广度/情绪请用 get_market_breadth
        - 看个股相对强弱请用 get_relative_strength

        next_recommended_tools:
        - get_market_breadth
        - get_relative_strength
        """
        if ctx:
            await ctx.info("🔧 获取风格轮动指标")
        try:
            logger.info("MCP tool called: get_style_rotation")
            gateway = Container.market_gateway()
            result = await gateway.get_style_rotation()

            signal = result.get("style_signal", {})
            ls = signal.get("large_vs_small", "N/A")
            gv = signal.get("growth_vs_value", "N/A")
            summary_text = f"风格轮动: {ls}, {gv}"

            artifact = create_artifact_envelope(
                component_type="style_rotation",
                name="风格轮动",
                content=result,
                description=summary_text,
                metadata={"type": "style_rotation"},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get style rotation failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "style_rotation"}

    @mcp.tool(tags={"money-flow"})
    async def get_futures_basis(
        index_code: str = "IF0",
        days: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取期货基差数据。

        WHEN TO USE:
        - 用户问"股指期货升水还是贴水""基差多少""期现价差"
        - 需要判断期货市场对后市的情绪预期

        CONCEPT:
        基差 = 期货价格 - 现货价格。正基差(升水)暗示看多，负基差(贴水)暗示看空。
        基差率可用于跨品种/跨时间比较。

        DIFFERENTIATION:
        - 这是"期现价差"；看期货行情请用 get_futures_main
        - 看期权概览请用 get_option_summary

        next_recommended_tools:
        - get_futures_main
        - get_option_summary
        """
        if ctx:
            await ctx.info("🔧 获取期货基差", extra={"index_code": index_code, "days": days})
        try:
            logger.info("MCP tool called: get_futures_basis", index_code=index_code, days=days)
            gateway = Container.market_gateway()
            result = await gateway.get_futures_basis(index_code=index_code, days=days)

            basis = result.get("latest_basis")
            basis_pct = result.get("latest_basis_pct")
            summary_text = (
                f"期货基差{index_code}: "
                f"基差={f'{basis:.2f}' if isinstance(basis, (int, float)) else 'N/A'}, "
                f"基差率={f'{basis_pct:+.2f}%' if isinstance(basis_pct, (int, float)) else 'N/A'}"
            )

            artifact = create_artifact_envelope(
                component_type="futures_basis",
                name=f"基差: {index_code}",
                content=result,
                description=summary_text,
                metadata={"type": "futures_basis", "index_code": index_code, "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get futures basis failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "futures_basis"}

    @mcp.tool(tags={"money-flow"})
    async def calculate_risk_metrics(
        symbol: str,
        days: int = 120,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """计算量化风险指标。

        WHEN TO USE:
        - 用户问"这只股票波动率多少""最大回撤""Beta值""Sharpe比率"
        - 需要量化评估个股的风险收益特征

        CONCEPT:
        基于历史行情计算Beta(系统性风险)、Sharpe Ratio(风险调整收益)、
        Max Drawdown(最大回撤)、VaR/CVaR(尾部风险)、Volatility(年化波动率)等。

        DIFFERENTIATION:
        - 这是"风险量化"；看相对强弱请用 get_relative_strength
        - 看筹码分布(成本结构)请用 get_chip_distribution

        next_recommended_tools:
        - get_relative_strength
        - get_chip_distribution
        """
        if ctx:
            await ctx.info("🔧 计算风险指标", extra={"symbol": symbol, "days": days})
        try:
            logger.info("MCP tool called: calculate_risk_metrics", symbol=symbol, days=days)
            gateway = Container.market_gateway()
            result = await gateway.calculate_risk_metrics(symbol=symbol, days=days)

            metrics = result.get("risk_metrics", {})
            vol = metrics.get("volatility_annual", "N/A")
            mdd = metrics.get("max_drawdown_pct", "N/A")
            sharpe = metrics.get("sharpe_ratio", "N/A")
            beta = metrics.get("beta", "N/A")

            summary_text = (
                f"{symbol}风险指标: "
                f"波动率={vol}%, 最大回撤={mdd}%, "
                f"Sharpe={sharpe}, Beta={beta}"
            )

            artifact = create_artifact_envelope(
                component_type="risk_metrics",
                name=f"风险指标: {symbol}",
                content=result,
                description=summary_text,
                metadata={"type": "risk_metrics", "symbol": symbol, "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Calculate risk metrics failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "risk_metrics"}

    # ==================================================================
    # Additional data domain tools (COL-140)
    # ==================================================================

    @mcp.tool(tags={"money-flow"})
    async def get_dragon_tiger_list(
        start_date: str = "",
        end_date: str = "",
        days: int = 10,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取龙虎榜每日明细。

        WHEN TO USE:
        - 用户问"龙虎榜有什么""游资在买什么""哪些股票上榜了"
        - 需要跟踪游资/机构大额买卖动向和市场热点

        CONCEPT:
        龙虎榜是交易所公开披露的大额买卖信息，包括买入/卖出营业部、买卖金额、上榜原因。
        可跟踪游资席位和机构席位的交易行为。

        DIFFERENTIATION:
        - 这是"龙虎榜"(交易所公开披露)；看大宗交易请用 get_block_trade
        - 看个股资金流(常规统计)请用 get_money_flow

        next_recommended_tools:
        - get_block_trade
        - get_money_flow
        """
        if ctx:
            await ctx.info("🔧 获取龙虎榜数据", extra={"days": days})
        try:
            logger.info("MCP tool called: get_dragon_tiger_list", days=days)
            result = await money_flow_use_cases.get_dragon_tiger_list(
                start_date=start_date, end_date=end_date, days=days,
            )
            data = result.get("data", [])
            summary_text = f"龙虎榜({len(data)}条记录)"

            artifact = create_artifact_envelope(
                component_type="dragon_tiger",
                name="龙虎榜",
                content=result,
                description=summary_text,
                metadata={"type": "dragon_tiger", "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get dragon tiger list failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "dragon_tiger"}

    @mcp.tool(tags={"money-flow"})
    async def get_block_trade(
        start_date: str = "",
        end_date: str = "",
        days: int = 10,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取大宗交易每日明细。

        WHEN TO USE:
        - 用户问"大宗交易情况""大股东减持""折价大宗"
        - 需要发现机构/大股东的大额交易行为和折溢价信号

        CONCEPT:
        大宗交易是单笔金额较大的场外协商交易。折价率高通常暗示减持意图；溢价交易可能表示看好。

        DIFFERENTIATION:
        - 这是"大宗交易"(场外协商)；看龙虎榜(交易所披露)请用 get_dragon_tiger_list
        - 看股东增减持统计请用 get_stock_shareholder_changes

        next_recommended_tools:
        - get_dragon_tiger_list
        - get_stock_shareholder_changes
        """
        if ctx:
            await ctx.info("🔧 获取大宗交易数据", extra={"days": days})
        try:
            logger.info("MCP tool called: get_block_trade", days=days)
            result = await money_flow_use_cases.get_block_trade(
                start_date=start_date, end_date=end_date, days=days,
            )
            data = result.get("data", [])
            summary_text = f"大宗交易({len(data)}条记录)"

            artifact = create_artifact_envelope(
                component_type="block_trade",
                name="大宗交易",
                content=result,
                description=summary_text,
                metadata={"type": "block_trade", "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get block trade failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "block_trade"}

    @mcp.tool(tags={"money-flow"})
    async def get_convertible_bond(
        bond_code: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取可转债实时行情。

        WHEN TO USE:
        - 用户问"可转债行情""转股溢价率""某某转债怎么样"
        - 需要分析可转债的转股价值、纯债价值、溢价率等

        CONCEPT:
        可转债兼具债底保护和股性弹性。转股溢价率越低，股性越强；纯债溢价率越低，债底保护越好。

        DIFFERENTIATION:
        - 这是"可转债"口径；看正股资金流请用 get_money_flow
        - 看期货请用 get_futures_main

        next_recommended_tools:
        - get_money_flow
        - get_futures_main
        """
        if ctx:
            await ctx.info("🔧 获取可转债行情", extra={"bond_code": bond_code})
        try:
            logger.info("MCP tool called: get_convertible_bond", bond_code=bond_code)
            result = await money_flow_use_cases.get_convertible_bond(bond_code=bond_code)

            data = result.get("data", [])
            summary_text = f"可转债行情({len(data)}只)"

            artifact = create_artifact_envelope(
                component_type="convertible_bond",
                name=f"可转债: {bond_code or '全市场'}",
                content=result,
                description=summary_text,
                metadata={"type": "convertible_bond", "bond_code": bond_code},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get convertible bond failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "convertible_bond"}

    @mcp.tool(tags={"money-flow"})
    async def get_fund_holdings(
        fund_code: str = "",
        quarter: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取基金重仓股数据。

        WHEN TO USE:
        - 用户问"基金经理买了什么""基金重仓股""机构持仓"
        - 需要跟踪明星基金经理的持仓变化或发现机构集中持股

        CONCEPT:
        公募基金每季度披露前十大重仓股。持仓变化反映基金经理对后市的判断和行业偏好。

        DIFFERENTIATION:
        - 这是"基金持仓"口径；看基金净值请用 get_fund_nav
        - 看ETF资金流请用 get_etf_flow；看十大流通股东请用 get_stock_top10_shareholders

        next_recommended_tools:
        - get_fund_nav
        - get_etf_flow
        - get_stock_top10_shareholders
        """
        if ctx:
            await ctx.info("🔧 获取基金持仓", extra={"fund_code": fund_code, "quarter": quarter})
        try:
            logger.info("MCP tool called: get_fund_holdings", fund_code=fund_code, quarter=quarter)
            result = await money_flow_use_cases.get_fund_holdings(
                fund_code=fund_code, quarter=quarter,
            )
            data = result.get("data", [])
            summary_text = f"基金持仓{' - ' + fund_code if fund_code else ''}({len(data)}条)"

            artifact = create_artifact_envelope(
                component_type="fund_holdings",
                name=f"基金持仓: {fund_code or '全部'}",
                content=result,
                description=summary_text,
                metadata={"type": "fund_holdings", "fund_code": fund_code, "quarter": quarter},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get fund holdings failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "fund_holdings"}

    @mcp.tool(tags={"money-flow"})
    async def get_commodity_inventory(
        symbol: str = "螺纹钢",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取商品期货库存/仓单数据。

        WHEN TO USE:
        - 用户问"螺纹钢库存""铜的库存变化""商品供需"
        - 需要判断商品的基本面供需格局

        CONCEPT:
        库存数据是商品基本面分析的核心指标。库存上升暗示供过于求，下降暗示供不应求。
        支持品种: 螺纹钢、铁矿石、铜、铝、锌、镍、锡、黄金、白银、原油等。

        DIFFERENTIATION:
        - 这是"商品基本面(库存)"口径；看期货行情请用 get_futures_main
        - 看期货基差请用 get_futures_basis

        next_recommended_tools:
        - get_futures_main
        - get_futures_basis
        """
        if ctx:
            await ctx.info("🔧 获取商品库存", extra={"symbol": symbol})
        try:
            logger.info("MCP tool called: get_commodity_inventory", symbol=symbol)
            result = await money_flow_use_cases.get_commodity_inventory(symbol=symbol)

            data = result.get("data", [])
            summary_text = f"{symbol}库存({len(data)}条记录)"

            artifact = create_artifact_envelope(
                component_type="commodity_inventory",
                name=f"库存: {symbol}",
                content=result,
                description=summary_text,
                metadata={"type": "commodity_inventory", "symbol": symbol},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get commodity inventory failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "commodity_inventory"}

    # ------------------------------------------------------------------
    # 股票参与者数据 (COL-144)
    # ------------------------------------------------------------------

    @mcp.tool(tags={"money-flow"})
    async def get_stock_northbound_holdings(
        symbol: str,
        days: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取个股北向持股明细。

        WHEN TO USE:
        - 用户问"外资持有这只股票多少""北向持股变化""外资在加仓还是减仓"
        - 需要判断外资对特定个股的态度和持仓趋势

        CONCEPT:
        北向持股明细展示个股被沪深港通外资持有的数量、市值、占流通股比例的历史变化。
        持股比例上升=外资加仓，下降=外资减仓。

        DIFFERENTIATION:
        - 这是"个股级"北向持仓；看全市场北向总流量请用 get_north_bound_flow
        - 看北向持股排名请用 get_stock_northbound_ranking
        - 看个股资金流请用 get_money_flow

        next_recommended_tools:
        - get_north_bound_flow
        - get_stock_northbound_ranking
        - get_money_flow
        """
        if ctx:
            await ctx.info("🔧 获取个股北向持股明细", extra={"symbol": symbol, "days": days})
        try:
            logger.info("MCP tool called: get_stock_northbound_holdings", symbol=symbol, days=days)
            result = await money_flow_use_cases.get_stock_northbound_holdings(symbol=symbol, days=days)

            snapshot = result.get("snapshot", {})
            history_count = result.get("total_history", 0)
            has_snap = bool(snapshot)
            summary_text = f"北向持股{symbol}: 快照{'有' if has_snap else '无'}数据, 历史{history_count}条"

            artifact = create_artifact_envelope(
                component_type="stock_northbound_holdings",
                name=f"北向持股: {symbol}",
                content=result,
                description=summary_text,
                metadata={"type": "stock_northbound_holdings", "symbol": symbol, "days": days},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get stock northbound holdings failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "stock_northbound_holdings"}

    @mcp.tool(tags={"money-flow"})
    async def get_stock_northbound_ranking(
        market: str = "北向",
        indicator: str = "今日排行",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取北向持股排行榜。

        WHEN TO USE:
        - 用户问"外资重仓股""北向资金买了哪些股""外资流入Top10"
        - 需要发现外资整体偏好的个股排名

        CONCEPT:
        北向持股排行榜按不同时间维度(今日/5日/10日/1月)展示外资持股变化排名。
        可快速定位外资加仓/减仓最集中的个股。

        DIFFERENTIATION:
        - 这是"排名"视角；看个股北向持仓历史请用 get_stock_northbound_holdings
        - 看全市场北向总流量请用 get_north_bound_flow

        next_recommended_tools:
        - get_stock_northbound_holdings
        - get_north_bound_flow
        """
        if ctx:
            await ctx.info("🔧 获取北向持股排行", extra={"market": market, "indicator": indicator})
        try:
            logger.info("MCP tool called: get_stock_northbound_ranking", market=market, indicator=indicator)
            result = await money_flow_use_cases.get_stock_northbound_ranking(market=market, indicator=indicator)

            data = result.get("data", [])
            summary_text = f"北向排行({indicator}): {len(data)}只股票"

            artifact = create_artifact_envelope(
                component_type="stock_northbound_ranking",
                name=f"北向排行: {indicator}",
                content=result,
                description=summary_text,
                metadata={"type": "stock_northbound_ranking", "market": market, "indicator": indicator},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get stock northbound ranking failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "stock_northbound_ranking"}

    @mcp.tool(tags={"money-flow"})
    async def get_stock_top10_shareholders(
        symbol: str,
        date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取十大流通股东。

        WHEN TO USE:
        - 用户问"这只股票谁在持有""十大股东""筹码集中度"
        - 需要判断个股的机构/外资持仓和筹码集中度变化

        CONCEPT:
        十大流通股东按持股比例排名，可观察机构、外资、自然人等不同类型股东的进出。
        筹码集中度提升通常有利于股价稳定。

        DIFFERENTIATION:
        - 这是"个股级股东结构"；看全市场股东增减持统计请用 get_stock_shareholder_changes
        - 看个股北向持仓请用 get_stock_northbound_holdings
        - 看基金重仓股请用 get_fund_holdings

        next_recommended_tools:
        - get_stock_shareholder_changes
        - get_stock_northbound_holdings
        - get_fund_holdings
        """
        if ctx:
            await ctx.info("🔧 获取十大流通股东", extra={"symbol": symbol, "date": date})
        try:
            logger.info("MCP tool called: get_stock_top10_shareholders", symbol=symbol, date=date)
            result = await money_flow_use_cases.get_stock_top10_shareholders(symbol=symbol, date=date)

            data = result.get("data", [])
            summary_text = f"十大流通股东{symbol}: {len(data)}条记录"

            artifact = create_artifact_envelope(
                component_type="stock_top10_shareholders",
                name=f"十大股东: {symbol}",
                content=result,
                description=summary_text,
                metadata={"type": "stock_top10_shareholders", "symbol": symbol},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get stock top10 shareholders failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "stock_top10_shareholders"}

    @mcp.tool(tags={"money-flow"})
    async def get_stock_shareholder_changes(
        date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取股东持股变化统计。

        WHEN TO USE:
        - 用户问"重要股东在增持还是减持""产业资本动向""高管增减持"
        - 需要判断全市场重要股东的增减持趋势

        CONCEPT:
        重要股东(大股东、董监高)的增减持行为反映内部人对公司价值的判断。
        产业资本集中增持常出现在市场底部区域。

        DIFFERENTIATION:
        - 这是"全市场股东行为统计"；看个股十大股东请用 get_stock_top10_shareholders
        - 看限售解禁请用 get_restricted_release；看回购请用 get_repurchase_info

        next_recommended_tools:
        - get_stock_top10_shareholders
        - get_restricted_release
        - get_repurchase_info
        """
        if ctx:
            await ctx.info("🔧 获取股东持股变化", extra={"date": date})
        try:
            logger.info("MCP tool called: get_stock_shareholder_changes", date=date)
            result = await money_flow_use_cases.get_stock_shareholder_changes(date=date)

            data = result.get("data", [])
            summary_text = f"股东持股变化: {len(data)}条记录"

            artifact = create_artifact_envelope(
                component_type="stock_shareholder_changes",
                name="股东持股变化",
                content=result,
                description=summary_text,
                metadata={"type": "stock_shareholder_changes", "date": date},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get stock shareholder changes failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "stock_shareholder_changes"}

    @mcp.tool(tags={"money-flow"})
    async def get_stock_institutional_research(
        date: str = "",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取机构调研统计。

        WHEN TO USE:
        - 用户问"哪些股票被机构密集调研""机构调研热度排名""这只股票有没有机构调研"
        - 需要发现机构关注度高的个股

        CONCEPT:
        机构调研指基金公司、券商、资管等实地走访上市公司并出报告。
        调研密度高 = 机构关注度强，常出现在基本面拐点前。

        DIFFERENTIATION:
        - 看的是"调研行为统计"，不是真实持仓变动
        - 持仓变动看 get_stock_top10_shareholders 或 get_fund_holdings
        - 北向动向看 get_stock_northbound_holdings

        next_recommended_tools:
        - get_stock_top10_shareholders
        - get_fund_holdings
        """
        if ctx:
            await ctx.info("🔧 获取机构调研统计", extra={"date": date})
        try:
            logger.info("MCP tool called: get_stock_institutional_research", date=date)
            result = await money_flow_use_cases.get_stock_institutional_research(date=date)

            data = result.get("data", [])
            summary_text = f"机构调研统计: {len(data)}条记录"

            artifact = create_artifact_envelope(
                component_type="stock_institutional_research",
                name="机构调研统计",
                content=result,
                description=summary_text,
                metadata={"type": "stock_institutional_research", "date": date},
            )
            return create_artifact_response(summary=summary_text, artifact=artifact)
        except Exception as e:
            logger.error(f"Get stock institutional research failed: {e}", exc_info=True)
            return {"error": str(e), "component_type": "stock_institutional_research"}
