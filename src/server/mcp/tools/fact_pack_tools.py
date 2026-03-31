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
        """A股股票事实包(一次调用聚合公司全维度结构化事实数据).

        WHEN TO USE: 用户要快速获得单只A股的完整事实底稿时调用, 适合作为股票研究入口工具.
        典型触发: "给我600519的完整资料" "这家公司全貌" "先拉一个fact pack".
        CONCEPT: 聚合证券主数据/财务/估值/公司治理/分红回购解禁/主营构成/公司主档/同行等多类事实,
        返回统一结构 entity + facts + source_trace + coverage, 方便后续分析链路复用.
        DIFFERENTIATION: 这是A股公司级综合聚合工具; 与get_market_fact_pack不同(后者偏交易与行情维度),
        与get_us_stock_fact_pack不同(后者面向美股), 与单一基本面工具不同(本工具一次拉全维度).
        next_recommended_tools: get_market_fact_pack, get_sector_fact_pack, get_us_stock_fact_pack
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
        """基金事实包(一次调用聚合基金全维度结构化事实数据).

        WHEN TO USE: 用户要快速了解公募基金全貌时调用, 是基金研究的入口工具.
        典型触发: "给我110011的完整资料" "这只基金怎么样" "基金fact pack".
        CONCEPT: 聚合基金主档/净值与收益/持仓/基金经理/规模份额/资产配置/费率分红/同类对比等维度,
        形成统一基金事实底稿, 便于后续比较和配置分析.
        DIFFERENTIATION: 这是开放式基金综合聚合工具; 与get_etf_fact_pack不同(ETF更偏交易与技术信号),
        与get_stock_fact_pack不同(股票而非基金), 与单一基金明细工具不同(本工具一次返回多维事实).
        next_recommended_tools: get_etf_fact_pack, get_index_fact_pack, get_stock_fact_pack
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
        """A股行情事实包(聚合交易维度全量结构化事实数据).

        WHEN TO USE: 用户要快速了解单只A股的交易面/技术面全貌时调用.
        典型触发: "这只票行情怎么样" "交易面fact pack" "盘前分析需要行情数据".
        CONCEPT: 聚合行情相关维度: 估值快照/技术面快照/K线因子/资金流向/市场广度/行业指数/衍生指标/相对强度/北向资金/融资融券,
        返回交易导向的结构化事实, 适合盘前分析和交易决策辅助.
        DIFFERENTIATION: 本工具偏交易与行情维度; 与get_stock_fact_pack不同(公司基本面为主),
        与单一技术指标工具不同(本工具聚合多维行情数据), 与get_sector_fact_pack不同(个股vs行业).
        next_recommended_tools: get_stock_fact_pack, get_sector_fact_pack
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
        """美股股票事实包(一次调用聚合美股公司全维度结构化事实数据).

        WHEN TO USE: 用户要快速获取单只美股的完整研究底稿时调用, 是美股公司研究入口工具.
        典型触发: "给我AAPL的完整资料" "特斯拉全貌" "先拉一个美股fact pack".
        CONCEPT: 聚合公司画像/估值/财务健康/机构持仓与内幕交易/分析师评级与收入结构/量价技术面等维度,
        形成可直接复用的美股结构化事实底稿.
        DIFFERENTIATION: 这是美股公司级综合聚合工具; 与get_stock_fact_pack不同(后者面向A股),
        与get_market_fact_pack不同(后者偏交易行情), 与单一美股基本面工具不同(本工具一次拉全维度).
        next_recommended_tools: get_stock_fact_pack, get_market_fact_pack
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
        """ETF事实包(聚合ETF全维度结构化事实数据).

        WHEN TO USE: 用户研究ETF产品或做资产配置时调用, 适合作为ETF研究入口工具.
        典型触发: "给我510300的完整资料" "这只ETF怎么样" "ETF fact pack".
        CONCEPT: 聚合ETF主档/实时行情/历史表现/资金申赎或资金流/技术信号等维度,
        帮助判断ETF的产品属性、交易活跃度和跟踪表现.
        DIFFERENTIATION: 本工具面向ETF; 与get_fund_fact_pack不同(公募基金更偏持仓经理费率),
        与get_index_fact_pack不同(指数本身而非跟踪基金), 与单一ETF详情工具不同(本工具一次聚合多维事实).
        next_recommended_tools: get_index_fact_pack, get_fund_fact_pack, get_stock_fact_pack
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
        """指数事实包(聚合指数全维度结构化事实数据).

        WHEN TO USE: 用户做指数层面的研究/择时/估值判断时调用.
        典型触发: "沪深300现在贵不贵" "上证指数全貌" "创业板指估值和技术面".
        CONCEPT: 聚合指数主档/PE-PB估值及历史分位/价格表现/成分股/技术信号等维度,
        形成指数研究底稿, 常用于大盘择时和宽基比较.
        DIFFERENTIATION: 本工具研究的是指数本体; 与get_etf_fact_pack不同(ETF是跟踪该指数的基金),
        与get_stock_fact_pack不同(个股vs指数), 与单一估值工具不同(本工具还包含成分和技术维度).
        next_recommended_tools: get_etf_fact_pack, get_sector_fact_pack, get_market_fact_pack
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
        """行业事实包(聚合行业全维度结构化事实数据).

        WHEN TO USE: 用户做行业/板块研究时调用, 适合作为行业研究的入口工具.
        典型触发: "白酒行业全貌" "半导体板块怎么样" "给我一个行业fact pack".
        CONCEPT: 聚合行业定位/成分股/结构快照/同业对比/证据摘要等维度,
        帮助快速建立对行业基本结构、估值位置和资金信号的整体认知.
        DIFFERENTIATION: 本工具是行业级深度聚合; 与get_stock_fact_pack不同(行业vs个股),
        与get_industry_ranking不同(后者是实时横向排名, 本工具是单行业纵向研究),
        与sector_research_tools中的单一工具不同(本工具把多个行业维度聚合在一起).
        next_recommended_tools: get_stock_fact_pack, get_market_fact_pack
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
