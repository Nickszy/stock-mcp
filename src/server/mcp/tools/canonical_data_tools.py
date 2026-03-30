# src/server/mcp/tools/canonical_data_tools.py
"""MCP tools for canonical-validated structured data access.

Canonical-first data bridge: when validated multi-source data exists in the
canonical store, return it with source attribution and quality metadata.
When canonical data is unavailable, fall back to live gateway data.

Tools:
  - get_canonical_financials: 查询已验证的财报数据(优先canonical)
  - get_canonical_market_data: 查询已验证的行情数据(优先canonical)
  - get_canonical_dataset_status: 查看结构化数据维度状态
"""

import json
import time
from typing import Any, Dict, Optional

from fastmcp import FastMCP, Context

from src.server.utils.logger import logger
from src.server.mcp.tools.artifact_utils import (
    ComponentType,
    create_standard_artifact_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_canonical_repo():
    """Lazily get the canonical repository from the structured_data route module."""
    try:
        from src.server.api.routes.structured_data import _get_canonical_repo as _get
        return _get()
    except Exception:
        return None


def _parse_symbol(symbol: str) -> tuple:
    """Parse EXCHANGE:SYMBOL into (exchange, ticker)."""
    parts = symbol.split(":")
    if len(parts) == 2:
        return parts[0], parts[1]
    # Heuristic for A-share numeric codes
    if symbol.isdigit() and len(symbol) == 6:
        exchange = "SSE" if symbol.startswith("6") else "SZSE"
        return exchange, symbol
    return "", symbol


def _format_source_attribution(
    source_type: str,
    version: Optional[int] = None,
    published_at: Optional[str] = None,
    provider: Optional[str] = None,
    confidence: Optional[float] = None,
) -> str:
    """Build a human-readable source attribution string."""
    if source_type == "canonical":
        parts = ["canonical(已验证)"]
        if version:
            parts.append(f"v{version}")
        if provider:
            parts.append(f"来源:{provider}")
        if confidence is not None:
            parts.append(f"置信度:{confidence:.0%}")
        return " | ".join(parts)
    return "live(实时查询)"


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

def register_canonical_data_tools(mcp: FastMCP):
    """Register canonical data MCP tools."""

    # ------------------------------------------------------------------
    # get_canonical_financials
    # ------------------------------------------------------------------
    @mcp.tool(tags={"canonical", "fundamental"})
    async def get_canonical_financials(
        symbol: str,
        limit: int = 8,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """查询A股已验证的财报数据(优先canonical多源交叉验证数据, 回退至实时查询).

        WHEN TO USE: 当AI需要最高质量的财报数据时使用, 数据经过多源交叉验证和置信度评分.
        典型触发: "获取600519的财报数据" "查贵州茅台最新财报" "要可信度最高的财务数据".
        CONCEPT: 优先查询canonical存储中的已验证财报, 包含来源归因(source attribution)、
        版本号(version)、发布时间(published_at). 如无canonical数据则回退至实时数据源.
        返回结构包含 source_type 字段标识数据来源(canonical/live).
        DIFFERENTIATION: 与get_financial_reports不同——后者直接查数据源无验证;
        本工具返回经过normalize→validate→cross-validate→publish管道处理的高质量数据,
        包含多源对比置信度和数据质量评分.
        next_recommended_tools: get_canonical_market_data, get_stock_fact_pack, get_financial_ratios
        """
        if ctx:
            await ctx.info(f"查询canonical财报: {symbol}")

        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_canonical_financials", symbol=symbol)

            exchange, ticker = _parse_symbol(symbol)
            source_type = "live"

            # Phase 1: Try canonical store
            canonical_repo = _get_canonical_repo()
            canonical_data = None

            if canonical_repo:
                try:
                    from src.server.domain.structured_data.canonical_reader import (
                        read_canonical_financial_statements,
                    )
                    canonical_data = await read_canonical_financial_statements(
                        dataset_key="financial_statements",
                        symbol=ticker,
                        exchange=exchange,
                        limit=limit,
                    )
                    if canonical_data:
                        source_type = "canonical"
                except Exception as e:
                    logger.warning(
                        "Canonical lookup failed, falling back to live",
                        symbol=symbol,
                        error=str(e),
                    )

            # Phase 2: Fallback to live gateway
            if not canonical_data:
                try:
                    from src.server.core.dependencies import Container
                    gateway = Container.market_gateway()
                    live_result = await gateway.get_financial_reports(symbol=symbol)

                    if live_result and isinstance(live_result, dict):
                        records = live_result.get("data", live_result)
                        if isinstance(records, list):
                            canonical_data = []
                            for rec in records[:limit]:
                                canonical_data.append({
                                    "report_period": rec.get("report_date", ""),
                                    "data": rec,
                                    "source_type": "live",
                                    "provider": rec.get("source", "gateway"),
                                })
                        elif isinstance(records, dict):
                            canonical_data = [{
                                "report_period": records.get("report_date", ""),
                                "data": records,
                                "source_type": "live",
                                "provider": "gateway",
                            }]
                except Exception as e:
                    logger.warning("Live gateway fallback failed", symbol=symbol, error=str(e))

            elapsed = time.perf_counter() - t0

            if not canonical_data:
                return create_standard_artifact_response(
                    summary=f"无财报数据: {symbol}",
                    component_type=ComponentType.TABLE,
                    name=f"财报数据: {symbol}",
                    data={"symbol": symbol, "records": [], "source_type": "none"},
                    source="canonical-bridge",
                    description=f"未找到 {symbol} 的财报数据",
                )

            # Build response
            records_count = len(canonical_data)
            attribution = _format_source_attribution(source_type)

            # Build markdown summary
            md = f"# 财报数据: {symbol}\n\n"
            md += f"**数据来源**: {attribution}\n"
            md += f"**报告期数**: {records_count}\n"
            md += f"**耗时**: {elapsed:.1f}s\n\n"

            for rec in canonical_data[:5]:
                period = rec.get("report_period", "unknown")
                data = rec.get("data", {})
                md += f"## {period}\n\n"
                # Show key financial metrics
                for key in ("revenue", "net_income", "eps", "total_assets", "total_liabilities"):
                    val = data.get(key)
                    if val is not None:
                        if isinstance(val, (int, float)) and val > 10000:
                            md += f"- **{key}**: {val:,.0f}\n"
                        else:
                            md += f"- **{key}**: {val}\n"
                st = rec.get("source_type", "live")
                md += f"- *来源: {st}*\n\n"

            summary = (
                f"财报数据: {symbol} | {records_count}期 | {attribution} "
                f"(耗时 {elapsed:.1f}s)"
            )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FINANCIAL_CHART,
                name=f"财报数据: {symbol}",
                data={
                    "symbol": symbol,
                    "records": canonical_data,
                    "source_type": source_type,
                    "record_count": records_count,
                    "elapsed_seconds": round(elapsed, 2),
                },
                source=source_type,
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_canonical_financials failed: {e}")
            return create_standard_artifact_response(
                summary=f"查询canonical财报失败: {e}",
                component_type=ComponentType.TABLE,
                name="财报错误",
                data={"error": str(e)},
                source="canonical-bridge",
                description=f"查询失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_canonical_market_data
    # ------------------------------------------------------------------
    @mcp.tool(tags={"canonical", "market"})
    async def get_canonical_market_data(
        symbol: str,
        limit: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """查询已验证的行情数据(优先canonical多源交叉验证数据, 回退至实时查询).

        WHEN TO USE: 当AI需要高质量日线行情数据时使用, 数据经过多源交叉验证.
        典型触发: "获取600519的历史行情" "查贵州茅台日线数据" "要可信行情数据".
        CONCEPT: 优先查询canonical存储中的已验证行情数据, 包含OHLCV、来源归因和版本号.
        如无canonical数据则回退至实时数据源.
        DIFFERENTIATION: 与get_kline_data不同——后者直接查数据源; 本工具返回经过
        多源对比验证的高质量行情, 适合需要数据准确性的量化分析场景.
        next_recommended_tools: get_canonical_financials, get_kline_data, get_stock_fact_pack
        """
        if ctx:
            await ctx.info(f"查询canonical行情: {symbol}")

        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_canonical_market_data", symbol=symbol)

            exchange, ticker = _parse_symbol(symbol)
            source_type = "live"

            # Phase 1: Try canonical store
            canonical_repo = _get_canonical_repo()
            canonical_data = None

            if canonical_repo:
                try:
                    records = await canonical_repo.find_by_symbol(
                        dataset_key="daily_market_data",
                        exchange=exchange,
                        symbol=ticker,
                        limit=limit,
                    )
                    if records:
                        source_type = "canonical"
                        canonical_data = []
                        for rec in records:
                            data = rec.get("data", {})
                            if isinstance(data, str):
                                try:
                                    data = json.loads(data)
                                except Exception:
                                    pass
                            bk = rec.get("business_key", "")
                            canonical_data.append({
                                "trade_date": data.get("trade_date", bk.split(":")[-1] if ":" in bk else ""),
                                "data": data,
                                "version": rec.get("version"),
                                "source_type": "canonical",
                                "published_at": str(rec.get("published_at", "")),
                                "provider": rec.get("source", ""),
                            })
                except Exception as e:
                    logger.warning("Canonical market data lookup failed", symbol=symbol, error=str(e))

            # Phase 2: Fallback to live gateway
            if not canonical_data:
                try:
                    from src.server.core.dependencies import Container
                    gateway = Container.market_gateway()
                    live_result = await gateway.get_historical_prices(
                        symbol=symbol, period="daily", limit=limit,
                    )
                    if live_result:
                        prices = live_result if isinstance(live_result, list) else live_result.get("data", [])
                        if isinstance(prices, list):
                            canonical_data = []
                            for p in prices:
                                canonical_data.append({
                                    "trade_date": p.get("date", p.get("trade_date", "")),
                                    "data": p,
                                    "source_type": "live",
                                    "provider": "gateway",
                                })
                except Exception as e:
                    logger.warning("Live gateway fallback failed", symbol=symbol, error=str(e))

            elapsed = time.perf_counter() - t0

            if not canonical_data:
                return create_standard_artifact_response(
                    summary=f"无行情数据: {symbol}",
                    component_type=ComponentType.TABLE,
                    name=f"行情数据: {symbol}",
                    data={"symbol": symbol, "records": [], "source_type": "none"},
                    source="canonical-bridge",
                    description=f"未找到 {symbol} 的行情数据",
                )

            records_count = len(canonical_data)
            attribution = _format_source_attribution(source_type)

            # Build markdown
            md = f"# 行情数据: {symbol}\n\n"
            md += f"**数据来源**: {attribution}\n"
            md += f"**记录数**: {records_count} | **耗时**: {elapsed:.1f}s\n\n"
            md += "| 日期 | 开盘 | 最高 | 最低 | 收盘 | 成交量 |\n"
            md += "|------|------|------|------|------|--------|\n"
            for rec in canonical_data[:20]:
                data = rec.get("data", {})
                date = rec.get("trade_date", "")
                o = data.get("open", data.get("open_price", "-"))
                h = data.get("high", data.get("high_price", "-"))
                l = data.get("low", data.get("low_price", "-"))
                c = data.get("close", data.get("close_price", "-"))
                v = data.get("volume", "-")
                md += f"| {date} | {o} | {h} | {l} | {c} | {v} |\n"

            summary = (
                f"行情数据: {symbol} | {records_count}条 | {attribution} "
                f"(耗时 {elapsed:.1f}s)"
            )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.FINANCIAL_CHART,
                name=f"行情数据: {symbol}",
                data={
                    "symbol": symbol,
                    "records": canonical_data,
                    "source_type": source_type,
                    "record_count": records_count,
                    "elapsed_seconds": round(elapsed, 2),
                },
                source=source_type,
                description=summary,
                markdown=md,
                symbol=symbol,
            )

        except Exception as e:
            logger.error(f"get_canonical_market_data failed: {e}")
            return create_standard_artifact_response(
                summary=f"查询canonical行情失败: {e}",
                component_type=ComponentType.TABLE,
                name="行情错误",
                data={"error": str(e)},
                source="canonical-bridge",
                description=f"查询失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_canonical_dataset_status
    # ------------------------------------------------------------------
    @mcp.tool(tags={"canonical", "metadata"})
    async def get_canonical_dataset_status(
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """查看结构化数据中台各维度的数据状态与质量.

        WHEN TO USE: 当AI需要了解数据中台有哪些高质量数据维度可用时使用.
        典型触发: "有哪些已验证的数据" "数据中台状态" "查看数据维度".
        CONCEPT: 返回7个结构化数据维度的状态——financial_statements, company_profile,
        dividend, shareholder, corporate_actions, index_constituents, daily_market_data.
        每个维度显示canonical记录数、最近更新时间、数据源覆盖等.
        DIFFERENTIATION: 唯一的数据中台元数据查询工具, 帮助AI判断哪些维度有
        高质量canonical数据可用, 从而选择最优的数据查询策略.
        next_recommended_tools: get_canonical_financials, get_canonical_market_data
        """
        if ctx:
            await ctx.info("查询数据中台状态")

        try:
            from src.server.domain.structured_data.registry import build_default_registry

            registry = build_default_registry()
            datasets = []
            for config in registry.list_all():
                ds_info = {
                    "dataset_key": config.dataset_key,
                    "display_name": config.display_name,
                    "description": config.description,
                    "sources": [s.source_name for s in config.sorted_sources],
                    "ttl_soft_hours": config.ttl.soft_ttl_hours,
                    "ttl_hard_hours": config.ttl.hard_ttl_hours,
                    "auto_publish_threshold": config.auto_publish_threshold,
                    "is_active": config.is_active,
                    "cron": config.cron_schedule,
                }
                datasets.append(ds_info)

            md = "# 结构化数据中台状态\n\n"
            md += f"**数据维度**: {len(datasets)}个\n\n"
            md += "| 维度 | 显示名 | 数据源 | TTL(小时) | 自动发布阈值 |\n"
            md += "|------|--------|--------|-----------|-------------|\n"
            for ds in datasets:
                sources = ", ".join(ds["sources"][:3])
                md += (
                    f"| {ds['dataset_key']} | {ds['display_name']} | {sources} "
                    f"| {ds['ttl_soft_hours']}h "
                    f"| {ds['auto_publish_threshold']} |\n"
                )

            summary = f"数据中台: {len(datasets)}个维度就绪"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name="数据中台状态",
                data={"datasets": datasets, "total": len(datasets)},
                source="canonical-bridge",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_canonical_dataset_status failed: {e}")
            return create_standard_artifact_response(
                summary=f"查询数据中台状态失败: {e}",
                component_type=ComponentType.TABLE,
                name="数据中台错误",
                data={"error": str(e)},
                source="canonical-bridge",
                description=f"查询失败: {e}",
            )
