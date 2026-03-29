# src/server/mcp/tools/us_technical_tools.py
"""MCP tools for US stock technical analysis.

Active Tools (4):
  - get_us_technical_indicators:  美股技术指标 (MA/RSI/MACD/布林带/ATR)
  - get_us_volume_analysis:       量价分析 (RVol / OBV趋势)
  - get_us_price_history:         K线数据 (OHLCV, 可指定interval)
  - us_technical_analysis_summary: 一键综合技术分析摘要 (对齐竞品)
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastmcp import FastMCP, Context

from src.server.core.use_cases import technical as technical_use_cases
from src.server.utils.logger import logger
from src.server.core.dependencies import Container
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_artifact_envelope,
    create_artifact_response,
    create_symbol_error_response,
)
from src.server.domain.symbols.errors import SymbolResolutionError


def register_us_technical_tools(mcp: FastMCP):
    """Register US technical analysis tools."""

    # ------------------------------------------------------------------
    # get_us_technical_indicators  (主力工具，对齐竞品 get_us_technical_indicators)
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-technical", "indicators"})
    async def get_us_technical_indicators(
        symbol: str,
        days: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """美股技术指标分析。

WHEN TO USE: 用户要看美股单只股票的 MA/RSI/MACD/布林带/ATR，或先做技术面快照判断时使用；输入通常是“苹果 RSI 怎么样”“NVDA 技术指标如何”。
CONCEPT: 基于价格与成交量衍生的技术指标，用于观察趋势、动量、波动和超买超卖状态。
DIFFERENTIATION: 这是美股专用指标工具；A股技术指标请用 technical_tools.py 中的 get_technical_indicators。若只需K线用 get_us_price_history，若想要整合结论用 us_technical_analysis_summary。
next_recommended_tools: get_us_price_history, get_us_volume_analysis, us_technical_analysis_summary
"""
        if ctx:
            await ctx.info(f"📉 计算美股技术指标: {symbol} ({days}d)")
        try:
            logger.info(
                "MCP tool: get_us_technical_indicators", symbol=symbol, days=days
            )
            # Reuse existing TechnicalService via calculate_technical_indicators
            period = f"{max(days, 30)}d"
            result = await technical_use_cases.calculate_technical_indicators(
                symbol, period=period, interval="1d"
            )

            if isinstance(result, dict) and result.get("error"):
                raise ValueError(result["error"])

            # Build concise LLM summary
            rows = result.get("rows") or []
            latest = rows[-1] if rows else {}
            rsi = latest.get("rsi14") or latest.get("rsi")
            close = latest.get("close")
            ma20 = latest.get("ma20") or latest.get("sma20")
            macd_val = latest.get("macd") or (
                (result.get("indicators") or {}).get("macd", {}) or {}
            ).get("macd_line", [None])
            if isinstance(macd_val, list):
                macd_val = macd_val[-1] if macd_val else None

            rsi_label = (
                "超买" if rsi and rsi > 70 else "超卖" if rsi and rsi < 30 else "中性"
            )
            trend = (
                "价格在MA20之上"
                if (close and ma20 and close > ma20)
                else "价格在MA20之下"
            )

            summary = (
                f"{symbol} 技术面: RSI={f'{rsi:.1f}' if rsi else 'N/A'}({rsi_label}), "
                f"{trend}, MACD={f'{macd_val:.3f}' if macd_val else 'N/A'}"
            )

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_TECHNICAL_CHART,
                name=f"{symbol} 技术指标",
                content=result,
                description=summary,
                metadata={"ticker": symbol, "days": days},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_TECHNICAL_CHART, f"{symbol} 技术指标"
            )
        except Exception as e:
            logger.error(
                "get_us_technical_indicators error", symbol=symbol, error=str(e)
            )
            summary = f"获取 {symbol} 技术指标失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_TECHNICAL_CHART,
                name=f"{symbol} 技术指标",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_us_volume_analysis
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-technical", "volume"})
    async def get_us_volume_analysis(
        symbol: str,
        days: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """美股量价关系分析。

WHEN TO USE: 用户关心放量突破、缩量回调、OBV 背离、相对成交量异常时使用；常见问法如“TSLA 今天是不是放量”“QQQ 量价是否配合上涨”。
CONCEPT: 量价分析用成交量、相对成交量(RVol)和 OBV 判断资金参与度与趋势确认度。
DIFFERENTIATION: 这是美股专用的量能工具；不直接给全套技术指标，也不同于仅返回K线的 get_us_price_history。A股技术分析请用 technical_tools.py。
next_recommended_tools: get_us_technical_indicators, get_us_price_history, us_technical_analysis_summary
"""
        if ctx:
            await ctx.info(f"📊 量价分析: {symbol} ({days}d)")
        try:
            logger.info("MCP tool: get_us_volume_analysis", symbol=symbol, days=days)
            data = await technical_use_cases.get_us_volume_analysis(
                symbol, days=days
            )

            avg_vol = data.get("avg_volume_20d", 0)
            rvol = data.get("rvol")
            obv_trend = data.get("obv_trend", "unknown")
            cur_vol = data.get("current_volume", 0)

            rvol_label = (
                "异常放量"
                if rvol and rvol > 2
                else (
                    "温和放量"
                    if rvol and rvol > 1.2
                    else "缩量" if rvol and rvol < 0.7 else "正常"
                )
            )
            summary = (
                f"{symbol} 成交量分析: 当前量{_fmt_vol(cur_vol)} "
                f"(RVol={f'{rvol:.2f}x' if rvol else 'N/A'} {rvol_label}), "
                f"20日均量{_fmt_vol(avg_vol)}, OBV趋势{obv_trend}"
            )

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_VOLUME_ANALYSIS,
                name=f"{symbol} 量价分析",
                content=data,
                description=summary,
                metadata={"ticker": symbol, "days": days},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_VOLUME_ANALYSIS, f"{symbol} 量价分析"
            )
        except Exception as e:
            logger.error("get_us_volume_analysis error", symbol=symbol, error=str(e))
            summary = f"获取 {symbol} 量价分析失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_VOLUME_ANALYSIS,
                name=f"{symbol} 量价分析",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # get_us_price_history (K线数据)
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-technical", "kline"})
    async def get_us_price_history(
        symbol: str,
        days: int = 60,
        interval: str = "1d",
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """美股K线历史数据 (OHLCV)。

WHEN TO USE: 用户要画K线图、看历史走势、找区间高低点时使用；常见问法如“AAPL 最近60天K线”“TSLA周线数据”。
CONCEPT: OHLCV(开盘/最高/最低/收盘/成交量)是技术分析的基础数据，按日/周/月聚合。
DIFFERENTIATION: 这是美股专用K线工具；返回原始价格数据而非衍生指标。需要技术指标请用 get_us_technical_indicators。A股K线用 asset_tools.py 的 get_kline_data。
next_recommended_tools: get_us_technical_indicators, get_us_volume_analysis
"""
        if ctx:
            await ctx.info(f"📈 获取K线数据: {symbol} ({days}d/{interval})")
        try:
            logger.info(
                "MCP tool: get_us_price_history",
                symbol=symbol,
                days=days,
                interval=interval,
            )
            data = await technical_use_cases.get_us_price_history(
                symbol, days=days, interval=interval
            )

            bars = data.get("bars", [])
            if bars:
                first_close = bars[0].get("close", 0)
                last_close = bars[-1].get("close", 0)
                chg_pct = (
                    ((last_close - first_close) / first_close * 100)
                    if first_close
                    else 0
                )
                high = max(b["high"] for b in bars)
                low = min(b["low"] for b in bars)
                summary = (
                    f"{symbol} {days}d K线: 最新收盘{last_close:.2f}, "
                    f"区间涨跌{chg_pct:+.2f}%, 高{high:.2f}/低{low:.2f}, "
                    f"共{len(bars)}根{interval}K线"
                )
            else:
                summary = f"{symbol} K线数据为空"

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_TECHNICAL_CHART,
                name=f"{symbol} K线数据 ({interval})",
                content=data,
                description=summary,
                metadata={"ticker": symbol, "interval": interval, "days": days},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_TECHNICAL_CHART, f"{symbol} K线"
            )
        except Exception as e:
            logger.error("get_us_price_history error", symbol=symbol, error=str(e))
            summary = f"获取 {symbol} K线数据失败: {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_TECHNICAL_CHART,
                name=f"{symbol} K线",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

    # ------------------------------------------------------------------
    # us_technical_analysis_summary  (综合技术分析，对齐竞品同名工具)
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-technical", "summary"})
    async def us_technical_analysis_summary(
        symbol: str,
        days: int = 60,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Comprehensive US stock technical analysis summary.

        Combines price history, volume analysis, and technical indicators
        into a single structured report. Identifies trend, momentum,
        support/resistance levels, and key signals.

        Use this as the primary entry point for US stock technical analysis.

        Args:
            symbol: US stock ticker. Format: EXCHANGE:SYMBOL
                Examples: NASDAQ:AAPL, NYSE:TSLA, NASDAQ:NVDA, NYSE:SPY
            days: Analysis window in calendar days (default 60)
            ctx: FastMCP Context

        Returns:
            ArtifactResponse with comprehensive technical analysis
        """
        if ctx:
            await ctx.info(f"🔬 美股技术综合分析: {symbol} ({days}d)")
        try:
            import asyncio

            logger.info(
                "MCP tool: us_technical_analysis_summary", symbol=symbol, days=days
            )

            # Fetch price history and volume analysis in parallel
            price_task = technical_use_cases.get_us_price_history(
                symbol, days=days, interval="1d"
            )
            vol_task = technical_use_cases.get_us_volume_analysis(
                symbol, days=min(days, 30)
            )
            ind_task = technical_use_cases.calculate_technical_indicators(
                symbol, period=f"{max(days, 30)}d", interval="1d"
            )

            price_data, vol_data, ind_data = await asyncio.gather(
                price_task, vol_task, ind_task, return_exceptions=True
            )

            # Gracefully handle partial failures
            errors = []
            for name, result in [
                ("price", price_data),
                ("volume", vol_data),
                ("indicators", ind_data),
            ]:
                if isinstance(result, Exception):
                    errors.append(f"{name}: {result}")

            bars = (
                price_data.get("bars", [])
                if not isinstance(price_data, Exception)
                else []
            )
            latest_bar = bars[-1] if bars else {}
            close = latest_bar.get("close")

            # --- Volume signals ---
            rvol = vol_data.get("rvol") if not isinstance(vol_data, Exception) else None
            obv_trend = (
                vol_data.get("obv_trend", "N/A")
                if not isinstance(vol_data, Exception)
                else "N/A"
            )

            # --- Indicator signals ---
            ind_rows = (
                (ind_data.get("rows") or [])
                if not isinstance(ind_data, Exception)
                else []
            )
            latest_ind = ind_rows[-1] if ind_rows else {}
            rsi = latest_ind.get("rsi14") or latest_ind.get("rsi")
            ma20 = latest_ind.get("ma20") or latest_ind.get("sma20")
            ma60 = latest_ind.get("ma60") or latest_ind.get("sma60")

            # --- Trend classification ---
            signals: List[str] = []
            if close and ma20:
                signals.append(
                    "价格 > MA20 (短期上升趋势)"
                    if close > ma20
                    else "价格 < MA20 (短期下降趋势)"
                )
            if close and ma60:
                signals.append(
                    "价格 > MA60 (中期上升趋势)"
                    if close > ma60
                    else "价格 < MA60 (中期下降趋势)"
                )
            if rsi:
                if rsi > 70:
                    signals.append(f"RSI={rsi:.1f} 超买区间")
                elif rsi < 30:
                    signals.append(f"RSI={rsi:.1f} 超卖区间")
                else:
                    signals.append(f"RSI={rsi:.1f} 中性")
            if rvol and rvol > 1.5:
                signals.append(f"RVol={rvol:.2f}x 放量")
            if obv_trend == "up":
                signals.append("OBV向上 (资金流入)")
            elif obv_trend == "down":
                signals.append("OBV向下 (资金流出)")

            summary = (
                f"{symbol} 技术综合: 收盘{f'{close:.2f}' if close else 'N/A'}; "
                + ", ".join(signals[:4])
            )
            if errors:
                summary += f" [部分数据获取失败: {'; '.join(errors)}]"

            content = {
                "ticker": symbol,
                "days": days,
                "latest_price": close,
                "signals": signals,
                "price_bars": (
                    bars[-20:] if bars else []
                ),  # Last 20 bars for frontend chart
                "volume": {
                    "rvol": rvol,
                    "obv_trend": obv_trend,
                    "avg_volume_20d": (
                        vol_data.get("avg_volume_20d")
                        if not isinstance(vol_data, Exception)
                        else None
                    ),
                },
                "indicators": {
                    "rsi": rsi,
                    "ma20": ma20,
                    "ma60": ma60,
                },
                "errors": errors,
            }

            artifact = create_artifact_envelope(
                component_type=ComponentType.US_TECHNICAL_CHART,
                name=f"{symbol} 技术综合分析",
                content=content,
                description=summary,
                metadata={"ticker": symbol, "days": days},
                visible_to_llm=False,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, ComponentType.US_TECHNICAL_CHART, f"{symbol} 技术分析"
            )
        except Exception as e:
            logger.error(
                "us_technical_analysis_summary error", symbol=symbol, error=str(e)
            )
            summary = f"技术综合分析失败 ({symbol}): {e}"
            artifact = create_artifact_envelope(
                component_type=ComponentType.US_TECHNICAL_CHART,
                name=f"{symbol} 技术分析",
                content={"error": str(e)},
                description=summary,
                visible_to_llm=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


    # ------------------------------------------------------------------
    # US Market Overview
    # ------------------------------------------------------------------
    @mcp.tool(tags={"us-market", "overview"})
    async def get_us_market_overview(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """Get US market overview: major indices, VIX, sector performance, and sentiment.

        Provides a comprehensive snapshot of the US stock market including:
        - Major index performance (SPY/QQQ/DIA/IWM)
        - CBOE VIX volatility level and signal
        - Sector ETF performance (11 GICS sectors ranked by change%)
        - Market breadth and sentiment assessment

        No arguments needed — always returns the full market snapshot.

        Returns:
            Market overview with indices, sector rankings, VIX, and sentiment.
        """
        if ctx:
            await ctx.info("获取美股市场概览")

        try:
            logger.info("MCP tool: get_us_market_overview")
            gateway = Container.market_gateway()
            result = await gateway.get_us_market_overview()

            indices = result.get("indices", [])
            sectors = result.get("sectors", [])
            vix = result.get("vix", {})
            breadth = result.get("market_breadth", {})
            sentiment = result.get("sentiment", "")

            # Build summary
            spy_info = next((i for i in indices if i["symbol"] == "SPY"), {})
            spy_pct = spy_info.get("change_pct", 0) if spy_info else 0
            vix_level = vix.get("level", "N/A")
            vix_signal = vix.get("signal", "")

            summary = (
                f"美股市场概览: SPY {spy_pct:+.2f}%, "
                f"VIX {vix_level}({vix_signal}), "
                f"板块上涨{breadth.get('up_sectors', 0)}/下跌{breadth.get('down_sectors', 0)}, "
                f"整体{sentiment}"
            )

            # Markdown output
            md = "## 美股市场概览\n\n"
            md += f"**整体情绪**: {sentiment} | **VIX**: {vix_level} ({vix_signal})\n\n"

            md += "### 主要指数\n"
            md += "| 指数 | 价格 | 涨跌幅% | 涨跌额 |\n"
            md += "|------|------|---------|--------|\n"
            for idx in indices:
                md += (
                    f"| {idx['name']} ({idx['symbol']}) "
                    f"| {idx['price']:.2f} "
                    f"| {idx['change_pct']:+.2f}% "
                    f"| {idx['change']:+.2f} |\n"
                )

            md += "\n### 板块表现 (按涨跌幅排序)\n"
            md += "| 板块 | ETF | 涨跌幅% |\n"
            md += "|------|-----|--------|\n"
            for s in sectors:
                md += f"| {s['name']} | {s['symbol']} | {s['change_pct']:+.2f}% |\n"

            md += f"\n### 市场广度\n"
            md += f"- 上涨板块: {breadth.get('up_sectors', 0)} / {breadth.get('up_sectors', 0) + breadth.get('down_sectors', 0)}\n"

            return create_artifact_response(
                summary=summary,
                artifact=create_artifact_envelope(
                    component_type=ComponentType.US_SECTOR_ETF,
                    name="美股市场概览",
                    content=result,
                    description=summary,
                    markdown=md,
                    visible_to_llm=True,
                    display_in_report=True,
                ),
            )

        except Exception as e:
            logger.error(f"get_us_market_overview failed: {e}")
            return {"error": str(e), "summary": f"美股市场概览获取失败: {e}"}


def _fmt_vol(val) -> str:
    if val is None:
        return "N/A"
    v = float(val)
    if v >= 1e9:
        return f"{v / 1e9:.1f}B"
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{v / 1e3:.1f}K"
    return str(int(v))
