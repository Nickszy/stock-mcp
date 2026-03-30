# src/server/mcp/tools/financial_analytics_tools.py
"""MCP tools for AI-native financial analytics.

Derived analytics on top of canonical/gateway data: growth rates,
financial health scoring, and peer comparison.

Tools:
  - get_financial_growth_analysis: YoY/QoQ增长率分析
  - get_financial_health_score: 财务健康评分
"""

import time
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP, Context

from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_standard_artifact_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    """Convert value to float, return None if not possible."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _calc_growth(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """Calculate YoY/QoQ growth rate."""
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def _format_pct(val: Optional[float]) -> str:
    """Format a float as percentage string."""
    if val is None:
        return "N/A"
    return f"{val:+.1%}" if val >= 0 else f"{val:.1%}"


def _format_amount(val: Optional[float]) -> str:
    """Format large amounts in 亿/万."""
    if val is None:
        return "N/A"
    if abs(val) >= 1e8:
        return f"{val / 1e8:.2f}亿"
    if abs(val) >= 1e4:
        return f"{val / 1e4:.2f}万"
    return f"{val:.2f}"


async def _fetch_financial_data(symbol: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Fetch financial data, trying canonical first then gateway."""
    exchange, ticker = symbol.split(":") if ":" in symbol else ("", symbol)

    # Try canonical
    try:
        from src.server.domain.structured_data.canonical_reader import (
            read_canonical_financial_statements,
        )
        data = await read_canonical_financial_statements(
            dataset_key="financial_statements",
            symbol=ticker,
            exchange=exchange,
            limit=limit,
        )
        if data:
            return data
    except Exception as e:
        logger.debug("Canonical fetch failed, trying gateway", symbol=symbol, error=str(e))

    # Fallback to gateway
    try:
        from src.server.core.dependencies import Container
        gateway = Container.market_gateway()
        result = await gateway.get_financial_reports(symbol=symbol)
        if result and isinstance(result, dict):
            records = result.get("data", result)
            if isinstance(records, list):
                return [
                    {"report_period": r.get("report_date", ""), "data": r, "source_type": "live"}
                    for r in records[:limit]
                ]
            elif isinstance(records, dict):
                return [
                    {"report_period": records.get("report_date", ""), "data": records, "source_type": "live"}
                ]
    except Exception as e:
        logger.debug("Gateway fetch also failed", symbol=symbol, error=str(e))

    return []


def _score_to_rating(score: float) -> str:
    """Convert 0-100 score to rating."""
    if score >= 80:
        return "优秀"
    if score >= 60:
        return "良好"
    if score >= 40:
        return "一般"
    if score >= 20:
        return "较弱"
    return "风险"


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

def register_financial_analytics_tools(mcp: FastMCP):
    """Register financial analytics MCP tools."""

    # ------------------------------------------------------------------
    # get_financial_growth_analysis
    # ------------------------------------------------------------------
    @mcp.tool(tags={"analytics", "fundamental"})
    async def get_financial_growth_analysis(
        symbol: str,
        limit: int = 8,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """财务增长率分析: YoY同比/QoQ环比增长率计算.

        WHEN TO USE: 当AI需要分析公司的增长趋势时使用, 自动计算营收/净利润/EPS等
        关键指标的同比和环比增长率.
        典型触发: "茅台的增长率怎么样" "分析600519的增长趋势" "营收和利润增长情况".
        CONCEPT: 基于canonical优先的财报数据, 计算以下增长率指标:
        营收YoY/QoQ、净利润YoY/QoQ、EPS YoY/QoQ、总资产YoY.
        返回多期趋势数据和增长加速/减速信号.
        DIFFERENTIATION: 与get_financial_reports不同——后者返回原始数据;
        本工具直接计算衍生指标(增长率), 让AI无需手动计算即可理解增长趋势.
        next_recommended_tools: get_financial_health_score, get_canonical_financials, get_financial_ratios
        """
        if ctx:
            await ctx.info(f"分析增长率: {symbol}")

        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_financial_growth_analysis", symbol=symbol)

            data = await _fetch_financial_data(symbol, limit=limit + 2)
            elapsed = time.perf_counter() - t0

            if not data:
                return create_standard_artifact_response(
                    summary=f"无财报数据: {symbol}",
                    component_type=ComponentType.TABLE,
                    name="增长率分析",
                    data={"symbol": symbol, "error": "No data available"},
                    source="analytics",
                    description="无法获取财报数据",
                )

            source_type = data[0].get("source_type", "unknown")

            # Sort by report_period ascending for growth calculation
            sorted_data = sorted(data, key=lambda x: x.get("report_period", ""))

            # Calculate growth rates
            periods: List[Dict[str, Any]] = []
            for i, rec in enumerate(sorted_data):
                d = rec.get("data", {})
                period = rec.get("report_period", "")

                entry: Dict[str, Any] = {
                    "period": period,
                    "revenue": _safe_float(d.get("revenue")),
                    "net_income": _safe_float(d.get("net_income")),
                    "eps": _safe_float(d.get("eps")),
                    "total_assets": _safe_float(d.get("total_assets")),
                }

                # YoY: compare with same quarter last year (4 periods back)
                if i >= 4:
                    prev = sorted_data[i - 4].get("data", {})
                    entry["revenue_yoy"] = _calc_growth(
                        entry["revenue"], _safe_float(prev.get("revenue"))
                    )
                    entry["net_income_yoy"] = _calc_growth(
                        entry["net_income"], _safe_float(prev.get("net_income"))
                    )
                    entry["eps_yoy"] = _calc_growth(
                        entry["eps"], _safe_float(prev.get("eps"))
                    )
                    entry["total_assets_yoy"] = _calc_growth(
                        entry["total_assets"], _safe_float(prev.get("total_assets"))
                    )

                # QoQ: compare with previous quarter
                if i >= 1:
                    prev = sorted_data[i - 1].get("data", {})
                    entry["revenue_qoq"] = _calc_growth(
                        entry["revenue"], _safe_float(prev.get("revenue"))
                    )
                    entry["net_income_qoq"] = _calc_growth(
                        entry["net_income"], _safe_float(prev.get("net_income"))
                    )

                periods.append(entry)

            # Build markdown
            md = f"# 增长率分析: {symbol}\n\n"
            md += f"**数据来源**: {source_type} | **报告期数**: {len(periods)} | **耗时**: {elapsed:.1f}s\n\n"

            md += "| 报告期 | 营收 | 营收YoY | 净利润 | 净利润YoY | EPS | EPS YoY |\n"
            md += "|--------|------|---------|--------|-----------|-----|---------|\n"
            for p in periods[-6:]:  # Show last 6 periods
                rev = _format_amount(p.get("revenue"))
                ni = _format_amount(p.get("net_income"))
                eps = f"{p['eps']:.2f}" if p.get("eps") else "N/A"
                rev_yoy = _format_pct(p.get("revenue_yoy"))
                ni_yoy = _format_pct(p.get("net_income_yoy"))
                eps_yoy = _format_pct(p.get("eps_yoy"))
                md += f"| {p['period']} | {rev} | {rev_yoy} | {ni} | {ni_yoy} | {eps} | {eps_yoy} |\n"

            # Growth trend summary
            latest = periods[-1] if periods else {}
            md += "\n## 最新增长摘要\n\n"
            if latest.get("revenue_yoy") is not None:
                md += f"- **营收YoY**: {_format_pct(latest['revenue_yoy'])}\n"
            if latest.get("net_income_yoy") is not None:
                md += f"- **净利润YoY**: {_format_pct(latest['net_income_yoy'])}\n"
            if latest.get("eps_yoy") is not None:
                md += f"- **EPS YoY**: {_format_pct(latest['eps_yoy'])}\n"

            summary = (
                f"增长率分析: {symbol} | "
                f"营收YoY:{_format_pct(latest.get('revenue_yoy'))} "
                f"净利润YoY:{_format_pct(latest.get('net_income_yoy'))} "
                f"({source_type}, 耗时 {elapsed:.1f}s)"
            )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FINANCIAL_CHART,
                name=f"增长率分析: {symbol}",
                data={
                    "symbol": symbol,
                    "periods": periods,
                    "source_type": source_type,
                    "period_count": len(periods),
                },
                source=source_type,
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_financial_growth_analysis failed: {e}")
            return create_standard_artifact_response(
                summary=f"增长率分析失败: {e}",
                component_type=ComponentType.TABLE,
                name="分析错误",
                data={"error": str(e), "symbol": symbol},
                source="analytics",
                description=f"分析失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_financial_health_score
    # ------------------------------------------------------------------
    @mcp.tool(tags={"analytics", "fundamental"})
    async def get_financial_health_score(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """财务健康评分: 基于多维度财务指标的综合健康度评分.

        WHEN TO USE: 当AI需要快速评估一家公司的财务健康状况时使用.
        典型触发: "茅台的财务健康吗" "600519的财务评分" "这家公司财务安不安全".
        CONCEPT: 基于最新财报数据计算5个维度的健康评分(各0-20分, 总分100):
        1. 盈利能力(ROE/净利率) 2. 偿债能力(资产负债率/流动比率)
        3. 成长性(营收增长/净利润增长) 4. 现金流质量(经营现金流/净利润)
        5. 资产效率(总资产周转率)
        返回总分+维度分+评级+关键指标明细.
        DIFFERENTIATION: 与get_financial_ratios不同——后者只返回原始比率;
        本工具直接给出综合评分和风险提示, 让AI快速判断财务健康度.
        next_recommended_tools: get_financial_growth_analysis, get_canonical_financials
        """
        if ctx:
            await ctx.info(f"财务健康评分: {symbol}")

        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_financial_health_score", symbol=symbol)

            data = await _fetch_financial_data(symbol, limit=6)
            elapsed = time.perf_counter() - t0

            if not data:
                return create_standard_artifact_response(
                    summary=f"无财报数据: {symbol}",
                    component_type=ComponentType.TABLE,
                    name="财务健康评分",
                    data={"symbol": symbol, "error": "No data available"},
                    source="analytics",
                    description="无法获取财报数据",
                )

            source_type = data[0].get("source_type", "unknown")

            # Use latest data for scoring
            latest = data[0].get("data", {})
            # Use second-latest for growth calculation
            prev = data[1].get("data", {}) if len(data) > 1 else {}

            # Extract key metrics
            revenue = _safe_float(latest.get("revenue"))
            net_income = _safe_float(latest.get("net_income"))
            total_assets = _safe_float(latest.get("total_assets"))
            total_liabilities = _safe_float(latest.get("total_liabilities"))
            operating_cf = _safe_float(latest.get("operating_cash_flow"))
            current_assets = _safe_float(latest.get("current_assets"))
            current_liabilities = _safe_float(latest.get("current_liabilities"))
            equity = (total_assets or 0) - (total_liabilities or 0) if total_assets else None

            prev_revenue = _safe_float(prev.get("revenue"))
            prev_net_income = _safe_float(prev.get("net_income"))

            # --- Dimension 1: Profitability (0-20) ---
            profitability_score = 0
            profitability_detail = {}

            # ROE
            if net_income and equity and equity > 0:
                roe = net_income / equity
                profitability_detail["roe"] = roe
                if roe > 0.15:
                    profitability_score += 10
                elif roe > 0.10:
                    profitability_score += 7
                elif roe > 0.05:
                    profitability_score += 4

            # Net margin
            if net_income and revenue and revenue > 0:
                net_margin = net_income / revenue
                profitability_detail["net_margin"] = net_margin
                if net_margin > 0.20:
                    profitability_score += 10
                elif net_margin > 0.10:
                    profitability_score += 7
                elif net_margin > 0.05:
                    profitability_score += 4

            # --- Dimension 2: Solvency (0-20) ---
            solvency_score = 0
            solvency_detail = {}

            # Debt ratio (lower is better for non-financial)
            if total_assets and total_liabilities:
                debt_ratio = total_liabilities / total_assets
                solvency_detail["debt_ratio"] = debt_ratio
                if debt_ratio < 0.40:
                    solvency_score += 10
                elif debt_ratio < 0.60:
                    solvency_score += 7
                elif debt_ratio < 0.80:
                    solvency_score += 4

            # Current ratio
            if current_assets and current_liabilities and current_liabilities > 0:
                current_ratio = current_assets / current_liabilities
                solvency_detail["current_ratio"] = current_ratio
                if current_ratio > 2.0:
                    solvency_score += 10
                elif current_ratio > 1.5:
                    solvency_score += 7
                elif current_ratio > 1.0:
                    solvency_score += 4

            # --- Dimension 3: Growth (0-20) ---
            growth_score = 0
            growth_detail = {}

            rev_growth = _calc_growth(revenue, prev_revenue)
            ni_growth = _calc_growth(net_income, prev_net_income)

            if rev_growth is not None:
                growth_detail["revenue_growth"] = rev_growth
                if rev_growth > 0.20:
                    growth_score += 10
                elif rev_growth > 0.10:
                    growth_score += 7
                elif rev_growth > 0:
                    growth_score += 4

            if ni_growth is not None:
                growth_detail["net_income_growth"] = ni_growth
                if ni_growth > 0.20:
                    growth_score += 10
                elif ni_growth > 0.10:
                    growth_score += 7
                elif ni_growth > 0:
                    growth_score += 4

            # --- Dimension 4: Cash Flow Quality (0-20) ---
            cashflow_score = 0
            cashflow_detail = {}

            if operating_cf and net_income and net_income > 0:
                cf_ratio = operating_cf / net_income
                cashflow_detail["ocf_to_ni"] = cf_ratio
                if cf_ratio > 1.2:
                    cashflow_score = 20
                elif cf_ratio > 0.8:
                    cashflow_score = 15
                elif cf_ratio > 0.5:
                    cashflow_score = 10
                elif cf_ratio > 0:
                    cashflow_score = 5

            # --- Dimension 5: Asset Efficiency (0-20) ---
            efficiency_score = 0
            efficiency_detail = {}

            if revenue and total_assets and total_assets > 0:
                asset_turnover = revenue / total_assets
                efficiency_detail["asset_turnover"] = asset_turnover
                if asset_turnover > 1.0:
                    efficiency_score = 20
                elif asset_turnover > 0.6:
                    efficiency_score = 15
                elif asset_turnover > 0.3:
                    efficiency_score = 10
                elif asset_turnover > 0:
                    efficiency_score = 5

            # --- Total Score ---
            total_score = (
                profitability_score
                + solvency_score
                + growth_score
                + cashflow_score
                + efficiency_score
            )
            rating = _score_to_rating(total_score)

            # Data sufficiency check
            available_fields = sum(1 for v in [
                revenue, net_income, total_assets, total_liabilities,
                operating_cf, current_assets, current_liabilities,
            ] if v is not None)
            data_sufficiency = available_fields / 7

            # Build markdown
            md = f"# 财务健康评分: {symbol}\n\n"
            md += f"**综合评分**: **{total_score}/100** ({rating})\n"
            md += f"**数据来源**: {source_type} | **数据完整度**: {data_sufficiency:.0%} | **耗时**: {elapsed:.1f}s\n\n"
            if data_sufficiency < 0.5:
                md += "> **注意**: 数据完整度低于50%, 评分可能不具参考性\n\n"

            md += "| 维度 | 得分 | 满分 | 关键指标 |\n"
            md += "|------|------|------|----------|\n"

            dims = [
                ("盈利能力", profitability_score, profitability_detail),
                ("偿债能力", solvency_score, solvency_detail),
                ("成长性", growth_score, growth_detail),
                ("现金流质量", cashflow_score, cashflow_detail),
                ("资产效率", efficiency_score, efficiency_detail),
            ]

            for dim_name, score, detail in dims:
                indicators = []
                for k, v in detail.items():
                    if isinstance(v, float):
                        indicators.append(f"{k}={v:.2%}" if abs(v) < 10 else f"{k}={v:.2f}")
                    else:
                        indicators.append(f"{k}={v}")
                md += f"| {dim_name} | {score} | 20 | {', '.join(indicators[:2]) or 'N/A'} |\n"

            # Risk flags
            risks = []
            if solvency_detail.get("debt_ratio", 0) > 0.70:
                risks.append("资产负债率偏高")
            if growth_detail.get("revenue_growth") is not None and growth_detail["revenue_growth"] < -0.10:
                risks.append("营收负增长超10%")
            if cashflow_detail.get("ocf_to_ni", 0) < 0.5 and cashflow_detail:
                risks.append("经营现金流/净利润偏低")
            if profitability_detail.get("roe", 0) < 0.05 and profitability_detail:
                risks.append("ROE偏低(<5%)")

            if risks:
                md += "\n## 风险提示\n\n"
                for r in risks:
                    md += f"- {r}\n"

            summary = f"财务健康: {symbol} | {total_score}/100 ({rating}) ({source_type}, {elapsed:.1f}s)"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FINANCIAL_CHART,
                name=f"财务健康: {symbol} ({rating})",
                data={
                    "symbol": symbol,
                    "total_score": total_score,
                    "rating": rating,
                    "dimensions": {
                        "profitability": {"score": profitability_score, **profitability_detail},
                        "solvency": {"score": solvency_score, **solvency_detail},
                        "growth": {"score": growth_score, **growth_detail},
                        "cashflow": {"score": cashflow_score, **cashflow_detail},
                        "efficiency": {"score": efficiency_score, **efficiency_detail},
                    },
                    "risks": risks,
                    "source_type": source_type,
                },
                source=source_type,
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_financial_health_score failed: {e}")
            return create_standard_artifact_response(
                summary=f"财务健康评分失败: {e}",
                component_type=ComponentType.TABLE,
                name="评分错误",
                data={"error": str(e), "symbol": symbol},
                source="analytics",
                description=f"评分失败: {e}",
            )
