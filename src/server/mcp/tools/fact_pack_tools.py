# src/server/mcp/tools/fact_pack_tools.py
"""MCP tools for stock fact pack data (COL-148).

Tools:
  - get_stock_fact_pack: 股票事实包聚合接口
"""

import time
from typing import Any, Dict

from fastmcp import FastMCP, Context

from src.server.core.dependencies import Container
from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_standard_artifact_response,
)


def register_fact_pack_tools(mcp: FastMCP):
    """Register fact pack MCP tools."""

    # ------------------------------------------------------------------
    # get_stock_fact_pack — 股票事实包
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fact-pack", "fundamental"})
    async def get_stock_fact_pack(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取股票事实包(Fact Pack)：一次调用聚合全维度结构化事实数据。

        聚合 10 大事实类别: 证券主数据、财务、市场估值(含融资融券)、公司治理、
        事件(分红/回购/解禁)、业务结构(主营构成)、公司主档、同行、限售解禁、回购数据。
        返回统一结构: entity + facts + source_trace + coverage。

        WHEN TO USE:
        - First call for any A-share stock analysis (entry point tool)
        - "Give me everything about 600519" / "Complete data for Moutai"
        - Need comprehensive stock data without calling multiple individual tools

        CONCEPT:
        One-call aggregated fact pack covering security master, financials, valuation,
        governance, events (dividends/repurchase/lockup), business structure, company profile,
        peers, restricted release, and repurchase data.

        DIFFERENTIATION:
        - vs get_us_stock_fact_pack: This is A-share only; us version for US stocks
        - vs individual tools (get_financials, get_valuation, etc): This aggregates ALL dimensions
        - vs get_market_fact_pack: This focuses on company fundamentals; market focuses on trading data

        next_recommended_tools: get_us_stock_fact_pack, get_market_fact_pack, get_sector_fact_pack

        Args:
            symbol: 股票代码 (如 600519, 300750)
            ctx: FastMCP Context.

        Returns:
            股票事实包，包含 entity, facts, source_trace, coverage, missing_fields
        """
        if ctx:
            await ctx.info(f"获取股票事实包: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_stock_fact_pack", symbol=symbol)

            gateway = Container.market_gateway()
            result = await gateway.get_stock_fact_pack(symbol=symbol)

            elapsed = time.perf_counter() - t0
            categories_fetched = result.get("categories_fetched", 0)
            categories_total = result.get("categories_total", 8)
            coverage = result.get("coverage", {})
            missing = result.get("missing_fields", [])
            entity = result.get("entity", {})

            # Get name from security_master if available
            sec_master = result.get("facts", {}).get("security_master", {})
            name = sec_master.get("name", symbol)

            summary = (
                f"股票事实包: {name}({symbol}) "
                f"[{categories_fetched}/{categories_total}类] "
                f"(耗时 {elapsed:.1f}s)"
            )

            # Use adapter-generated fact_markdown (COL-181: single source of truth)
            adapter_md = result.get("fact_markdown", "")
            if adapter_md:
                # Prepend runtime header (coverage/elapsed not available at adapter build time)
                header = f"**已获取**: {categories_fetched}/{categories_total} 类"
                header += f" | **耗时**: {elapsed:.1f}s\n\n"
                if coverage:
                    complete = sum(1 for v in coverage.values() if v == "complete")
                    partial = sum(1 for v in coverage.values() if v == "partial")
                    header += f"**覆盖率**: {complete}完整 + {partial}部分 / {categories_total}类\n\n"
                md = adapter_md.replace(
                    f"# 股票事实包: {name}({symbol})\n\n",
                    f"# 股票事实包: {name}({symbol})\n\n{header}",
                    1,
                )
            else:
                # Fallback: minimal inline view when adapter didn't produce markdown
                md = f"# 股票事实包: {name}({symbol})\n\n"
                md += f"**已获取**: {categories_fetched}/{categories_total} 类"
                md += f" | **耗时**: {elapsed:.1f}s\n\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"股票事实包: {name}({symbol})",
                data=result,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_stock_fact_pack failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取股票事实包失败: {e}",
                component_type=ComponentType.TABLE,
                name="事实包错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取股票事实包失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_fund_fact_pack — 基金事实包
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fact-pack", "fund"})
    async def get_fund_fact_pack(
        fund_code: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取基金事实包(Fact Pack)：一次调用聚合全维度基金结构化事实数据。

        WHEN TO USE:
        - First call for any fund analysis (entry point for funds)
        - "Give me everything about fund 110011"
        - Need comprehensive fund data: holdings, performance, manager, fees, allocation
        - Comparing fund vs fund on all dimensions

        CONCEPT:
        One-call aggregated fact pack covering 8 categories: fund master data,
        NAV & returns, portfolio holdings, fund manager info, scale & shares,
        asset allocation, fees & dividends, peer comparison.
        Returns: entity + facts + source_trace + coverage.

        DIFFERENTIATION:
        - vs get_stock_fact_pack: This is for mutual funds; stock version for equities
        - vs get_etf_fact_pack: This covers open-end mutual funds; ETF version for ETFs
        - vs individual fund tools: This aggregates ALL dimensions in one call

        next_recommended_tools: get_stock_fact_pack, get_etf_fact_pack, get_index_fact_pack

        Args:
            fund_code: 基金代码 (如 110011, 005827)
            ctx: FastMCP Context.

        Returns:
            基金事实包，包含 entity, facts, source_trace, coverage, missing_fields
        """
        if ctx:
            await ctx.info(f"获取基金事实包: {fund_code}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_fund_fact_pack", fund_code=fund_code)

            gateway = Container.market_gateway()
            result = await gateway.get_fund_fact_pack(fund_code=fund_code)

            elapsed = time.perf_counter() - t0
            categories_fetched = result.get("categories_fetched", 0)
            categories_total = result.get("categories_total", 8)
            coverage = result.get("coverage", {})
            missing = result.get("missing_fields", [])

            # Get name from master facts if available
            master = result.get("facts", {}).get("master", {})
            name = master.get("基金简称", master.get("fund_name", fund_code))

            summary = (
                f"基金事实包: {name}({fund_code}) "
                f"[{categories_fetched}/{categories_total}类] "
                f"(耗时 {elapsed:.1f}s)"
            )

            # Use adapter-generated fact_markdown (COL-182: single source of truth)
            md = result.get("fact_markdown", "")
            if not md:
                md = f"# 基金事实包: {name}({fund_code})\n\n"
                md += f"**已获取**: {categories_fetched}/{categories_total} 类"
                md += f" | **耗时**: {elapsed:.1f}s\n\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"基金事实包: {name}({fund_code})",
                data=result,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=fund_code,
            )

        except Exception as e:
            logger.error(f"get_fund_fact_pack failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取基金事实包失败: {e}",
                component_type=ComponentType.TABLE,
                name="基金事实包错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取基金事实包失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_market_fact_pack — 行情事实包
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fact-pack", "market"})
    async def get_market_fact_pack(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取行情事实包(Fact Pack)：聚合全维度行情结构化事实数据.

        WHEN TO USE:
        - Need trading-oriented data for a stock (not fundamental/company data)
        - Technical analysis entry: valuation snapshot + K-line factors + money flow
        - Pre-trade analysis: check margin data, money flow, relative strength

        CONCEPT:
        Aggregates trading data: valuation metrics, technical snapshot, K-line factors,
        money flow, market breadth, sector/index, derivatives, relative strength,
        north-bound capital, margin trading.

        DIFFERENTIATION:
        - vs get_stock_fact_pack: This focuses on trading data; stock focuses on fundamentals
        - vs get_technical_indicators: This aggregates multiple dimensions; technical is single-dim
        - vs get_money_flow: This includes money flow plus 9 other dimensions

        next_recommended_tools: get_stock_fact_pack, get_technical_indicators, get_money_flow

        Args:
            symbol: 股票代码 (如 600519, 000001)
            ctx: FastMCP Context.

        Returns:
            行情事实包，包含 entity, facts, source_trace, coverage, missing_fields
        """
        if ctx:
            await ctx.info(f"获取行情事实包: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_market_fact_pack", symbol=symbol)

            gateway = Container.market_gateway()
            result = await gateway.get_market_fact_pack(symbol=symbol)

            elapsed = time.perf_counter() - t0
            categories_fetched = result.get("categories_fetched", 0)
            categories_total = result.get("categories_total", 8)
            coverage = result.get("coverage", {})
            missing = result.get("missing_fields", [])

            summary = (
                f"行情事实包: {symbol} "
                f"[{categories_fetched}/{categories_total}类] "
                f"(耗时 {elapsed:.1f}s)"
            )

            # Use adapter-generated fact_markdown (COL-182: single source of truth)
            md = result.get("fact_markdown", "")
            if not md:
                md = f"# 行情事实包: {symbol}\n\n"
                md += f"**已获取**: {categories_fetched}/{categories_total} 类"
                md += f" | **耗时**: {elapsed:.1f}s\n\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"行情事实包: {symbol}",
                data=result,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_market_fact_pack failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取行情事实包失败: {e}",
                component_type=ComponentType.TABLE,
                name="行情事实包错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取行情事实包失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_us_stock_fact_pack — 美股事实包 (COL-168)
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fact-pack", "us-fundamental"})
    async def get_us_stock_fact_pack(
        ticker: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取美股事实包(Fact Pack)：一次调用聚合全维度美股结构化事实数据.

        WHEN TO USE:
        - First call for any US stock analysis (entry point for US equities)
        - "Give me everything about AAPL" / "Complete data for Tesla"
        - Need comprehensive US stock data without calling multiple individual tools

        CONCEPT:
        One-call aggregated fact pack covering 6 categories: company profile,
        valuation metrics, financial health, institutional holdings & insider trading,
        analyst ratings & revenue segments, price-volume technical analysis.
        Returns: entity + facts + source_trace + coverage.

        DIFFERENTIATION:
        - vs get_stock_fact_pack: This is US stocks; stock version is for A-shares
        - vs individual US tools: This aggregates ALL dimensions in one call
        - vs get_market_fact_pack: This focuses on company fundamentals; market on trading data

        next_recommended_tools: get_stock_fact_pack, get_us_valuation_metrics, get_us_financial_health

        Args:
            ticker: 美股代码 (如 AAPL, TSLA, MSFT)
            ctx: FastMCP Context.

        Returns:
            美股事实包，包含 entity, facts, source_trace, coverage, missing_fields
        """
        if ctx:
            await ctx.info(f"获取美股事实包: {ticker}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_us_stock_fact_pack", ticker=ticker)

            gateway = Container.market_gateway()
            result = await gateway.get_us_stock_fact_pack(ticker=ticker)

            elapsed = time.perf_counter() - t0
            categories_fetched = result.get("categories_fetched", 0)
            categories_total = result.get("categories_total", 6)
            coverage = result.get("coverage", {})
            missing = result.get("missing_fields", [])
            facts = result.get("facts", {})

            # Get company name from profile
            profile = facts.get("profile", {})
            name = profile.get("company_name", ticker)

            summary = (
                f"美股事实包: {name}({ticker}) "
                f"[{categories_fetched}/{categories_total}类] "
                f"(耗时 {elapsed:.1f}s)"
            )

            # Use adapter-generated fact_markdown (COL-182: single source of truth)
            md = result.get("fact_markdown", "")
            if not md:
                md = f"# 美股事实包: {name}({ticker})\n\n"
                md += f"**已获取**: {categories_fetched}/{categories_total} 类"
                md += f" | **耗时**: {elapsed:.1f}s\n\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"美股事实包: {name}({ticker})",
                data=result,
                source="yahoo",
                description=summary,
                markdown=md,
                symbol=ticker,
            )

        except Exception as e:
            logger.error(f"get_us_stock_fact_pack failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取美股事实包失败: {e}",
                component_type=ComponentType.TABLE,
                name="美股事实包错误",
                data={"error": str(e)},
                source="yahoo",
                description=f"获取美股事实包失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_etf_fact_pack — ETF事实包
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fact-pack", "etf"})
    async def get_etf_fact_pack(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取ETF事实包(Fact Pack)：聚合全维度ETF结构化事实数据.

        WHEN TO USE:
        - First call for any ETF analysis (entry point for ETF research)
        - Need ETF fundamentals + trading data + technical signals in one call
        - Evaluating ETF for portfolio allocation decisions

        CONCEPT:
        Aggregates 5 categories: ETF master data, real-time quotes, historical performance,
        capital flow/redemptions, technical signals (RSI/MACD/BOLL).
        Returns: entity + facts + source_trace + coverage.

        DIFFERENTIATION:
        - vs get_stock_fact_pack: This is for ETFs; stock version for individual equities
        - vs get_etf_detail + get_etf_performance: This aggregates both plus more
        - vs get_fund_fact_pack: This is ETF-specific with technical signals; fund is for mutual funds

        next_recommended_tools: get_stock_fact_pack, get_etf_detail, get_etf_performance

        Args:
            symbol: ETF代码 (如 510300, 159919)
            ctx: FastMCP Context.

        Returns:
            ETF事实包，包含 entity, facts, source_trace, coverage, missing_fields
        """
        if ctx:
            await ctx.info(f"获取ETF事实包: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_etf_fact_pack", symbol=symbol)

            gateway = Container.market_gateway()
            result = await gateway.get_etf_fact_pack(symbol=symbol)

            elapsed = time.perf_counter() - t0
            categories_fetched = result.get("categories_fetched", 0)
            categories_total = result.get("categories_total", 5)
            coverage = result.get("coverage", {})
            missing = result.get("missing_fields", [])
            facts = result.get("facts", {})

            # Get name from master or realtime
            master = facts.get("master", {})
            rt = facts.get("realtime", {})
            name = rt.get("name", master.get("名称", symbol))

            summary = (
                f"ETF事实包: {name}({symbol}) "
                f"[{categories_fetched}/{categories_total}类] "
                f"(耗时 {elapsed:.1f}s)"
            )

            # Use adapter-generated fact_markdown (COL-182: single source of truth)
            md = result.get("fact_markdown", "")
            if not md:
                md = f"# ETF事实包: {name}({symbol})\n\n"
                md += f"**已获取**: {categories_fetched}/{categories_total} 类"
                md += f" | **耗时**: {elapsed:.1f}s\n\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"ETF事实包: {name}({symbol})",
                data=result,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_etf_fact_pack failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取ETF事实包失败: {e}",
                component_type=ComponentType.TABLE,
                name="ETF事实包错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取ETF事实包失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_index_fact_pack — 指数事实包
    # ------------------------------------------------------------------
    @mcp.tool(tags={"fact-pack", "index"})
    async def get_index_fact_pack(
        symbol: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取指数事实包(Fact Pack)：聚合全维度指数结构化事实数据.

        WHEN TO USE:
        - Index-level analysis (CSI 300, SSE 50, ChiNext, etc.)
        - Need index PE/PB percentile ranking for market timing
        - Checking index constituent list or technical signals

        CONCEPT:
        Aggregates 5 categories: index master data, PE/PB valuation with historical percentile,
        price performance, constituent stocks, technical signals (RSI/MACD/BOLL).

        DIFFERENTIATION:
        - vs get_stock_fact_pack: This is for market indices; stock is for individual equities
        - vs get_etf_fact_pack: This analyzes the index itself; ETF analyzes the tracking fund
        - vs get_valuation_metrics: This includes valuation plus 4 more dimensions

        next_recommended_tools: get_etf_fact_pack, get_sector_fact_pack, get_valuation_metrics

        Args:
            symbol: 指数代码 (如 000300=沪深300, 000001=上证指数, 399006=创业板指)
            ctx: FastMCP Context.

        Returns:
            指数事实包，包含 entity, facts, source_trace, coverage, missing_fields
        """
        if ctx:
            await ctx.info(f"获取指数事实包: {symbol}")
        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_index_fact_pack", symbol=symbol)

            gateway = Container.market_gateway()
            result = await gateway.get_index_fact_pack(symbol=symbol)

            elapsed = time.perf_counter() - t0
            categories_fetched = result.get("categories_fetched", 0)
            categories_total = result.get("categories_total", 5)
            coverage = result.get("coverage", {})
            missing = result.get("missing_fields", [])
            facts = result.get("facts", {})

            # Get name from master
            master = facts.get("master", {})
            name = master.get("index_name", symbol)

            summary = (
                f"指数事实包: {name}({symbol}) "
                f"[{categories_fetched}/{categories_total}类] "
                f"(耗时 {elapsed:.1f}s)"
            )

            # Use adapter-generated fact_markdown (COL-182: single source of truth)
            md = result.get("fact_markdown", "")
            if not md:
                md = f"# 指数事实包: {name}({symbol})\n\n"
                md += f"**已获取**: {categories_fetched}/{categories_total} 类"
                md += f" | **耗时**: {elapsed:.1f}s\n\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"指数事实包: {name}({symbol})",
                data=result,
                source="akshare",
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_index_fact_pack failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取指数事实包失败: {e}",
                component_type=ComponentType.TABLE,
                name="指数事实包错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取指数事实包失败: {e}",
            )

    @mcp.tool(tags={"fact-pack"})
    async def get_sector_fact_pack(
        sector_name: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取行业事实包(Fact Pack)：聚合全维度行业结构化事实数据.

        WHEN TO USE:
        - Sector/industry analysis entry point (banking, semiconductor, liquor, etc.)
        - Need sector composition, valuation, money flow, and peer comparison
        - Evaluating sector rotation opportunities

        CONCEPT:
        Aggregates 5 categories: sector positioning, constituent stocks,
        structure snapshot, peer comparison, evidence summary (money flow + PE/PB history).
        Returns: entity + facts + source_trace + coverage.

        DIFFERENTIATION:
        - vs get_stock_fact_pack: This analyzes a whole industry; stock is for individual equities
        - vs get_sector_fact_pack: Same concept but with deeper peer comparison
        - vs get_industry_ranking: That shows real-time ranking; this is deep structural analysis

        next_recommended_tools: get_stock_fact_pack, get_industry_ranking, get_sector_money_flow_history

        Args:
            sector_name: 行业名称 (如 白酒, 半导体, 新能源, 银行)
            ctx: FastMCP Context.

        Returns:
            行业事实包，包含 entity, facts, source_trace, coverage, missing_fields
        """
        if ctx:
            await ctx.info(f"获取行业事实包: {sector_name}", extra={"sector_name": sector_name})

        try:
            gateway = Container.market_gateway()
            result = await gateway.get_sector_fact_pack(sector_name=sector_name)

            categories_fetched = result.get("categories_fetched", 0)
            categories_total = result.get("categories_total", 5)
            elapsed = result.get("elapsed_seconds", 0)
            coverage = result.get("coverage", {})
            missing = result.get("missing_fields", [])

            name = sector_name
            summary = f"{name} 行业事实包: {categories_fetched}/{categories_total} 类已获取"
            if missing:
                summary += f" | 缺失: {', '.join(missing)}"
            summary += f" | 耗时{elapsed:.1f}s"

            md = result.get("fact_markdown", "")
            if not md:
                md = f"# 行业事实包: {name}\n\n"
                md += f"**已获取**: {categories_fetched}/{categories_total} 类"
                md += f" | **耗时**: {elapsed:.1f}s\n\n"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"行业事实包: {name}",
                data=result,
                source="akshare",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_sector_fact_pack failed: {e}")
            return create_standard_artifact_response(
                summary=f"获取行业事实包失败: {e}",
                component_type=ComponentType.TABLE,
                name="行业事实包错误",
                data={"error": str(e)},
                source="akshare",
                description=f"获取行业事实包失败: {e}",
            )
