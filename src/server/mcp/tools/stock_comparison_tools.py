# src/server/mcp/tools/stock_comparison_tools.py
"""MCP tools for multi-stock comparison and benchmarking.

Provides AI agents with side-by-side stock comparison across multiple
dimensions: valuation, growth, profitability, financial health, and
technical momentum.

Tools:
  - compare_stocks: 多股对比分析(2-5只股票)
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
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _fmt(val, unit: str = "") -> str:
    """Format a value for display."""
    if val is None:
        return "N/A"
    if abs(val) >= 1e8:
        return f"{val / 1e8:.1f}亿{unit}"
    if abs(val) >= 1e4:
        return f"{val / 1e4:.1f}万{unit}"
    if isinstance(val, float):
        return f"{val:.2f}{unit}"
    return f"{val}{unit}"


def _fmt_pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:.1%}"


async def _fetch_stock_metrics(symbol: str) -> Dict[str, Any]:
    """Fetch key metrics for a single stock via gateway + canonical."""
    metrics: Dict[str, Any] = {"symbol": symbol}

    # Fetch fact pack (aggregated data)
    try:
        from src.server.core.dependencies import Container
        gateway = Container.market_gateway()
        fact_pack = await gateway.get_stock_fact_pack(symbol=symbol)
        if fact_pack:
            facts = fact_pack.get("facts", {})
            entity = fact_pack.get("entity", {})

            # Entity info
            metrics["name"] = entity.get("name", facts.get("security_master", {}).get("name", symbol))

            # Valuation
            valuation = facts.get("market", {}).get("valuation", {})
            if isinstance(valuation, dict):
                metrics["pe_ttm"] = _safe_float(valuation.get("pe_ttm"))
                metrics["pb"] = _safe_float(valuation.get("pb"))
                metrics["market_cap"] = _safe_float(valuation.get("total_market_value"))

            # Financial
            financial = facts.get("financial", {})
            if isinstance(financial, dict):
                data = financial.get("data", financial)
                if isinstance(data, list) and data:
                    latest = data[0] if data else {}
                elif isinstance(data, dict):
                    latest = data
                else:
                    latest = {}
                metrics["revenue"] = _safe_float(latest.get("revenue"))
                metrics["net_income"] = _safe_float(latest.get("net_income"))
                metrics["eps"] = _safe_float(latest.get("eps"))
                metrics["roe"] = _safe_float(latest.get("roe"))
                metrics["gross_margin"] = _safe_float(latest.get("gross_profit_margin"))
                metrics["net_margin"] = _safe_float(latest.get("net_profit_margin"))
                metrics["revenue_yoy"] = _safe_float(latest.get("revenue_yoy_growth"))
                metrics["net_income_yoy"] = _safe_float(latest.get("net_profit_yoy_growth"))

            # Dividend
            dividend = facts.get("events", {}).get("dividends", {})
            if isinstance(dividend, dict):
                metrics["dividend_yield"] = _safe_float(dividend.get("yield"))

    except Exception as e:
        logger.warning("Fact pack fetch failed in comparison", symbol=symbol, error=str(e))

    # Fetch financial ratios
    try:
        from src.server.core.dependencies import Container
        gateway = Container.market_gateway()
        ratios = await gateway.get_financial_ratios(symbol=symbol)
        if ratios and isinstance(ratios, dict):
            data = ratios.get("data", ratios)
            if isinstance(data, list) and data:
                latest = data[0]
            elif isinstance(data, dict):
                latest = data
            else:
                latest = {}
            # Don't overwrite if already present
            if metrics.get("roe") is None:
                metrics["roe"] = _safe_float(latest.get("roe"))
            if metrics.get("gross_margin") is None:
                metrics["gross_margin"] = _safe_float(latest.get("gross_profit_margin"))
            if metrics.get("net_margin") is None:
                metrics["net_margin"] = _safe_float(latest.get("net_profit_margin"))
            metrics["debt_ratio"] = _safe_float(latest.get("debt_to_assets"))
            metrics["current_ratio"] = _safe_float(latest.get("current_ratio"))
    except Exception:
        pass

    return metrics


def _pick_winner(
    stocks: List[Dict[str, Any]],
    key: str,
    higher_is_better: bool = True,
) -> Optional[str]:
    """Pick the best stock for a given metric."""
    valid = [(s["symbol"], s.get(key)) for s in stocks if s.get(key) is not None]
    if not valid:
        return None
    if higher_is_better:
        return max(valid, key=lambda x: x[1])[0]
    return min(valid, key=lambda x: x[1])[0]


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

def register_stock_comparison_tools(mcp: FastMCP):
    """Register stock comparison MCP tools."""

    # ------------------------------------------------------------------
    # compare_stocks
    # ------------------------------------------------------------------
    @mcp.tool(tags={"comparison", "analytics", "fundamental"})
    async def compare_stocks(
        symbols: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """多股对比分析: 2-5只股票的估值/成长/盈利/财务健康横向对比.

        WHEN TO USE: 当AI需要比较2-5只股票的全方位指标时使用.
        典型触发: "比较茅台和五粮液" "600519 vs 000858" "这几只白酒股哪个好"
        "帮我对比一下这几家公司" "A和B哪个更值得投资".
        CONCEPT: 聚合多只股票的关键指标进行横向对比, 包括:
        估值(PE/PB/市值)、成长(营收增速/净利润增速)、盈利(ROE/净利率/毛利率)、
        财务健康(资产负债率/流动比率)、分红(股息率).
        自动标注每个维度的最优标的, 并给出综合推荐排序.
        DIFFERENTIATION: 与build_peer_benchmark_table不同——后者要求同行业且需预设symbols;
        本工具支持任意2-5只股票跨行业对比, 包含更丰富的财务指标和自动胜出标注.
        next_recommended_tools: get_financial_health_score, get_financial_growth_analysis, resolve_entity
        """
        if ctx:
            await ctx.info(f"多股对比: {symbols}")

        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: compare_stocks", symbols=symbols)

            # Parse symbols (comma-separated)
            symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
            if len(symbol_list) < 2:
                return create_standard_artifact_response(
                    summary="至少需要2只股票进行对比",
                    component_type=ComponentType.TABLE,
                    name="多股对比",
                    data={"error": "至少需要2只股票", "symbols": symbols},
                    source="comparison",
                    description="请提供2-5只股票代码, 用逗号分隔",
                )
            if len(symbol_list) > 5:
                symbol_list = symbol_list[:5]

            # Fetch metrics for each stock in parallel
            import asyncio
            tasks = [_fetch_stock_metrics(s) for s in symbol_list]
            stocks = await asyncio.gather(*tasks, return_exceptions=True)

            # Filter out failures
            valid_stocks = []
            for i, result in enumerate(stocks):
                if isinstance(result, Exception):
                    valid_stocks.append({"symbol": symbol_list[i], "name": symbol_list[i], "error": str(result)})
                else:
                    valid_stocks.append(result)

            elapsed = time.perf_counter() - t0

            # Build comparison table
            comparison_metrics = [
                ("市值", "market_cap", True, "亿"),
                ("PE(TTM)", "pe_ttm", False, ""),
                ("PB", "pb", False, ""),
                ("营收", "revenue", True, ""),
                ("净利润", "net_income", True, ""),
                ("EPS", "eps", True, ""),
                ("ROE", "roe", True, ""),
                ("毛利率", "gross_margin", True, ""),
                ("净利率", "net_margin", True, ""),
                ("营收增速(YoY)", "revenue_yoy", True, ""),
                ("净利润增速(YoY)", "net_income_yoy", True, ""),
                ("资产负债率", "debt_ratio", False, ""),
                ("流动比率", "current_ratio", True, ""),
                ("股息率", "dividend_yield", True, ""),
            ]

            # Pick winners for each metric
            winners = {}
            for label, key, higher_better, _ in comparison_metrics:
                winner = _pick_winner(valid_stocks, key, higher_better)
                if winner:
                    winners[key] = winner

            # Count wins per stock
            win_counts: Dict[str, int] = {s["symbol"]: 0 for s in valid_stocks}
            for winner_symbol in winners.values():
                win_counts[winner_symbol] = win_counts.get(winner_symbol, 0) + 1

            # Rank stocks by win count
            ranked = sorted(valid_stocks, key=lambda s: win_counts.get(s["symbol"], 0), reverse=True)

            # Build markdown
            stock_names = [s.get("name", s["symbol"]) for s in valid_stocks]
            md = f"# 多股对比: {' vs '.join(stock_names)}\n\n"
            md += f"**对比股票数**: {len(valid_stocks)} | **耗时**: {elapsed:.1f}s\n\n"

            # Comparison table
            headers = ["指标"] + stock_names
            md += "| " + " | ".join(headers) + " |\n"
            md += "|" + "|".join(["---"] * len(headers)) + "|\n"

            for label, key, higher_better, unit in comparison_metrics:
                row_vals = []
                winner = winners.get(key)
                for s in valid_stocks:
                    val = s.get(key)
                    if val is None:
                        row_vals.append("N/A")
                    elif unit == "亿" and isinstance(val, (int, float)):
                        row_vals.append(f"{val / 1e8:.1f}亿" if val >= 1e8 else _fmt(val))
                    elif key in ("revenue_yoy", "net_income_yoy") and isinstance(val, (int, float)):
                        row_vals.append(_fmt_pct(val))
                    elif key in ("roe", "gross_margin", "net_margin", "debt_ratio", "dividend_yield") and isinstance(val, (int, float)):
                        row_vals.append(f"{val:.1%}" if abs(val) < 10 else f"{val:.2f}")
                    else:
                        row_vals.append(_fmt(val, unit))

                    # Highlight winner
                    if s["symbol"] == winner and val is not None:
                        row_vals[-1] = f"**{row_vals[-1]}**"

                md += f"| {label} | " + " | ".join(row_vals) + " |\n"

            # Winner summary
            md += "\n## 各维度最优\n\n"
            for label, key, higher_better, _ in comparison_metrics:
                winner = winners.get(key)
                if winner:
                    winner_name = next(
                        (s.get("name", s["symbol"]) for s in valid_stocks if s["symbol"] == winner),
                        winner,
                    )
                    md += f"- **{label}**: {winner_name}\n"

            # Overall ranking
            md += "\n## 综合排序(按胜出维度数)\n\n"
            for rank, s in enumerate(ranked, 1):
                name = s.get("name", s["symbol"])
                wins = win_counts.get(s["symbol"], 0)
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
                md += f"{medal} **{name}** — {wins}个维度领先\n"

            # Data structure
            comparison_data = {
                "symbols": symbol_list,
                "stocks": valid_stocks,
                "comparison_metrics": [
                    {"label": label, "key": key, "winner": winners.get(key)}
                    for label, key, _, _ in comparison_metrics
                ],
                "win_counts": win_counts,
                "ranked": [{"symbol": s["symbol"], "name": s.get("name", ""), "wins": win_counts.get(s["symbol"], 0)} for s in ranked],
            }

            top_name = ranked[0].get("name", ranked[0]["symbol"]) if ranked else "N/A"
            top_wins = win_counts.get(ranked[0]["symbol"], 0) if ranked else 0

            summary = (
                f"多股对比: {' vs '.join(stock_names)} | "
                f"综合领先: {top_name}({top_wins}维度) "
                f"(耗时 {elapsed:.1f}s)"
            )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"多股对比: {' vs '.join(stock_names[:3])}",
                data=comparison_data,
                source="comparison",
                description=summary,
                markdown=md,
                symbol=",".join(symbol_list),
            )

        except Exception as e:
            logger.error(f"compare_stocks failed: {e}")
            return create_standard_artifact_response(
                summary=f"多股对比失败: {e}",
                component_type=ComponentType.TABLE,
                name="对比错误",
                data={"error": str(e), "symbols": symbols},
                source="comparison",
                description=f"对比失败: {e}",
            )
