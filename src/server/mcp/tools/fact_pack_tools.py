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

        聚合 9 大事实类别: 证券主数据、财务、市场估值(含融资融券)、公司治理、
        事件(分红/回购/解禁)、业务结构(主营构成)、公司主档、同行。
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

            # Build structured Markdown fact view
            md = f"# 股票事实包: {name}({symbol})\n\n"
            md += f"**已获取**: {categories_fetched}/{categories_total} 类"
            md += f" | **耗时**: {elapsed:.1f}s\n\n"

            # Coverage summary
            if coverage:
                complete = sum(1 for v in coverage.values() if v == "complete")
                partial = sum(1 for v in coverage.values() if v == "partial")
                md += f"**覆盖率**: {complete}完整 + {partial}部分 / {categories_total}类\n\n"

            facts = result.get("facts", {})

            # Security master
            sec = facts.get("security_master", {})
            if sec:
                md += "## 证券主数据\n\n"
                for k, v in sec.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Financial
            fin = facts.get("financial", {})
            if fin:
                md += "## 财务数据\n\n"
                if isinstance(fin, dict):
                    for k, v in fin.items():
                        md += f"- **{k}**: {v}\n"
                else:
                    md += f"{fin}\n"
                md += "\n"

            # Market / Valuation
            mkt = facts.get("market", {})
            if mkt:
                md += "## 市场估值\n\n"
                for k, v in mkt.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Governance
            gov = facts.get("governance", {})
            if gov:
                md += "## 公司治理\n\n"
                top10 = gov.get("top10_shareholders", [])
                if top10:
                    md += "### 前十大流通股东\n\n"
                    md += "| 股东名称 | 持股数量 | 持股比例 |\n"
                    md += "|---------|---------|----------|\n"
                    for s in top10[:10]:
                        if isinstance(s, dict):
                            md += (
                                f"| {s.get('holder_name', '')} "
                                f"| {s.get('hold_qty', '-')} "
                                f"| {s.get('hold_ratio', '-')} |\n"
                            )
                        else:
                            md += f"| {s} |\n"
                    md += "\n"
                changes = gov.get("shareholder_changes", {})
                if changes:
                    md += f"### 股东户数变化\n\n{changes}\n\n"

            # Events
            evt = facts.get("events", {})
            if evt:
                md += "## 事件\n\n"
                div = evt.get("dividends", {})
                if div:
                    md += "### 分红\n\n"
                    if isinstance(div, list):
                        for d in div[:5]:
                            md += f"- {d}\n"
                    else:
                        md += f"{div}\n"
                    md += "\n"
                rep = evt.get("repurchase", {})
                if rep:
                    md += f"### 回购\n\n{rep}\n\n"
                rst = evt.get("restricted_release", {})
                if rst:
                    md += f"### 解禁\n\n{rst}\n\n"

            # Business structure
            biz = facts.get("business_structure", {})
            if biz:
                md += "## 业务结构(主营构成)\n\n"
                if isinstance(biz, list):
                    for b in biz[:10]:
                        md += f"- {b}\n"
                else:
                    md += f"{biz}\n"
                md += "\n"

            # Source trace (dict: category → {provider, error?})
            trace = result.get("source_trace", {})
            if trace:
                md += "## 数据溯源\n\n"
                md += "| 类别 | 详情 |\n"
                md += "|------|------|\n"
                for cat, info in trace.items():
                    md += f"| {cat} | {info} |\n"
                md += "\n"

            if missing:
                md += f"## 缺失字段\n\n> {', '.join(missing)}\n"

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

            # Build structured Markdown fact view
            md = f"# 基金事实包: {name}({fund_code})\n\n"
            md += f"**已获取**: {categories_fetched}/{categories_total} 类"
            md += f" | **耗时**: {elapsed:.1f}s\n\n"

            if coverage:
                complete = sum(1 for v in coverage.values() if v == "complete")
                partial = sum(1 for v in coverage.values() if v == "partial")
                md += f"**覆盖率**: {complete}完整 + {partial}部分 / {categories_total}类\n\n"

            facts = result.get("facts", {})

            # Master
            mst = facts.get("master", {})
            if mst:
                md += "## 基金主档\n\n"
                for k, v in mst.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # NAV & Performance
            nav_facts = facts.get("nav", {})
            if nav_facts:
                md += "## 净值与收益\n\n"
                for k, v in nav_facts.items():
                    if isinstance(v, (dict, list)):
                        md += f"- **{k}**: {v}\n"
                    else:
                        md += f"- **{k}**: {v}\n"
                md += "\n"

            # Holdings
            hld = facts.get("holdings", {})
            if hld:
                md += "## 持仓穿透\n\n"
                hld_data = hld.get("data", [])
                if hld_data:
                    md += f"**重仓股数**: {hld.get('total', 0)}\n\n"
                    md += "| 股票代码 | 股票名称 | 持仓占比 |\n"
                    md += "|---------|---------|----------|\n"
                    for s in hld_data[:10]:
                        if isinstance(s, dict):
                            md += (
                                f"| {s.get('股票代码', '')} "
                                f"| {s.get('股票名称', '')} "
                                f"| {s.get('占净值比例', '-')} |\n"
                            )
                        else:
                            md += f"| {s} |\n"
                md += "\n"

            # Manager
            mgr = facts.get("manager", [])
            if mgr:
                md += "## 基金经理\n\n"
                for m in mgr[:5]:
                    if isinstance(m, dict):
                        md += f"- {m.get('姓名', m.get('基金经理', ''))}"
                        md += f" (任职: {m.get('任职日期', '-')})"
                        md += f" 管理规模: {m.get('管理规模', '-')}\n"
                    else:
                        md += f"- {m}\n"
                md += "\n"

            # Scale
            scl = facts.get("scale", {})
            if scl:
                md += "## 规模份额\n\n"
                for k, v in scl.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Allocation
            alloc = facts.get("allocation", {})
            if alloc:
                md += "## 资产配置\n\n"
                if isinstance(alloc, list):
                    for a in alloc[:10]:
                        md += f"- {a}\n"
                else:
                    md += f"{alloc}\n"
                md += "\n"

            # Source trace
            trace = result.get("source_trace", {})
            if trace:
                md += "## 数据溯源\n\n"
                md += "| 类别 | 详情 |\n"
                md += "|------|------|\n"
                for cat, info in trace.items():
                    md += f"| {cat} | {info} |\n"
                md += "\n"

            if missing:
                md += f"## 缺失字段\n\n> {', '.join(missing)}\n"

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

            md = f"# 行情事实包: {symbol}\n\n"
            md += f"**已获取**: {categories_fetched}/{categories_total} 类"
            md += f" | **耗时**: {elapsed:.1f}s\n\n"

            if coverage:
                complete = sum(1 for v in coverage.values() if v == "complete")
                partial = sum(1 for v in coverage.values() if v == "partial")
                md += f"**覆盖率**: {complete}完整 + {partial}部分 / {categories_total}类\n\n"

            facts = result.get("facts", {})

            # Master (valuation)
            mst = facts.get("master", {})
            if mst:
                md += "## 估值指标\n\n"
                for k, v in mst.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Snapshot (technical)
            snap = facts.get("snapshot", {})
            if snap:
                md += "## 技术快照\n\n"
                for k, v in snap.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Kline
            kl = facts.get("kline", {})
            if kl:
                md += "## K线因子\n\n"
                fac = kl.get("factors", {})
                if isinstance(fac, dict):
                    for k, v in fac.items():
                        md += f"- **{k}**: {v}\n"
                else:
                    md += f"{fac}\n"
                md += "\n"

            # Money Flow
            mf = facts.get("money_flow", {})
            if mf:
                md += "## 资金流\n\n"
                if isinstance(mf, dict):
                    for k, v in mf.items():
                        if isinstance(v, list) and v:
                            md += f"- **{k}**: {len(v)}条记录\n"
                        else:
                            md += f"- **{k}**: {v}\n"
                else:
                    md += f"{mf}\n"
                md += "\n"

            # Breadth
            br = facts.get("breadth", {})
            if br:
                md += "## 市场广度\n\n"
                for k, v in br.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Index/Sector
            idx = facts.get("index", {})
            if idx:
                md += "## 指数/板块行情\n\n"
                for k, v in idx.items():
                    if isinstance(v, list) and v:
                        md += f"- **{k}**: {len(v)}条记录\n"
                    else:
                        md += f"- **{k}**: {v}\n"
                md += "\n"

            # Derivative
            drv = facts.get("derivative", {})
            if drv:
                md += "## 衍生行情\n\n"
                for k, v in drv.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Relative
            rs = facts.get("relative", {})
            if rs:
                md += "## 相对强弱\n\n"
                for k, v in rs.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # North Bound
            nb = facts.get("north_bound", {})
            if nb:
                md += "## 北向资金\n\n"
                inflow = nb.get("latest_net_inflow")
                date_val = nb.get("latest_date")
                if inflow is not None:
                    md += f"- **最新净买入**: {inflow}\n"
                if date_val:
                    md += f"- **日期**: {date_val}\n"
                trend = nb.get("trend", [])
                if trend:
                    md += "\n### 近期趋势\n\n"
                    for t in trend[-5:]:
                        if isinstance(t, dict):
                            md += f"- {t.get('date', t.get('日期', ''))}: 净买入 {t.get('north_net_inflow', t.get('净买入', '-'))}\n"
                    md += "\n"

            # Margin
            mg = facts.get("margin", {})
            if mg:
                md += "## 融资融券\n\n"
                summary_mg = mg.get("summary", {})
                if summary_mg:
                    mb = summary_mg.get("latest_margin_balance")
                    sb = summary_mg.get("latest_short_balance")
                    if mb is not None:
                        md += f"- **融资余额**: {mb}\n"
                    if sb is not None:
                        md += f"- **融券余额**: {sb}\n"
                exchange = mg.get("exchange", "")
                if exchange:
                    md += f"- **交易所**: {exchange}\n"
                md += "\n"

            # Source trace
            trace = result.get("source_trace", {})
            if trace:
                md += "## 数据溯源\n\n"
                md += "| 类别 | 详情 |\n"
                md += "|------|------|\n"
                for cat, info in trace.items():
                    md += f"| {cat} | {info} |\n"
                md += "\n"

            if missing:
                md += f"## 缺失字段\n\n> {', '.join(missing)}\n"

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

            # Build structured Markdown fact view
            md = f"# 美股事实包: {name}({ticker})\n\n"
            md += f"**已获取**: {categories_fetched}/{categories_total} 类"
            md += f" | **耗时**: {elapsed:.1f}s\n\n"

            if coverage:
                complete = sum(1 for v in coverage.values() if v == "complete")
                partial = sum(1 for v in coverage.values() if v == "partial")
                md += f"**覆盖率**: {complete}完整 + {partial}部分 / {categories_total}类\n\n"

            # Profile
            if profile:
                md += "## 公司档案\n\n"
                for k, v in profile.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Valuation
            val = facts.get("valuation", {})
            if val:
                md += "## 估值指标\n\n"
                for k, v in val.items():
                    if isinstance(v, dict):
                        md += f"- **{k}**:\n"
                        for sk, sv in v.items():
                            md += f"  - {sk}: {sv}\n"
                    else:
                        md += f"- **{k}**: {v}\n"
                md += "\n"

            # Financials
            fin = facts.get("financials", {})
            if fin:
                md += "## 财务健康\n\n"
                for k, v in fin.items():
                    if isinstance(v, dict):
                        md += f"- **{k}**:\n"
                        for sk, sv in v.items():
                            md += f"  - {sk}: {sv}\n"
                    elif isinstance(v, list):
                        md += f"- **{k}**: {len(v)}条记录\n"
                    else:
                        md += f"- **{k}**: {v}\n"
                md += "\n"

            # Ownership
            own = facts.get("ownership", {})
            if own:
                md += "## 机构持仓与内部人\n\n"
                inst = own.get("institutional_holders", [])
                if inst:
                    md += f"### 机构持仓前{min(len(inst), 10)}名\n\n"
                    md += "| 机构 | 持仓市值 | 比例 |\n"
                    md += "|------|---------|------|\n"
                    for h in inst[:10]:
                        if isinstance(h, dict):
                            md += (
                                f"| {h.get('holder', '')} "
                                f"| {h.get('value', '-')} "
                                f"| {h.get('pct_held', '-')} |\n"
                            )
                    md += "\n"
                insider = own.get("insider_trades", [])
                if insider:
                    md += f"### 内部人交易 (最近{min(len(insider), 5)}笔)\n\n"
                    for t in insider[:5]:
                        if isinstance(t, dict):
                            md += (
                                f"- {t.get('insider', '')} "
                                f"{t.get('transaction', '')} "
                                f"{t.get('shares', '-')}股\n"
                            )
                    md += "\n"
                for k, v in own.items():
                    if k not in ("institutional_holders", "insider_trades"):
                        md += f"- **{k}**: {v}\n"
                md += "\n"

            # Analyst
            ana = facts.get("analyst", {})
            if ana:
                md += "## 分析师与收入\n\n"
                for k, v in ana.items():
                    if isinstance(v, dict):
                        md += f"- **{k}**:\n"
                        for sk, sv in v.items():
                            md += f"  - {sk}: {sv}\n"
                    elif isinstance(v, list):
                        md += f"- **{k}**: {len(v)}条记录\n"
                    else:
                        md += f"- **{k}**: {v}\n"
                md += "\n"

            # Technical
            tech = facts.get("technical", {})
            if tech:
                md += "## 量价技术\n\n"
                for k, v in tech.items():
                    if isinstance(v, dict):
                        md += f"- **{k}**:\n"
                        for sk, sv in v.items():
                            md += f"  - {sk}: {sv}\n"
                    elif isinstance(v, list):
                        md += f"- **{k}**: {len(v)}条记录\n"
                    else:
                        md += f"- **{k}**: {v}\n"
                md += "\n"

            # Source trace
            trace = result.get("source_trace", {})
            if trace:
                md += "## 数据溯源\n\n"
                md += "| 类别 | 详情 |\n"
                md += "|------|------|\n"
                for cat, info in trace.items():
                    md += f"| {cat} | {info} |\n"
                md += "\n"

            if missing:
                md += f"## 缺失类别\n\n> {', '.join(missing)}\n"

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

            # Build structured Markdown fact view
            md = f"# ETF事实包: {name}({symbol})\n\n"
            md += f"**已获取**: {categories_fetched}/{categories_total} 类"
            md += f" | **耗时**: {elapsed:.1f}s\n\n"

            if coverage:
                complete = sum(1 for v in coverage.values() if v == "complete")
                partial = sum(1 for v in coverage.values() if v == "partial")
                md += f"**覆盖率**: {complete}完整 + {partial}部分 / {categories_total}类\n\n"

            # Master
            if master:
                md += "## ETF主档\n\n"
                for k, v in master.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Realtime
            if rt:
                md += "## 实时行情\n\n"
                for k, v in rt.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Performance
            perf = facts.get("performance", {})
            if perf:
                md += "## 历史表现\n\n"
                for k, v in perf.items():
                    if k == "history":
                        md += f"- **近10日行情**: {len(v)}条\n"
                    else:
                        md += f"- **{k}**: {v}\n"
                md += "\n"

            # Flow
            flow = facts.get("flow", {})
            if flow:
                md += "## 资金流/申赎\n\n"
                if isinstance(flow, dict):
                    for k, v in flow.items():
                        md += f"- **{k}**: {v}\n"
                elif isinstance(flow, list):
                    for item in flow[:5]:
                        md += f"- {item}\n"
                md += "\n"

            # Technical
            tech = facts.get("technical", {})
            if tech:
                md += "## 技术信号\n\n"
                signals = tech.get("signals", {})
                if signals:
                    for indicator, signal in signals.items():
                        md += f"- **{indicator}**: {signal}\n"
                md += f"- **RSI(14)**: {tech.get('rsi14', '-')}\n"
                md += f"- **MACD DIF**: {tech.get('macd_dif', '-')}\n"
                md += f"- **MACD DEA**: {tech.get('macd_dea', '-')}\n"
                md += f"- **BOLL上轨**: {tech.get('boll_upper', '-')}\n"
                md += f"- **BOLL下轨**: {tech.get('boll_lower', '-')}\n"
                md += "\n"

            # Source trace
            trace = result.get("source_trace", {})
            if trace:
                md += "## 数据溯源\n\n"
                md += "| 类别 | 详情 |\n"
                md += "|------|------|\n"
                for cat, info in trace.items():
                    md += f"| {cat} | {info} |\n"
                md += "\n"

            if missing:
                md += f"## 缺失类别\n\n> {', '.join(missing)}\n"

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

            # Build structured Markdown fact view
            md = f"# 指数事实包: {name}({symbol})\n\n"
            md += f"**已获取**: {categories_fetched}/{categories_total} 类"
            md += f" | **耗时**: {elapsed:.1f}s\n\n"

            if coverage:
                complete = sum(1 for v in coverage.values() if v == "complete")
                partial = sum(1 for v in coverage.values() if v == "partial")
                md += f"**覆盖率**: {complete}完整 + {partial}部分 / {categories_total}类\n\n"

            # Master
            if master:
                md += "## 指数主档\n\n"
                for k, v in master.items():
                    md += f"- **{k}**: {v}\n"
                md += "\n"

            # Valuation
            val = facts.get("valuation", {})
            if val:
                md += "## PE/PB估值\n\n"
                md += f"- **最新日期**: {val.get('latest_date', '-')}\n"
                md += f"- **PE**: {val.get('pe', '-')}\n"
                md += f"- **PB**: {val.get('pb', '-')}\n"
                md += f"- **PE历史分位**: {val.get('pe_percentile', '-')}%\n"
                md += f"- **PB历史分位**: {val.get('pb_percentile', '-')}%\n"
                md += f"- **数据点数**: {val.get('data_points', 0)}\n"
                md += "\n"

            # Performance
            perf = facts.get("performance", {})
            if perf:
                md += "## 行情表现\n\n"
                md += f"- **最新日期**: {perf.get('latest_date', '-')}\n"
                md += f"- **最新收盘**: {perf.get('latest_close', '-')}\n"
                md += f"- **日涨跌幅**: {perf.get('change_pct_1d', '-')}%\n"
                md += f"- **5日涨跌幅**: {perf.get('change_pct_5d', '-')}%\n"
                md += f"- **20日涨跌幅**: {perf.get('change_pct_20d', '-')}%\n"
                md += f"- **数据点数**: {perf.get('data_points', 0)}\n"
                md += "\n"

            # Constituents
            cons = facts.get("constituents", {})
            if cons:
                md += f"## 成分股 (共{cons.get('total', 0)}只)\n\n"
                top10 = cons.get("top10", [])
                if top10:
                    md += "| 股票代码 | 股票名称 |\n"
                    md += "|---------|--------|\n"
                    for c in top10[:10]:
                        if isinstance(c, dict):
                            code = c.get("index_code", c.get("constituent_code", ""))
                            cname = c.get("index_name", c.get("constituent_name", ""))
                            md += f"| {code} | {cname} |\n"
                md += "\n"

            # Technical
            tech = facts.get("technical", {})
            if tech:
                md += "## 技术信号\n\n"
                signals = tech.get("signals", {})
                if signals:
                    for indicator, signal in signals.items():
                        md += f"- **{indicator}**: {signal}\n"
                md += f"- **RSI(14)**: {tech.get('rsi14', '-')}\n"
                md += f"- **MACD DIF**: {tech.get('macd_dif', '-')}\n"
                md += f"- **MACD DEA**: {tech.get('macd_dea', '-')}\n"
                md += f"- **BOLL上轨**: {tech.get('boll_upper', '-')}\n"
                md += f"- **BOLL下轨**: {tech.get('boll_lower', '-')}\n"
                md += "\n"

            # Source trace
            trace = result.get("source_trace", {})
            if trace:
                md += "## 数据溯源\n\n"
                md += "| 类别 | 详情 |\n"
                md += "|------|------|\n"
                for cat, info in trace.items():
                    md += f"| {cat} | {info} |\n"
                md += "\n"

            if missing:
                md += f"## 缺失类别\n\n> {', '.join(missing)}\n"

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
