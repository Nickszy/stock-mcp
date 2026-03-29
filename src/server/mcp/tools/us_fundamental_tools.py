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
        """获取美股EPS盈利历史 (实际 vs 预期).

        WHEN TO USE: 用户问 "这只美股业绩如何"、"最近几季度财报beat还是miss"、
            "盈利超预期了吗"、"NVDA earnings history".
        CONCEPT: EPS(Earnings Per Share)是每股收益. 对比实际EPS与分析师一致预期,
            计算surprise%(超预期幅度). 连续beat表示盈利质量高.
        DIFFERENTIATION: 本工具是美股专用, 仅覆盖US市场. A股用 get_financial_reports.
            与 get_us_valuation_metrics 互补: 本工具看盈利趋势, 那个看估值水平.
        next_recommended_tools: get_us_valuation_metrics → get_cash_flow_quality

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
        """分析美股现金流质量 (经营/自由现金流).

        WHEN TO USE: 用户问 "现金流健康吗"、"利润质量如何"、"自由现金流够不够"、
            "AAPL cash flow quality"、"赚的是真钱还是纸面利润".
        CONCEPT: 经营现金流(OCF)→减去资本支出(CapEx)→自由现金流(FCF).
            FCF/净利润 > 0.8 说明盈利含金量高(利润有真金白银支撑).
            比率低可能意味着应收账款膨胀或利润操纵风险.
        DIFFERENTIATION: 专注现金流年度趋势, 不是单季快照. 与 get_earnings_history
            互补: 那个看EPS trend, 这个看现金流验证盈利质量.
        next_recommended_tools: get_us_valuation_metrics → get_us_financial_health

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
        """获取美股估值指标快照 (PE/PB/EV_EBITDA/PEG/市值).

        WHEN TO USE: 用户问 "这美股贵不贵"、"PE是多少"、"估值高不高"、
            "TSLA valuation"、"市值多大"、"和同行比估值如何".
        CONCEPT: PE(TTM)=总市值/最近4季度净利润; PB=市值/净资产; EV/EBITDA剔除了
            资本结构差异, 适合跨行业比较. PEG<1通常被低估.
        DIFFERENTIATION: 本工具是估值**快照**(当前时点). A股估值用 get_valuation_metrics
            (含历史百分位). 本工具不含历史分位, 如需百分位用 get_us_financial_health.
            与 get_earnings_history 互补: 那个看盈利趋势, 这个看当前估值水平.
        next_recommended_tools: get_earnings_history → get_us_financial_health

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
        """获取美股机构持仓 (前15大机构 + 增减仓).

        WHEN TO USE: 用户问 "谁在买这只股票"、"机构怎么看"、"聪明钱在干嘛"、
            "NVDA institutional holdings"、"被哪些基金重仓".
        CONCEPT: 13F季报披露前15大机构持仓(BlackRock, Vanguard等). 机构增仓=看好,
            集中减仓=看空. 注意: 13F数据有45天延迟.
        DIFFERENTIATION: 美股专用(13F). A股用 get_stock_top10_shareholders 或
            get_fund_holdings. 与 get_us_insider_trading 互补:
            机构看基金/资管, 内部人看CEO/CFO等高管.
        next_recommended_tools: get_us_insider_trading → get_us_share_statistics

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
        """获取美股公司概况 (公司做什么 + 行业定位).

        WHEN TO USE: 用户刚开始研究一只美股, 问 "这家公司是干什么的"、"属于什么行业"、
            "基本情况介绍"、"company profile"、"先给我个概览".
        CONCEPT: 公司概况是投研入口层信息, 包含 sector、industry、业务描述、管理层、员工数、
            市值、52周区间等, 用来先建立公司画像.
        DIFFERENTIATION: 这是**研究起点工具**. 不分析估值、不分析盈利质量、不分析情绪.
            深入研究应继续用 get_us_valuation_metrics / get_earnings_history /
            get_us_financial_health.
        next_recommended_tools: get_us_financial_health → get_us_valuation_metrics

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
                component_type=ComponentType.US_COMPANY_PROFILE,
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
                component_type=ComponentType.US_COMPANY_PROFILE,
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
        """获取美股分析师评级与目标价.

        WHEN TO USE: 用户问 "华尔街怎么看"、"分析师评级如何"、"目标价是多少"、
            "upgrade/downgrade history"、"一致预期偏多还是偏空".
        CONCEPT: 汇总券商分析师的 buy/hold/sell 共识、目标价区间、以及近期升级/降级事件.
            这是 sell-side sentiment, 不是公司基本面本身.
        DIFFERENTIATION: 看的是**外部分析师观点**, 不是内部人交易, 也不是机构真实持仓.
            如需真实资金动作, 用 get_us_institutional_holdings 或 get_us_insider_trading.
        next_recommended_tools: get_earnings_history → get_us_valuation_metrics

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
                component_type=ComponentType.US_ANALYST_RECOMMENDATIONS,
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
                component_type=ComponentType.US_ANALYST_RECOMMENDATIONS,
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
        """获取美股收入构成拆分 (区域 + 业务线).

        WHEN TO USE: 用户问 "这家公司靠什么赚钱"、"收入主要来自哪个地区"、
            "业务结构集中吗"、"Apple revenue by segment".
        CONCEPT: 将总营收拆成 geographic segments(美洲/欧洲/亚太等)
            和 business segments(iPhone/Cloud/Ads等), 用于判断单一市场依赖度
            与增长驱动来源.
        DIFFERENTIATION: 这是**营收结构**工具, 不看利润率、不看估值、不看情绪.
            若想判断公司整体质量, 用 get_us_financial_health; 若想看估值,
            用 get_us_valuation_metrics.
        next_recommended_tools: get_us_company_profile → get_us_financial_health

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
                component_type=ComponentType.US_REVENUE_SEGMENTS,
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
                component_type=ComponentType.US_REVENUE_SEGMENTS,
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
        """获取美股内部人交易 (高管/董事买卖).

        WHEN TO USE: 用户问 "管理层在买还是卖"、"CEO/CFO最近有没有减持"、
            "insider buying"、"内部人信号偏多还是偏空".
        CONCEPT: 内部人交易指CEO、CFO、董事等申报交易. 连续净买入常被视为
            管理层信心信号, 连续大额减持则可能提示估值高位或兑现动机.
        DIFFERENTIATION: 看的是**公司内部人真实交易动作**, 不是分析师观点,
            也不是基金13F持仓. 机构动作用 get_us_institutional_holdings,
            卖方观点用 get_us_analyst_recommendations.
        next_recommended_tools: get_us_institutional_holdings → get_us_share_statistics

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
                component_type=ComponentType.US_INSIDER_TRADING,
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
                component_type=ComponentType.US_INSIDER_TRADING,
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
        """获取美股股份统计与做空数据.

        WHEN TO USE: 用户问 "空头多不多"、"有没有轧空风险"、"流通盘多大"、
            "short interest"、"days to cover"、"机构/内部人持股占比多少".
        CONCEPT: short interest % of float 衡量空头仓位拥挤度; days to cover
            衡量按近期成交量回补空头所需天数. 数值越高, squeeze 风险越大.
        DIFFERENTIATION: 这是**股本结构/空头拥挤度**工具, 不反映公司经营质量.
            若想看基本面健康, 用 get_us_financial_health; 若想看真实高管动作,
            用 get_us_insider_trading.
        next_recommended_tools: get_us_insider_trading → get_us_valuation_metrics

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
                component_type=ComponentType.US_SHARE_STATISTICS,
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
                component_type=ComponentType.US_SHARE_STATISTICS,
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
        """获取美股综合财务健康评分.

        WHEN TO USE: 用户问 "这家公司财务健康吗"、"基本面质量如何"、
            "是否值得长期跟踪"、"给我一个综合质量分".
        CONCEPT: 综合 profitability、liquidity、solvency、growth、valuation
            五类指标, 输出 0-100 分健康度、等级与关键发现. 适合作为单只股票
            基本面体检入口.
        DIFFERENTIATION: 这是**综合评分工具**. 与 get_us_company_profile 不同,
            那个是业务画像; 与 get_us_valuation_metrics 不同, 那个只看估值快照;
            与 get_cash_flow_quality 不同, 那个只看现金流含金量.
        next_recommended_tools: get_us_valuation_metrics → get_cash_flow_quality

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
                component_type=ComponentType.US_COMPANY_PROFILE,
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
                component_type=ComponentType.US_COMPANY_PROFILE,
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
