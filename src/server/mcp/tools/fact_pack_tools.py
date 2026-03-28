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

        聚合 8 大事实类别: 证券主数据、财务、市场估值、公司治理、
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
