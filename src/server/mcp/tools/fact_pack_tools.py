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

        Typical use cases:
        - "给我 600519 的完整事实包"
        - "贵州茅台的最新全维度结构化数据"
        - "查一下宁德时代的基本面+治理+事件数据"

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

        聚合 8 大事实类别: 基金主档、净值与收益、持仓穿透、基金经理、
        规模份额、资产配置、费率分红、同类比较。
        返回统一结构: entity + facts + source_trace + coverage。

        Typical use cases:
        - "给我 110011 的完整基金事实包"
        - "易方达中小盘的最新全维度数据"
        - "查一下华夏沪深300的持仓+业绩+规模数据"

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
        """获取行情事实包(Fact Pack)：一次调用聚合全维度行情结构化事实数据。

        聚合 10 大事实类别: 标的估值、技术快照、K线因子、资金流、市场广度、
        指数板块、衍生行情、相对强弱、北向资金、融资融券。
        返回统一结构: entity + facts + source_trace + coverage。

        Typical use cases:
        - "给我 600519 的完整行情事实包"
        - "贵州茅台的最新行情+资金流+技术指标数据"
        - "查一下宁德时代的相对强弱+资金流+估值数据"

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
        """获取美股事实包(Fact Pack)：一次调用聚合全维度美股结构化事实数据。

        聚合 6 大事实类别: 公司档案、估值指标、财务健康、
        机构持仓与内部人交易、分析师评级与收入结构、量价技术分析。
        返回统一结构: entity + facts + source_trace + coverage。

        Typical use cases:
        - "给我 AAPL 的完整美股事实包"
        - "Apple 的最新全维度结构化数据"
        - "查一下 TSLA 的估值+财务健康+机构持仓"

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
        """获取ETF事实包(Fact Pack)：一次调用聚合全维度ETF结构化事实数据。

        聚合 5 大事实类别: ETF主档、实时行情、历史表现、资金流/申赎、技术信号。
        返回统一结构: entity + facts + source_trace + coverage。

        Typical use cases:
        - "给我 510300 的完整ETF事实包"
        - "沪深300ETF的最新行情+申赎+技术信号"
        - "查一下 159919 的规模+涨跌幅+RSI/MACD信号"

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
        """获取指数事实包(Fact Pack)：一次调用聚合全维度指数结构化事实数据。

        聚合 5 大事实类别: 指数主档、PE/PB估值与历史分位、行情表现、成分股、技术信号。
        返回统一结构: entity + facts + source_trace + coverage。

        Typical use cases:
        - "给我 000300 的完整指数事实包"
        - "沪深300的最新PE/PB估值+技术信号"
        - "查一下上证50的成分股+涨跌幅+MACD"

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
