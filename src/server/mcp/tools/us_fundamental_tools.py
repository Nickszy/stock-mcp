# src/server/mcp/tools/us_fundamental_tools.py
"""MCP tools for US stock fundamental data.
Supports output_format: markdown (default, human-readable) or json (structured).

Active Tools (4):
  - get_earnings_history:        EPS历史 (实际 vs 预期 + surprise%)
  - get_cash_flow_quality:       现金流质量 (OCF / FCF / FCF-净利润比)
  - get_us_valuation_metrics:    美股估值 (PE/PS/PB/EV_EBITDA)
  - get_us_institutional_holdings: 机构持仓 (前15大机构 + 变动)
"""

from typing import Any, Dict
import time

from fastmcp import FastMCP, Context

from src.server.core.use_cases import fundamental as fundamental_use_cases
from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_artifact_envelope,
    create_artifact_response,
    create_table_artifact,
    create_symbol_error_response,
)
from src.server.mcp.tools.output_format_utils import (
    _format_table_markdown,
    OutputFormat,
)
from src.server.domain.symbols.errors import SymbolResolutionError


def _is_rate_limited_error(err: Exception) -> bool:
    """Detect upstream rate-limit errors (HTTP 429 / Too Many Requests)."""
    msg = str(err).lower()
    signals = ("429", "too many requests", "rate limit", "rate limited")
    return any(s in msg for s in signals)


def register_us_fundamental_tools(mcp: FastMCP):
    """Register US fundamental analysis tools."""

    # ------------------------------------------------------------------
    # get_earnings_history
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-fundamental", "earnings"})
    async def get_earnings_history(
        symbol: str,
        quarters: int = 8,
        output_format: OutputFormat = "markdown",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Get EPS earnings history for a US stock.

        Shows actual EPS vs analyst estimate and surprise % for the last N quarters.
        Useful for evaluating earnings quality and beat/miss trends.

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:AAPL, NYSE:TSLA, NASDAQ:NVDA
            quarters: Number of past quarters to return (default 8)
            output_format: Output format - "markdown" (default, human-readable)
                or "json" (structured data for programs)
            ctx: FastMCP Context

        Returns:
            If output_format="markdown": Returns markdown tables with Chinese labels
            If output_format="json": Returns artifact with earnings table
        """
        if ctx:
            await ctx.info(f"📊 获取EPS历史: {symbol} ({quarters}季度)")
        try:
            t0 = time.perf_counter()
            logger.info(
                "MCP tool: get_earnings_history", symbol=symbol, quarters=quarters
            )
            if ":" not in symbol:
                logger.warning(
                    "get_earnings_history received unqualified symbol, resolver may probe exchanges and become slower",
                    symbol=symbol,
                )
            data = await fundamental_use_cases.get_earnings_history(
                symbol, quarters=quarters
            )
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "MCP tool: get_earnings_history finished",
                symbol=symbol,
                quarters=quarters,
                elapsed_ms=elapsed_ms,
                rows=len(data.get("quarters", [])) if isinstance(data, dict) else 0,
            )
            rows = data.get("quarters", [])

            # Build summary for LLM
            beats = sum(
                1 for r in rows if r.get("surprise_pct") and r["surprise_pct"] > 0
            )
            misses = sum(
                1 for r in rows if r.get("surprise_pct") and r["surprise_pct"] < 0
            )
            avg_surprise = sum(
                r["surprise_pct"] for r in rows if r.get("surprise_pct") is not None
            ) / max(len([r for r in rows if r.get("surprise_pct") is not None]), 1)
            summary = (
                f"{symbol} 近{len(rows)}季度EPS: 超预期{beats}次, 低预期{misses}次, "
                f"平均surprise {avg_surprise:+.1f}%"
            )

            # For JSON format, return original artifact structure
            if output_format == "json":
                artifact = create_table_artifact(
                    title=f"{symbol} EPS历史 (近{quarters}季度)",
                    columns=[
                        {"key": "date", "label": "财报日期"},
                        {"key": "actual_eps", "label": "实际EPS"},
                        {"key": "estimated_eps", "label": "预期EPS"},
                        {"key": "surprise_pct", "label": "Surprise%"},
                    ],
                    rows=rows,
                    tag="earnings_history",
                    description=summary,
                )
                artifact["component_type"] = ComponentType.EARNINGS_TABLE.value
                return create_artifact_response(summary=summary, artifact=artifact)

            # For markdown format, render as readable text
            md_output = f"## {symbol} EPS历史 (近{quarters}季度)\n\n"
            md_output += f"**摘要**: {summary}\n\n"
            md_output += _format_table_markdown(
                rows,
                "EPS明细",
                column_order=["date", "actual_eps", "estimated_eps", "surprise_pct"],
            )

            artifact = create_artifact_envelope(
                component_type="earnings_table_markdown",
                name=f"EPS历史: {symbol}",
                content={"markdown": md_output, "format": "markdown"},
                description=summary,
                metadata={"output_format": "markdown", "symbol": symbol},
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.EARNINGS_TABLE, f"{symbol} EPS历史"
            )
        except Exception as e:
            logger.error("get_earnings_history error", symbol=symbol, error=str(e))
            is_rate_limited = _is_rate_limited_error(e)
            if is_rate_limited:
                summary = (
                    f"获取 {symbol} EPS历史失败: 数据源限流(429/Too Many Requests)。"
                    f"建议 30-120 秒后重试，或降低并发请求。原始错误: {e}"
                )
                content = {
                    "error": str(e),
                    "rate_limited": True,
                    "error_code": "RATE_LIMITED",
                    "retry_after_seconds": 60,
                }
            else:
                summary = f"获取 {symbol} EPS历史失败: {e}"
                content = {"error": str(e)}
            artifact = create_artifact_envelope(
                component_type=ComponentType.EARNINGS_TABLE,
                name=f"{symbol} EPS历史",
                content=content,
                description=summary,
                metadata={"rate_limited": is_rate_limited},
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_cash_flow_quality
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-fundamental", "cashflow"})
    async def get_cash_flow_quality(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Analyze cash flow quality for a US stock.

        Returns operating cash flow, capex, free cash flow, and FCF/net-income
        ratio by year. High FCF ratio (>0.8) indicates strong earnings quality.

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:AAPL, NYSE:MSFT, NYSE:BRK-B
            ctx: FastMCP Context

        Returns:
            ArtifactResponse with cash flow table and LLM summary
        """
        if ctx:
            await ctx.info(f"💵 分析现金流质量: {symbol}")
        try:
            logger.info("MCP tool: get_cash_flow_quality", symbol=symbol)
            data = await fundamental_use_cases.get_cash_flow_quality(symbol)
            annual = data.get("annual", [])

            latest = annual[-1] if annual else {}
            fcf = latest.get("free_cf")
            fcf_ratio = latest.get("fcf_ratio")
            quality = (
                "优秀"
                if fcf_ratio and fcf_ratio > 0.8
                else "良好" if fcf_ratio and fcf_ratio > 0.5 else "一般"
            )

            summary = (
                f"{symbol} 最近年度: FCF={_fmt_billions(fcf)}, "
                f"FCF/净利润={f'{fcf_ratio:.0%}' if fcf_ratio else 'N/A'} ({quality})"
            )

            artifact = create_table_artifact(
                title=f"{symbol} 现金流质量",
                columns=[
                    {"key": "year", "label": "年度"},
                    {"key": "operating_cf", "label": "经营现金流"},
                    {"key": "capex", "label": "资本支出"},
                    {"key": "free_cf", "label": "自由现金流"},
                    {"key": "net_income", "label": "净利润"},
                    {"key": "fcf_ratio", "label": "FCF/净利润"},
                ],
                rows=annual,
                tag="cash_flow_quality",
                description=summary,
            )
            artifact["component_type"] = ComponentType.CASH_FLOW_CHART.value
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.CASH_FLOW_CHART, f"{symbol} 现金流"
            )
        except Exception as e:
            logger.error("get_cash_flow_quality error", symbol=symbol, error=str(e))
            summary = f"获取 {symbol} 现金流质量失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.CASH_FLOW_CHART,
                name=f"{symbol} 现金流",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_us_valuation_metrics
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-fundamental", "valuation"})
    async def get_us_valuation_metrics(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Get US stock valuation metrics.

        Returns PE (TTM & Forward), PS, PB, EV/EBITDA, PEG ratio,
        market cap, enterprise value, beta, and dividend yield.

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:AAPL, NASDAQ:AMZN, NYSE:JPM
            ctx: FastMCP Context

        Returns:
            ArtifactResponse with valuation snapshot and LLM summary
        """
        if ctx:
            await ctx.info(f"📈 获取估值指标: {symbol}")
        try:
            logger.info("MCP tool: get_us_valuation_metrics", symbol=symbol)
            data = await fundamental_use_cases.get_us_valuation_metrics(symbol)

            pe = data.get("pe_ttm")
            pb = data.get("pb")
            ev_ebitda = data.get("ev_ebitda")
            mcap = data.get("market_cap")
            name = data.get("name", symbol)

            summary = (
                f"{name} ({symbol}): PE(TTM)={f'{pe:.1f}x' if pe else 'N/A'}, "
                f"PB={f'{pb:.2f}x' if pb else 'N/A'}, "
                f"EV/EBITDA={f'{ev_ebitda:.1f}x' if ev_ebitda else 'N/A'}, "
                f"市值={_fmt_billions(mcap)}"
            )

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_VALUATION,
                name=f"{symbol} 估值指标",
                content=data,
                description=summary,
                metadata={"ticker": symbol, "sector": data.get("sector", "")},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_VALUATION, f"{symbol} 估值"
            )
        except Exception as e:
            logger.error("get_us_valuation_metrics error", symbol=symbol, error=str(e))
            summary = f"获取 {symbol} 估值指标失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_VALUATION,
                name=f"{symbol} 估值",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_us_institutional_holdings
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-fundamental", "institutional"})
    async def get_us_institutional_holdings(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Get institutional holdings for a US stock.

        Returns top 15 institutional holders with shares held, percentage,
        and recent change direction. Useful for tracking smart money flows.

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:AAPL, NYSE:TSLA, NASDAQ:META
            ctx: FastMCP Context

        Returns:
            ArtifactResponse with institutional holdings table and LLM summary
        """
        if ctx:
            await ctx.info(f"🏦 获取机构持仓: {symbol}")
        try:
            logger.info("MCP tool: get_us_institutional_holdings", symbol=symbol)
            data = await fundamental_use_cases.get_us_institutional_holdings(symbol)
            holders = data.get("holders", [])

            top3 = [h["name"] for h in holders[:3] if h.get("name")]
            top3_str = ", ".join(top3) if top3 else "无数据"
            inflows = sum(
                1 for h in holders if h.get("change_pct") and h["change_pct"] > 0
            )
            outflows = sum(
                1 for h in holders if h.get("change_pct") and h["change_pct"] < 0
            )
            summary = (
                f"{symbol} 机构持仓: 共{len(holders)}家, "
                f"增仓{inflows}家/减仓{outflows}家, "
                f"前三: {top3_str}"
            )

            artifact = create_table_artifact(
                title=f"{symbol} 机构持仓 (前15)",
                columns=[
                    {"key": "name", "label": "机构名称"},
                    {"key": "pct_held", "label": "持仓比例%"},
                    {"key": "shares", "label": "持股数"},
                    {"key": "change_pct", "label": "变动%"},
                    {"key": "filing_date", "label": "申报日期"},
                ],
                rows=holders,
                tag="institutional_holdings",
                description=summary,
            )
            artifact["component_type"] = ComponentType.INSTITUTIONAL_HOLDINGS.value
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.INSTITUTIONAL_HOLDINGS, f"{symbol} 机构持仓"
            )
        except Exception as e:
            logger.error(
                "get_us_institutional_holdings error", symbol=symbol, error=str(e)
            )
            summary = f"获取 {symbol} 机构持仓失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.INSTITUTIONAL_HOLDINGS,
                name=f"{symbol} 机构持仓",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_us_company_profile
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-fundamental", "profile"})
    async def get_us_company_profile(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Get comprehensive company profile for a US stock.

        Returns company overview including sector, industry, description,
        employees, CEO, market cap, key financial metrics, and price ranges.
        Essential for understanding what the company does before deeper analysis.

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:AAPL, NYSE:TSLA, NASDAQ:NVDA
            ctx: FastMCP Context

        Returns:
            ArtifactResponse with company profile and LLM summary
        """
        if ctx:
            await ctx.info(f"🏢 获取公司概况: {symbol}")
        try:
            logger.info("MCP tool: get_us_company_profile", symbol=symbol)
            data = await fundamental_use_cases.get_us_company_profile(symbol)

            name = data.get("name", symbol)
            sector = data.get("sector", "")
            industry = data.get("industry", "")
            mcap = data.get("market_cap")
            employees = data.get("employees")
            ceo = data.get("ceo", "")

            summary = (
                f"{name} ({symbol}): {sector}/{industry}"
                f"{f', CEO={ceo}' if ceo else ''}"
                f"{f', 员工={int(employees):,}' if employees else ''}"
                f"{f', 市值={_fmt_billions(mcap)}' if mcap else ''}"
            ).rstrip()

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_COMPANY_PROFILE.value,
                name=f"{symbol} 公司概况",
                content=data,
                description=summary,
                metadata={"ticker": symbol},
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_COMPANY_PROFILE, f"{symbol} 公司概况"
            )
        except Exception as e:
            logger.error("get_us_company_profile error", symbol=symbol, error=str(e))
            summary = f"获取 {symbol} 公司概况失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_COMPANY_PROFILE.value,
                name=f"{symbol} 公司概况",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_us_analyst_recommendations
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-fundamental", "analyst"})
    async def get_us_analyst_recommendations(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Get analyst recommendations and upgrade/downgrade history for a US stock.

        Returns consensus ratings (strong buy/buy/hold/sell/strong sell), target prices,
        and recent analyst upgrade/downgrade events. Critical for gauging
        Wall Street sentiment.

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:AAPL, NYSE:TSLA, NASDAQ:NVDA
            ctx: FastMCP Context

        Returns:
            ArtifactResponse with analyst data and LLM summary
        """
        if ctx:
            await ctx.info(f"📊 获取分析师评级: {symbol}")
        try:
            logger.info("MCP tool: get_us_analyst_recommendations", symbol=symbol)
            data = await fundamental_use_cases.get_us_analyst_recommendations(symbol)

            target = data.get("target_price", {})
            current = data.get("current_price")
            num_analysts = data.get("num_analysts", 0)
            recs = data.get("recommendations", [])
            upgrades = data.get("upgrade_history", [])
            summary_data = data.get("summary", {})

            # Build consensus summary
            total_buy = summary_data.get("strong_buy", 0) + summary_data.get("buy", 0)
            total_sell = summary_data.get("sell", 0) + summary_data.get("strong_sell", 0)
            total_hold = summary_data.get("hold", 0)
            consensus = (
                "看多" if total_buy > total_sell + total_hold
                else "看空" if total_sell > total_buy + total_hold
                else "中性"
            )

            target_mean = target.get("mean")
            upside_pct = (
                f" +{(target_mean - current) / current * 100:.1f}%"
                if target_mean and current and current > 0
                else ""
            )

            summary = (
                f"{symbol} 分析师共识: {consensus}"
                f" (买{total_buy}/持{total_hold}/卖{total_sell}, {num_analysts}位分析师)"
                f"{f', 目标价${target_mean:.2f}{upside_pct}' if target_mean else ''}"
                f"{f', 近{len(upgrades)}条评级变动' if upgrades else ''}"
            ).rstrip()

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_ANALYST_RECOMMENDATIONS.value,
                name=f"{symbol} 分析师评级",
                content=data,
                description=summary,
                metadata={"ticker": symbol},
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_ANALYST_RECOMMENDATIONS, f"{symbol} 分析师评级"
            )
        except Exception as e:
            logger.error("get_us_analyst_recommendations error", symbol=symbol, error=str(e))
            summary = f"获取 {symbol} 分析师评级失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_ANALYST_RECOMMENDATIONS.value,
                name=f"{symbol} 分析师评级",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_us_revenue_segments
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-fundamental", "segments"})
    async def get_us_revenue_segments(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Get revenue breakdown by geography and business segment for a US stock.

        Returns geographic revenue distribution (US, Europe, Asia, etc.) and
        business segment breakdown (Product, Service, etc.) with percentages.
        Shows how the company generates revenue across regions and segments.

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:AAPL, NYSE:TSLA, NASDAQ:NVDA
            ctx: FastMCP Context

        Returns:
            ArtifactResponse with segment data and LLM summary
        """
        if ctx:
            await ctx.info(f"🌍 获取收入构成: {symbol}")
        try:
            logger.info("MCP tool: get_us_revenue_segments", symbol=symbol)
            data = await fundamental_use_cases.get_us_revenue_segments(symbol)

            geo = data.get("geographic_segments", [])
            biz = data.get("business_segments", [])
            total_rev = data.get("total_revenue")

            parts = []
            if geo:
                top_geo = max(geo, key=lambda x: x.get("revenue", 0))
                parts.append(
                    f"区域: {top_geo['region']}({top_geo.get('pct', 0)}%)"
                    if top_geo.get("pct")
                    else f"区域: {len(geo)}个"
                )
            if biz:
                top_biz = max(biz, key=lambda x: x.get("revenue", 0))
                parts.append(
                    f"业务: {top_biz['segment']}({top_biz.get('pct', 0)}%)"
                    if top_biz.get("pct")
                    else f"业务: {len(biz)}个"
                )
            if total_rev:
                parts.append(f"总营收={_fmt_billions(total_rev)}")

            summary = f"{symbol} 收入构成: {', '.join(parts)}" if parts else f"{symbol} 收入构成: 暂无数据"

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_REVENUE_SEGMENTS.value,
                name=f"{symbol} 收入构成",
                content=data,
                description=summary,
                metadata={"ticker": symbol},
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_REVENUE_SEGMENTS, f"{symbol} 收入构成"
            )
        except Exception as e:
            logger.error("get_us_revenue_segments error", symbol=symbol, error=str(e))
            summary = f"获取 {symbol} 收入构成失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_REVENUE_SEGMENTS.value,
                name=f"{symbol} 收入构成",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_us_insider_trading
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-fundamental", "insider"})
    async def get_us_insider_trading(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Get recent insider trading activity for a US stock.

        Returns insider purchases and sales with transaction details.
        Includes net sentiment (buying vs selling pressure).
        Insiders (CEO, CFO, directors) have information advantage -
        clusters of insider buying often signal confidence.

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:AAPL, NYSE:TSLA, NASDAQ:NVDA
            ctx: FastMCP Context

        Returns:
            ArtifactResponse with insider transactions and LLM summary
        """
        if ctx:
            await ctx.info(f"👤 获取内部人交易: {symbol}")
        try:
            logger.info("MCP tool: get_us_insider_trading", symbol=symbol)
            data = await fundamental_use_cases.get_us_insider_trading(symbol)

            txns = data.get("transactions", [])
            s = data.get("summary", {})
            buys = s.get("buy_count", 0)
            sells = s.get("sell_count", 0)
            sentiment = s.get("net_sentiment", "neutral")

            sentiment_label = {
                "insider_buying": "净买入(看多信号)",
                "insider_selling": "净卖出(看空信号)",
                "neutral": "中性",
            }.get(sentiment, sentiment)

            summary = (
                f"{symbol} 内部人交易: {len(txns)}笔"
                f"(买入{buys}笔/卖出{sells}笔)"
                f", 整体情绪: {sentiment_label}"
            )

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_INSIDER_TRADING.value,
                name=f"{symbol} 内部人交易",
                content=data,
                description=summary,
                metadata={"ticker": symbol},
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_INSIDER_TRADING, f"{symbol} 内部人交易"
            )
        except Exception as e:
            logger.error("get_us_insider_trading error", symbol=symbol, error=str(e))
            summary = f"获取 {symbol} 内部人交易失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_INSIDER_TRADING.value,
                name=f"{symbol} 内部人交易",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_us_share_statistics
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-fundamental", "short-interest"})
    async def get_us_share_statistics(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Get share statistics including short interest for a US stock.

        Returns shares outstanding, float, short interest (% of float),
        days to cover, institutional ownership %, and insider ownership %.
        High short interest can indicate bearish sentiment or short squeeze potential.

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:TSLA, NASDAQ:GME, NYSE:AMC
            ctx: FastMCP Context

        Returns:
            ArtifactResponse with share statistics and LLM summary
        """
        if ctx:
            await ctx.info(f"📊 获取股份统计: {symbol}")
        try:
            logger.info("MCP tool: get_us_share_statistics", symbol=symbol)
            data = await fundamental_use_cases.get_us_share_statistics(symbol)

            short = data.get("short_interest", {})
            ownership = data.get("ownership", {})
            short_pct = short.get("short_pct_of_float")
            days_cover = short.get("days_to_cover")
            inst_pct = ownership.get("institutional_pct")

            # Classify short interest level
            if short_pct and short_pct > 20:
                short_label = "高做空比率(潜在轧空风险)"
            elif short_pct and short_pct > 10:
                short_label = "中等做空"
            elif short_pct:
                short_label = "低做空"
            else:
                short_label = ""

            summary = (
                f"{symbol} 股份统计: 流通股={_fmt_shares(data.get('float_shares'))}股"
            )
            if short_pct:
                summary += f", 做空比率={short_pct:.1f}%({short_label})"
            if days_cover:
                summary += f", 空头需{days_cover:.1f}天回补"
            if inst_pct:
                summary += f", 机构持股={inst_pct}%"
            summary = summary.rstrip()

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_SHARE_STATISTICS.value,
                name=f"{symbol} 股份统计",
                content=data,
                description=summary,
                metadata={"ticker": symbol},
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_SHARE_STATISTICS, f"{symbol} 股份统计"
            )
        except Exception as e:
            logger.error("get_us_share_statistics error", symbol=symbol, error=str(e))
            summary = f"获取 {symbol} 股份统计失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_SHARE_STATISTICS.value,
                name=f"{symbol} 股份统计",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_us_financial_health
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-fundamental", "health-score"})
    async def get_us_financial_health(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Get comprehensive financial health score for a US stock.

        Computes profitability (margins, ROE, ROA), liquidity (current/quick ratio),
        solvency (debt-to-equity, interest coverage), growth (revenue/earnings growth),
        and valuation (PE, PEG, PB) metrics. Returns a composite 0-100 health score
        with letter grade and key findings.

        Use this as the primary tool for answering "Is this stock financially healthy?"
        or "What is the financial quality of this company?".

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:AAPL, NYSE:TSLA, NASDAQ:NVDA
            ctx: FastMCP Context

        Returns:
            ArtifactResponse with health score breakdown and LLM summary
        """
        if ctx:
            await ctx.info(f"🏥 计算财务健康评分: {symbol}")
        try:
            logger.info("MCP tool: get_us_financial_health", symbol=symbol)
            data = await fundamental_use_cases.get_us_financial_health(symbol)

            name = data.get("name", symbol)
            score = data.get("health_score", 0)
            grade = data.get("grade", "?")
            label = data.get("grade_label", "")
            findings = data.get("key_findings", [])
            breakdown = data.get("score_breakdown", {})

            # Build summary
            findings_str = "; ".join(findings[:4]) if findings else "无明显异常"
            summary = (
                f"{name} ({symbol}) 财务健康: {score}分({grade} {label})"
                f" | 关键发现: {findings_str}"
            )

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_COMPANY_PROFILE.value,
                name=f"{symbol} 财务健康评分",
                content=data,
                description=summary,
                metadata={"ticker": symbol, "health_score": score, "grade": grade},
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_COMPANY_PROFILE, f"{symbol} 财务健康"
            )
        except Exception as e:
            logger.error("get_us_financial_health error", symbol=symbol, error=str(e))
            summary = f"获取 {symbol} 财务健康评分失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_COMPANY_PROFILE.value,
                name=f"{symbol} 财务健康",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_billions(val) -> str:
    """Format a large number as billions/millions string (dollar prefixed)."""
    if val is None:
        return "N/A"
    try:
        v = float(val)
    except Exception:
        return "N/A"
    if abs(v) >= 1e12:
        return f"${v / 1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:,.0f}"


def _fmt_shares(val) -> str:
    """Format a share count as billions/millions (no dollar prefix)."""
    if val is None:
        return "N/A"
    try:
        v = float(val)
    except Exception:
        return "N/A"
    if abs(v) >= 1e12:
        return f"{v / 1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"{v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"{v / 1e6:.2f}M"
    if abs(v) >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{v:,.0f}"
