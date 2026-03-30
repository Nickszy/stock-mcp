# src/server/mcp/tools/entity_tools.py
"""MCP tools for entity registry knowledge graph access.

Exposes the entity registry's resolution, peer discovery, classification,
and relationship capabilities to AI agents via MCP.

Tools:
  - resolve_entity: 实体解析(模糊匹配)
  - get_entity_detail: 实体详情(含分类/关系/事件)
  - get_entity_peers: 同行业实体发现
  - search_entities: 实体搜索
"""

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

def _get_entity_service():
    """Lazily get the EntityRegistryService."""
    try:
        from src.server.api.routes.entity_registry import _service
        return _service
    except Exception:
        return None


def _get_entity_repo():
    """Lazily get the EntityRegistryRepository."""
    try:
        from src.server.api.routes.entity_registry import _repo
        return _repo
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Tool Registration
# ---------------------------------------------------------------------------

def register_entity_tools(mcp: FastMCP):
    """Register entity registry MCP tools."""

    # ------------------------------------------------------------------
    # resolve_entity
    # ------------------------------------------------------------------
    @mcp.tool(tags={"entity", "fundamental"})
    async def resolve_entity(
        query: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """解析实体: 通过股票代码、名称、asset_id查找实体(模糊匹配).

        WHEN TO USE: 当AI需要将模糊引用(如"茅台"、"600519"、"贵州茅台")解析为
        标准化实体时使用. 返回完整实体信息包括交易所、分类、关联实体等.
        典型触发: "茅台是哪个交易所的" "600519的公司信息" "平安银行对应的实体".
        CONCEPT: 统一实体解析入口——支持ticker(EXCHANGE:SYMBOL)、中文名称、
        asset_id三种查询方式, 自动通过security_master + entity_registry联合解析.
        返回profile + classifications + relations + snapshot全量数据.
        DIFFERENTIATION: 与get_asset_info不同——后者只返回基础行情信息;
        本工具返回完整的实体知识图谱数据, 包含行业分类(申万/中信/GICS)、
        企业关系(母子公司/交叉上市/供应链)、公司事件等.
        next_recommended_tools: get_entity_detail, get_entity_peers, search_entities
        """
        if ctx:
            await ctx.info(f"解析实体: {query}")

        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: resolve_entity", query=query)

            service = _get_entity_service()
            if not service:
                return create_standard_artifact_response(
                    summary="实体注册表未初始化(需要PostgreSQL)",
                    component_type=ComponentType.TABLE,
                    name="实体解析",
                    data={"error": "Entity registry not initialized", "query": query},
                    source="entity-registry",
                    description="实体注册表需要PostgreSQL连接",
                )

            # Determine query type
            ticker = None
            name = None
            asset_id = None

            if query.count(":") == 1 and len(query.split(":")) == 2:
                # Looks like EXCHANGE:SYMBOL
                ticker = query
            elif len(query) == 36 and "-" in query:
                # Looks like UUID
                asset_id = query
            else:
                # Treat as name
                name = query

            result = await service.resolve_entity(
                ticker=ticker, name=name, asset_id=asset_id,
            )

            elapsed = time.perf_counter() - t0

            if not result:
                return create_standard_artifact_response(
                    summary=f"未找到实体: {query}",
                    component_type=ComponentType.TABLE,
                    name="实体解析",
                    data={"query": query, "found": False},
                    source="entity-registry",
                    description=f"无法解析: {query}",
                )

            # Build markdown summary
            profile = result.get("profile", {})
            classifications = result.get("classifications", [])
            relations = result.get("relations", [])

            name_zh = profile.get("name_zh", query)
            md = f"# 实体: {name_zh}\n\n"
            md += f"**查询**: `{query}` | **耗时**: {elapsed:.1f}s\n\n"

            if profile:
                md += "## 基础信息\n\n"
                for key, label in [
                    ("asset_id", "资产ID"),
                    ("status", "状态"),
                    ("name_en", "英文名"),
                    ("isin", "ISIN"),
                    ("listing_date", "上市日期"),
                ]:
                    val = profile.get(key)
                    if val:
                        md += f"- **{label}**: {val}\n"
                md += "\n"

            if classifications:
                md += "## 行业分类\n\n"
                for c in classifications[:5]:
                    scheme = c.get("scheme", "")
                    cname = c.get("name", "")
                    code = c.get("code", "")
                    md += f"- **{scheme}**: {cname} ({code})\n"
                md += "\n"

            if relations:
                md += f"## 关联实体 ({len(relations)}个)\n\n"
                for r in relations[:5]:
                    rtype = r.get("relation_type", "")
                    md += f"- {rtype}\n"

            summary = (
                f"实体解析: {name_zh} | 分类:{len(classifications)} "
                f"关系:{len(relations)} (耗时 {elapsed:.1f}s)"
            )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"实体: {name_zh}",
                data=result,
                source="entity-registry",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"resolve_entity failed: {e}")
            return create_standard_artifact_response(
                summary=f"实体解析失败: {e}",
                component_type=ComponentType.TABLE,
                name="实体错误",
                data={"error": str(e), "query": query},
                source="entity-registry",
                description=f"解析失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_entity_detail
    # ------------------------------------------------------------------
    @mcp.tool(tags={"entity", "fundamental"})
    async def get_entity_detail(
        asset_id: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取实体完整详情: 档案+分类+关系+事件+快照.

        WHEN TO USE: 当AI需要了解一个实体的全景信息时使用, 返回完整的知识图谱数据.
        典型触发: "查这个公司的详细信息" "实体的所有分类和关系" "获取asset_id=xxx的详情".
        CONCEPT: 返回entity_profile + classifications + relations + events + market_snapshot
        五类聚合数据, 构成实体的完整知识图谱.
        DIFFERENTIATION: 与resolve_entity不同——本工具需要精确的asset_id而非模糊查询;
        返回更丰富的数据(events/snapshots). 与get_stock_fact_pack不同——后者是行情聚合,
        本工具是实体知识图谱.
        next_recommended_tools: resolve_entity, get_entity_peers, get_stock_fact_pack
        """
        if ctx:
            await ctx.info(f"获取实体详情: {asset_id}")

        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_entity_detail", asset_id=asset_id)

            repo = _get_entity_repo()
            if not repo:
                return create_standard_artifact_response(
                    summary="实体注册表未初始化",
                    component_type=ComponentType.TABLE,
                    name="实体详情",
                    data={"error": "Entity registry not initialized"},
                    source="entity-registry",
                    description="需要PostgreSQL连接",
                )

            detail = await repo.get_entity_detail(asset_id)
            elapsed = time.perf_counter() - t0

            if not detail:
                return create_standard_artifact_response(
                    summary=f"未找到实体: {asset_id}",
                    component_type=ComponentType.TABLE,
                    name="实体详情",
                    data={"asset_id": asset_id, "found": False},
                    source="entity-registry",
                    description=f"实体不存在: {asset_id}",
                )

            profile = detail.get("profile", {})
            classifications = detail.get("classifications", [])
            relations = detail.get("relations", [])
            events = detail.get("events", [])
            snapshot = detail.get("market_snapshot", {})

            name_zh = profile.get("name_zh", asset_id)
            md = f"# 实体详情: {name_zh}\n\n"
            md += f"**Asset ID**: `{asset_id}` | **耗时**: {elapsed:.1f}s\n\n"

            if snapshot:
                md += "## 市场快照\n\n"
                for key in ("market_cap", "shares_outstanding", "pe_ratio", "pb_ratio"):
                    val = snapshot.get(key)
                    if val is not None:
                        md += f"- **{key}**: {val}\n"
                md += "\n"

            if events:
                md += f"## 公司事件 ({len(events)}个)\n\n"
                for evt in events[:10]:
                    etype = evt.get("event_type", "")
                    edate = evt.get("event_date", "")
                    md += f"- [{edate}] {etype}\n"
                md += "\n"

            section_counts = {
                "classifications": len(classifications),
                "relations": len(relations),
                "events": len(events),
                "has_snapshot": bool(snapshot),
            }

            summary = (
                f"实体详情: {name_zh} | "
                f"分类:{len(classifications)} 关系:{len(relations)} "
                f"事件:{len(events)} (耗时 {elapsed:.1f}s)"
            )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"实体详情: {name_zh}",
                data={**detail, "_section_counts": section_counts},
                source="entity-registry",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_entity_detail failed: {e}")
            return create_standard_artifact_response(
                summary=f"实体详情查询失败: {e}",
                component_type=ComponentType.TABLE,
                name="实体错误",
                data={"error": str(e), "asset_id": asset_id},
                source="entity-registry",
                description=f"查询失败: {e}",
            )

    # ------------------------------------------------------------------
    # get_entity_peers
    # ------------------------------------------------------------------
    @mcp.tool(tags={"entity", "fundamental"})
    async def get_entity_peers(
        symbol: str,
        scheme: str = "sw_industry",
        level: int = 1,
        limit: int = 20,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """发现同行业实体: 基于行业分类的同行发现.

        WHEN TO USE: 当AI需要找到与目标公司同行业的其他公司时使用,
        支持申万行业(SW)、中信行业(CITIC)、GICS等多种分类体系.
        典型触发: "茅台的同行有哪些" "和600519同行业的公司" "白酒行业公司列表".
        CONCEPT: 通过实体注册表的行业分类体系找到同行业公司. 默认使用申万一级
        行业分类, 也可以指定中信或GICS体系. 返回同行列表含asset_id、名称、
        行业分类等信息.
        DIFFERENTIATION: 与sector_research不同——后者是宏观行业分析;
        本工具是基于实体知识图谱的精确同行匹配, 返回的是具体公司列表.
        next_recommended_tools: resolve_entity, get_entity_detail, get_sector_scope
        """
        if ctx:
            await ctx.info(f"发现同行: {symbol} ({scheme})")

        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: get_entity_peers", symbol=symbol, scheme=scheme)

            service = _get_entity_service()
            if not service:
                return create_standard_artifact_response(
                    summary="实体注册表未初始化",
                    component_type=ComponentType.TABLE,
                    name="同行发现",
                    data={"error": "Entity registry not initialized", "symbol": symbol},
                    source="entity-registry",
                    description="需要PostgreSQL连接",
                )

            # First resolve the entity to get asset_id
            parts = symbol.split(":")
            ticker = symbol
            name = None
            if len(parts) != 2:
                # Not EXCHANGE:SYMBOL format, treat as name
                ticker = None
                name = symbol

            entity = await service.resolve_entity(ticker=ticker, name=name)
            if not entity:
                return create_standard_artifact_response(
                    summary=f"无法解析实体: {symbol}",
                    component_type=ComponentType.TABLE,
                    name="同行发现",
                    data={"symbol": symbol, "error": "Entity not found"},
                    source="entity-registry",
                    description=f"无法解析: {symbol}",
                )

            asset_id = entity.get("profile", {}).get("asset_id", "")
            if not asset_id:
                return create_standard_artifact_response(
                    summary=f"实体缺少asset_id: {symbol}",
                    component_type=ComponentType.TABLE,
                    name="同行发现",
                    data={"symbol": symbol, "error": "No asset_id"},
                    source="entity-registry",
                    description="实体数据不完整",
                )

            # Get peers
            peers = await service.get_peers(
                asset_id, scheme=scheme, level=level, limit=limit,
            )
            elapsed = time.perf_counter() - t0

            # Build markdown
            entity_name = entity.get("profile", {}).get("name_zh", symbol)
            entity_class = ""
            classifications = entity.get("classifications", [])
            for c in classifications:
                if c.get("scheme") == scheme and c.get("level") == level:
                    entity_class = c.get("name", "")
                    break

            md = f"# 同行发现: {entity_name}\n\n"
            md += f"**行业分类**: {entity_class} ({scheme} L{level})\n"
            md += f"**同行数量**: {len(peers)} | **耗时**: {elapsed:.1f}s\n\n"

            if peers:
                md += "| # | 名称 | 资产ID |\n"
                md += "|---|------|--------|\n"
                for i, peer in enumerate(peers[:20], 1):
                    pname = peer.get("name_zh", peer.get("name", ""))
                    paid = str(peer.get("asset_id", ""))[:8]
                    md += f"| {i} | {pname} | {paid}... |\n"

            summary = (
                f"同行发现: {entity_name}({entity_class}) | "
                f"{len(peers)}家同行 ({scheme}) (耗时 {elapsed:.1f}s)"
            )

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"同行: {entity_name}({entity_class})",
                data={
                    "symbol": symbol,
                    "entity_name": entity_name,
                    "classification": entity_class,
                    "scheme": scheme,
                    "peers": peers,
                    "peer_count": len(peers),
                },
                source="entity-registry",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"get_entity_peers failed: {e}")
            return create_standard_artifact_response(
                summary=f"同行发现失败: {e}",
                component_type=ComponentType.TABLE,
                name="同行错误",
                data={"error": str(e), "symbol": symbol},
                source="entity-registry",
                description=f"查询失败: {e}",
            )

    # ------------------------------------------------------------------
    # search_entities
    # ------------------------------------------------------------------
    @mcp.tool(tags={"entity", "fundamental"})
    async def search_entities(
        q: str,
        limit: int = 20,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """搜索实体: 按名称模糊搜索实体注册表.

        WHEN TO USE: 当AI需要按名称搜索公司实体时使用.
        典型触发: "搜索茅台相关的公司" "找名字里含有'银行'的公司" "搜索半导体公司".
        CONCEPT: 模糊搜索entity_profile表, 支持中文名称和英文名称匹配.
        返回匹配的实体列表含基础档案信息.
        DIFFERENTIATION: 与resolve_entity不同——本工具返回多个匹配结果;
        resolve_entity只返回最佳匹配.
        next_recommended_tools: resolve_entity, get_entity_detail
        """
        if ctx:
            await ctx.info(f"搜索实体: {q}")

        try:
            t0 = time.perf_counter()
            logger.info("MCP tool: search_entities", q=q)

            repo = _get_entity_repo()
            if not repo:
                return create_standard_artifact_response(
                    summary="实体注册表未初始化",
                    component_type=ComponentType.TABLE,
                    name="实体搜索",
                    data={"error": "Entity registry not initialized", "q": q},
                    source="entity-registry",
                    description="需要PostgreSQL连接",
                )

            results = await repo.search_profiles(
                name_query=q, limit=limit,
            )
            elapsed = time.perf_counter() - t0

            md = f"# 实体搜索: {q}\n\n"
            md += f"**结果数**: {len(results)} | **耗时**: {elapsed:.1f}s\n\n"

            if results:
                md += "| # | 名称 | 状态 |\n"
                md += "|---|------|------|\n"
                for i, entity in enumerate(results[:20], 1):
                    name = entity.get("name_zh", entity.get("name_en", ""))
                    status = entity.get("status", "")
                    md += f"| {i} | {name} | {status} |\n"

            summary = f"实体搜索: '{q}' | {len(results)}条结果 (耗时 {elapsed:.1f}s)"

            return create_standard_artifact_response(
                summary=summary,
                component_type=ComponentType.TABLE,
                name=f"搜索: {q}",
                data={"query": q, "results": results, "count": len(results)},
                source="entity-registry",
                description=summary,
                markdown=md,
            )

        except Exception as e:
            logger.error(f"search_entities failed: {e}")
            return create_standard_artifact_response(
                summary=f"实体搜索失败: {e}",
                component_type=ComponentType.TABLE,
                name="搜索错误",
                data={"error": str(e), "q": q},
                source="entity-registry",
                description=f"搜索失败: {e}",
            )
