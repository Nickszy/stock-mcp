# src/server/mcp/tools/filings_tools.py
"""MCP tools for SEC and A-share filings.
Provides access to regulatory filings and announcements.
Returns structured data (JSON).
"""

import re
from collections import Counter
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP, Context

from src.server.core.use_cases import filings as filings_use_cases
from src.server.utils.logger import logger

from src.server.mcp.tools.artifact_utils import (
    create_artifact_envelope,
    create_artifact_response,
    create_symbol_error_response,
)
from src.server.domain.symbols.errors import SymbolResolutionError


_NUMBER_PATTERN = re.compile(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:%|x|倍|亿美元|亿元|万元)?\b")


def _safe_excerpt(text: str, limit: int = 240) -> str:
    val = (text or "").strip()
    return val if len(val) <= limit else (val[: limit - 3] + "...")


def _extract_metric_lines(
    markdown: str,
    metric_hints: List[str],
    max_items: int = 30,
) -> List[Dict[str, Any]]:
    lines = (markdown or "").splitlines()
    hints = [h.lower() for h in (metric_hints or []) if str(h).strip()]
    items: List[Dict[str, Any]] = []
    for idx, line in enumerate(lines, start=1):
        raw = line.strip()
        if not raw:
            continue
        lowered = raw.lower()
        matched_hints = [h for h in hints if h in lowered]
        numbers = _NUMBER_PATTERN.findall(raw)
        if not numbers:
            continue
        if hints and not matched_hints:
            continue
        items.append(
            {
                "line_no": idx,
                "text": _safe_excerpt(raw),
                "numbers": numbers[:8],
                "metric_hints": matched_hints[:5],
            }
        )
        if len(items) >= max_items:
            break
    return items


def _extract_section_facts(
    markdown: str,
    section_hints: List[str],
    max_quotes_per_section: int = 5,
) -> List[Dict[str, Any]]:
    lines = (markdown or "").splitlines()
    hints = [h.lower() for h in (section_hints or []) if str(h).strip()]
    sections: List[Dict[str, Any]] = []

    current_heading = ""
    current_lines: List[str] = []
    collected: Dict[str, List[Dict[str, Any]]] = {}

    def _flush():
        nonlocal current_heading, current_lines
        if not current_heading or not current_lines:
            current_heading = ""
            current_lines = []
            return
        heading_key = current_heading.lower()
        matched = [h for h in hints if h in heading_key] if hints else [current_heading]
        if matched:
            snippets = []
            for i, text in enumerate(current_lines):
                clean = text.strip()
                if not clean:
                    continue
                snippets.append({"text": _safe_excerpt(clean, 300)})
                if len(snippets) >= max_quotes_per_section:
                    break
            if snippets:
                bucket = collected.setdefault(current_heading, [])
                bucket.extend(snippets)
        current_heading = ""
        current_lines = []

    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("#"):
            _flush()
            current_heading = stripped.lstrip("#").strip()
            continue
        if current_heading:
            current_lines.append(stripped)
    _flush()

    for heading, snippets in collected.items():
        sections.append(
            {
                "heading": heading,
                "facts": snippets[:max_quotes_per_section],
            }
        )
    return sections


def _first_non_empty(record: Dict[str, Any], keys: List[str]) -> str:
    for key in keys:
        val = str(record.get(key) or "").strip()
        if val:
            return val
    return ""


def _summarize_filing_collection(
    subject: str,
    label: str,
    records: List[Dict[str, Any]],
    *,
    date_keys: List[str],
    type_keys: List[str],
    id_keys: List[str],
    title_keys: List[str],
    fallback_types: Optional[List[str]] = None,
) -> str:
    total = len(records)
    date_vals = [
        _first_non_empty(item, date_keys)
        for item in records
        if isinstance(item, dict)
    ]
    date_vals = [d for d in date_vals if d]
    date_range = f"{min(date_vals)}~{max(date_vals)}" if date_vals else "日期未知"

    type_vals = [
        _first_non_empty(item, type_keys)
        for item in records
        if isinstance(item, dict)
    ]
    type_vals = [t for t in type_vals if t]
    type_counter = Counter(type_vals)
    if type_counter:
        top_types = ",".join([f"{k}({v})" for k, v in type_counter.most_common(3)])
    else:
        defaults = [str(t).strip() for t in (fallback_types or []) if str(t).strip()]
        top_types = ",".join(defaults[:3]) or "N/A"

    latest = ""
    if date_vals:
        dated_records = []
        for item in records:
            if not isinstance(item, dict):
                continue
            item_date = _first_non_empty(item, date_keys)
            if item_date:
                dated_records.append((item_date, item))
        if dated_records:
            latest_item = sorted(dated_records, key=lambda x: x[0], reverse=True)[0][1]
            latest_doc = _first_non_empty(latest_item, id_keys) or "N/A"
            latest_title = _safe_excerpt(_first_non_empty(latest_item, title_keys), 80) or "N/A"
            latest = f"latest_doc={latest_doc}, latest_title={latest_title}"

    summary_parts = [
        f"{subject} {label}: {total}份",
        f"类型={top_types}",
        f"区间={date_range}",
    ]
    if latest:
        summary_parts.append(latest)
    return " | ".join(summary_parts)


def register_filings_tools(mcp: FastMCP):
    """Register filings tools."""

    @mcp.tool(tags={"filings"})
    async def fetch_periodic_sec_filings(
        ticker: str,
        forms: list[str] = None,
        year: int = None,
        quarter: int = None,
        limit: int = 10,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """获取SEC定期报告(10-K/10-Q/20-F/6-K).

        WHEN TO USE: 用户需要查看美股公司的正式定期披露文件时调用, 适合基本面与财报研究入口.
        典型触发: "AAPL最近10-K" "TSLA 2024Q3 10-Q" "BABA 20-F".
        CONCEPT: 按ticker/表单类型/年份/季度检索SEC定期报告元数据, 返回报告列表和访问入口,
        适合追踪年报/季报等计划性披露.
        DIFFERENTIATION: 本工具只返回定期报告列表, 不下载正文; 与fetch_event_sec_filings不同(后者是8-K/3/4/5等事件驱动披露),
        与process_document和get_filing_markdown不同(那两个用于读取正文内容).
        next_recommended_tools: get_filing_markdown, process_document, extract_filing_key_metrics
        """
        if ctx:
            await ctx.info(
                f"🔧 获取SEC定期报告: {ticker}",
                extra={"ticker": ticker, "forms": forms, "year": year, "quarter": quarter}
            )

        try:
            logger.info(
                "MCP tool called: fetch_periodic_sec_filings",
                ticker=ticker,
                forms=forms,
                year=year,
                quarter=quarter,
                limit=limit,
            )

            results = await filings_use_cases.fetch_periodic_sec_filings(
                ticker=ticker,
                forms=forms,
                year=year,
                quarter=quarter,
                limit=limit,
            )
            
            if ctx:
                await ctx.info(
                    f"✅ SEC定期报告获取完成: {ticker}",
                    extra={"count": len(results)}
                )
                
            result = {
                "items": results,
                "component_type": "filings_list"
            }
            
            description = _summarize_filing_collection(
                ticker,
                "SEC定期报告",
                [r for r in results if isinstance(r, dict)],
                date_keys=["filing_date", "report_date"],
                type_keys=["form", "type"],
                id_keys=["filing_id", "accession", "doc_id", "accession_number"],
                title_keys=["title", "content_summary"],
                fallback_types=forms,
            )
            
            artifact = create_artifact_envelope(
                component_type="filings_list",
                name=f"{ticker} SEC定期报告",
                content=result,
                description=description,
                visible_to_llm=False,
                display_in_report=False,
            )
            return create_artifact_response(summary=description, artifact=artifact)

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败: {ticker}", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="filings_list", name=f"{ticker} SEC定期报告"
            )
        except Exception as e:
            logger.error(f"Fetch periodic SEC filings failed: {e}")
            if ctx:
                await ctx.error(
                    f"❌ 获取SEC定期报告失败: {ticker}",
                    extra={"error": str(e)}
                )
            return [{"error": str(e)}]

    @mcp.tool(tags={"filings"})
    async def fetch_event_sec_filings(
        ticker: str,
        forms: list[str] = None,
        start_date: str = None,
        end_date: str = None,
        limit: int = 10,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """获取SEC事件驱动报告(8-K/3/4/5/6-K).

        WHEN TO USE: 用户要追踪美股公司的突发事项或内幕交易披露时调用.
        典型触发: "AAPL最近8-K" "TSLA最近高管减持" "过去30天Form 4".
        CONCEPT: 检索SEC事件驱动披露, 包括重大事项(8-K)和内幕交易(Form 3/4/5),
        支持按日期区间筛选, 适合事件监控和公告驱动研究.
        DIFFERENTIATION: 本工具关注非定期/事件驱动披露; 与fetch_periodic_sec_filings不同(后者是10-K/10-Q等定期报告),
        与get_us_insider_trading不同(后者抽取结构化内幕交易数据, 本工具返回原始披露列表).
        next_recommended_tools: get_filing_markdown, process_document, fetch_periodic_sec_filings
        """
        if ctx:
            await ctx.info(
                f"🔧 获取SEC临时报告: {ticker}",
                extra={"ticker": ticker, "forms": forms}
            )

        try:
            logger.info(
                "MCP tool called: fetch_event_sec_filings",
                ticker=ticker,
                forms=forms,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )

            results = await filings_use_cases.fetch_event_sec_filings(
                ticker=ticker,
                forms=forms,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            
            if ctx:
                await ctx.info(
                    f"✅ SEC临时报告获取完成: {ticker}",
                    extra={"count": len(results)}
                )
                
            result = {
                "items": results,
                "component_type": "filings_list"
            }
            
            description = _summarize_filing_collection(
                ticker,
                "SEC临时报告",
                [r for r in results if isinstance(r, dict)],
                date_keys=["filing_date", "report_date"],
                type_keys=["form", "type"],
                id_keys=["filing_id", "accession", "doc_id", "accession_number"],
                title_keys=["title", "content_summary"],
                fallback_types=forms,
            )
            
            artifact = create_artifact_envelope(
                component_type="filings_list",
                name=f"{ticker} SEC临时报告",
                content=result,
                description=description,
                visible_to_llm=False,
                display_in_report=False,
            )
            return create_artifact_response(summary=description, artifact=artifact)

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败: {ticker}", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="filings_list", name=f"{ticker} SEC临时报告"
            )
        except Exception as e:
            logger.error(f"Fetch event SEC filings failed: {e}")
            if ctx:
                await ctx.error(
                    f"❌ 获取SEC临时报告失败: {ticker}",
                    extra={"error": str(e)}
                )
            return [{"error": str(e)}]

    @mcp.tool(tags={"filings"})
    async def fetch_ashare_filings(
        symbol: str,
        filing_types: list[str] = None,
        start_date: str = None,
        end_date: str = None,
        limit: int = 10,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """获取A股公告与披露文件(CNINFO/巨潮信息).

        WHEN TO USE: 用户要查看A股公司的公告/年报/半年报/季报/董事会决议等披露时调用.
        典型触发: "茅台最新年报" "宁德时代最近公告" "A股公司季报列表".
        CONCEPT: 按股票代码/披露类型/日期区间检索巨潮资讯公告列表, 返回公告元数据与PDF链接,
        适合A股公司治理、事件跟踪和财报披露研究.
        DIFFERENTIATION: 本工具面向A股CNINFO披露; 与fetch_periodic_sec_filings和fetch_event_sec_filings不同(后两者面向SEC),
        与process_document不同(本工具先找文件列表, process_document再下载处理正文).
        next_recommended_tools: process_document, get_filing_markdown
        """
        if ctx:
            await ctx.info(
                f"🔧 获取A股公告: {symbol}",
                extra={"symbol": symbol, "types": filing_types}
            )

        try:
            logger.info(
                "MCP tool called: fetch_ashare_filings",
                symbol=symbol,
                types=filing_types,
                limit=limit,
            )

            results = await filings_use_cases.fetch_ashare_filings(
                symbol=symbol,
                filing_types=filing_types,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )
            
            if ctx:
                await ctx.info(
                    f"✅ A股公告获取完成: {symbol}",
                    extra={"count": len(results)}
                )
                
            result = {
                "items": results,
                "component_type": "filings_list"
            }
            
            description = _summarize_filing_collection(
                symbol,
                "A股公告",
                [r for r in results if isinstance(r, dict)],
                date_keys=["ann_date", "pub_date", "filing_date", "end_date", "filingDate"],
                type_keys=["filing_type", "report_type", "announcement_type", "type", "form"],
                id_keys=["filing_id", "announcement_id", "doc_id", "secCode"],
                title_keys=["title", "announcement_title", "content_summary"],
                fallback_types=filing_types,
            )
            
            artifact = create_artifact_envelope(
                component_type="filings_list",
                name=f"{symbol} A股公告",
                content=result,
                description=description,
                visible_to_llm=False,
                display_in_report=False,
            )
            return create_artifact_response(summary=description, artifact=artifact)

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败: {symbol}", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="filings_list", name=f"{symbol} A股公告"
            )
        except Exception as e:
            logger.error(f"Fetch A-share filings failed: {e}")
            if ctx:
                await ctx.error(
                    f"❌ 获取A股公告失败: {symbol}",
                    extra={"error": str(e)}
                )
            return [{"error": str(e)}]

    @mcp.tool(tags={"filings"})
    async def process_document(
        doc_id: str,
        url: str,
        doc_type: str = "unknown",
        ticker: str = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """处理单个披露文档(下载并提取正文文本).

        WHEN TO USE: 用户已经拿到文档URL, 需要把SEC/公告文件下载并转成可分析文本时调用.
        典型触发: "把这个10-K下载成正文" "读取这份公告PDF" "先处理文档再抽指标".
        CONCEPT: 根据doc_id和url下载文档, 尝试提取HTML/PDF/文本内容并返回结构化结果,
        是从“文件列表”走向“正文分析”的桥接步骤.
        DIFFERENTIATION: 本工具处理任意给定URL的单个文档; 与get_filing_markdown不同(后者是SEC专用的ticker+doc_id读取),
        与fetch_*_filings不同(后者只返回文件列表), 与extract_*工具不同(后者基于已提取正文做结构化抽取).
        next_recommended_tools: extract_filing_key_metrics, extract_filing_section_facts, build_filing_citations
        """
        if ctx:
            await ctx.info(
                f"🔧 处理文档: {doc_id}",
                extra={"url": url, "doc_type": doc_type, "ticker": ticker}
            )

        try:
            logger.info(
                "MCP tool called: process_document",
                doc_id=doc_id,
                url=url,
                doc_type=doc_type,
                ticker=ticker,
            )

            result = await filings_use_cases.process_document(
                doc_id=doc_id,
                url=url,
                doc_type=doc_type,
                ticker=ticker,
            )
            
            if ctx:
                await ctx.info(f"✅ 文档处理完成: {doc_id}")
                
            return result

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败: {ticker}", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="filing_document", name=f"{ticker} 文档处理"
            )
        except Exception as e:
            logger.error(f"Process document failed: {e}")
            if ctx:
                await ctx.error(
                    f"❌ 文档处理失败: {doc_id}",
                    extra={"error": str(e)}
                )
            return {"error": str(e)}

    @mcp.tool(tags={"filings"})
    async def get_filing_markdown(
        ticker: str,
        doc_id: str,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """获取SEC文档Markdown正文(ticker + doc_id 读取完整文本).

        WHEN TO USE: 用户已从SEC报告列表拿到doc_id, 需要读取该文件完整正文时调用.
        典型触发: "读取这个10-K正文" "把AAPL这个accession转成markdown".
        CONCEPT: 基于ticker和doc_id抓取并转换SEC披露正文为markdown, 返回可直接用于搜索/抽取/引用的全文内容,
        是披露研究中的核心阅读工具.
        DIFFERENTIATION: 本工具是SEC专用全文读取入口; 与process_document不同(后者基于任意URL处理),
        与extract_filing_key_metrics不同(后者只抽关键数字行), 与extract_filing_section_facts不同(后者按章节整理事实片段).
        next_recommended_tools: extract_filing_key_metrics, extract_filing_section_facts, build_filing_citations
        """
        if ctx:
            await ctx.info(
                f"🔧 获取SEC文档Markdown: {ticker} {doc_id}",
                extra={"ticker": ticker, "doc_id": doc_id},
            )

        try:
            logger.info(
                "MCP tool called: get_filing_markdown",
                ticker=ticker,
                doc_id=doc_id,
            )
            result = await filings_use_cases.get_filing_markdown(
                ticker=ticker,
                doc_id=doc_id,
            )

            markdown = ""
            if isinstance(result, dict):
                markdown = str(result.get("content") or "")

            if isinstance(result, dict) and result.get("status") == "error":
                summary = (
                    f"{ticker} 文档Markdown获取失败: "
                    f"{result.get('error') or 'unknown error'}"
                )
                artifact = create_artifact_envelope(
                    component_type="filing_document",
                    name=f"{ticker} SEC文档Markdown",
                    content=result,
                    description=summary,
                    visible_to_llm=True,
                    display_in_report=False,
                )
                return create_artifact_response(summary=summary, artifact=artifact)

            summary = (
                f"{ticker} 文档Markdown获取完成: doc_id={doc_id}"
                f" | cached={bool(result.get('cached')) if isinstance(result, dict) else False}"
                f" | length={len(markdown)} chars"
                f" | heading_count={markdown.count('#')}"
            )
            artifact = create_artifact_envelope(
                component_type="filing_document",
                name=f"{ticker} SEC文档Markdown",
                content=result,
                description=summary,
                visible_to_llm=False,
                display_in_report=False,
            )
            if ctx:
                await ctx.info(
                    f"✅ SEC文档Markdown获取完成: {ticker}",
                    extra={
                        "doc_id": doc_id,
                        "cached": bool(result.get("cached"))
                        if isinstance(result, dict)
                        else False,
                        "length": len(markdown),
                    },
                )
            return create_artifact_response(summary=summary, artifact=artifact)

        except SymbolResolutionError as e:
            if ctx:
                await ctx.warning(f"⚠️ 符号解析失败: {ticker}", extra=e.to_dict())
            return create_symbol_error_response(
                e, component_type="filing_document", name=f"{ticker} SEC文档Markdown"
            )
        except Exception as e:
            logger.error(f"Get filing markdown failed: {e}")
            if ctx:
                await ctx.error(
                    f"❌ 获取SEC文档Markdown失败: {ticker}",
                    extra={"error": str(e)},
                )
            return {"error": str(e)}

    @mcp.tool(tags={"filings"})
    async def extract_filing_key_metrics(
        ticker: str,
        doc_id: str,
        metric_hints: list[str] = None,
        max_items: int = 30,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """提取披露文件关键指标行(快速抓取数字证据).

        WHEN TO USE: 用户不想通读整篇披露, 只想快速抓取收入/利润/EPS/毛利率等数字证据时调用.
        典型触发: "从10-K里抓关键数字" "提取财报指标" "快速找revenue和net income".
        CONCEPT: 在披露markdown中扫描包含数字和指标提示词的文本行, 返回带行号/数字片段/提示词命中的结构化结果,
        适合快速证据抽取和报告素材准备.
        DIFFERENTIATION: 本工具返回指标型数字行; 与get_filing_markdown不同(全文读取),
        与extract_filing_section_facts不同(后者按章节组织事实片段), 与build_filing_citations不同(后者构造可引用对象).
        next_recommended_tools: extract_filing_section_facts, build_filing_citations, get_filing_markdown
        """
        default_hints = [
            "revenue",
            "net income",
            "operating income",
            "eps",
            "margin",
            "capex",
            "guidance",
            "收入",
            "净利润",
            "毛利率",
            "现金流",
            "资本开支",
            "同比",
        ]
        hints = metric_hints or default_hints
        max_items = max(5, min(int(max_items), 100))
        if ctx:
            await ctx.info(
                f"🔧 提取文档关键指标: {ticker} {doc_id}",
                extra={"ticker": ticker, "doc_id": doc_id, "max_items": max_items},
            )

        try:
            markdown_result = await filings_use_cases.get_filing_markdown(
                ticker=ticker,
                doc_id=doc_id,
            )
            markdown = (
                str(markdown_result.get("content") or "")
                if isinstance(markdown_result, dict)
                else ""
            )
            items = _extract_metric_lines(markdown, hints, max_items=max_items)
            preview = []
            for item in items[:2]:
                numbers = ",".join(item.get("numbers", [])[:3])
                preview.append(
                    f"L{item.get('line_no')}: {item.get('text')} [{numbers}]"
                )
            summary = (
                f"{ticker} 关键指标提取完成: {len(items)}条"
                f" | doc_id={doc_id}"
                f" | cached={bool(markdown_result.get('cached')) if isinstance(markdown_result, dict) else False}"
                f" | 示例={' ; '.join(preview) if preview else 'N/A'}"
            )
            artifact = create_artifact_envelope(
                component_type="filing_key_metrics",
                name=f"{ticker} Filing Key Metrics",
                content={
                    "ticker": ticker,
                    "doc_id": doc_id,
                    "items": items,
                    "metric_hints": hints,
                },
                description=summary,
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, component_type="filing_key_metrics", name=f"{ticker} Filing Key Metrics"
            )
        except Exception as e:
            logger.error(f"Extract filing key metrics failed: {e}")
            return {"error": str(e)}

    @mcp.tool(tags={"filings"})
    async def extract_filing_section_facts(
        ticker: str,
        doc_id: str,
        section_hints: list[str] = None,
        max_quotes_per_section: int = 5,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """提取披露文件章节事实片段(按Risk Factors/MD&A等章节组织).

        WHEN TO USE: 用户要基于披露文件的特定章节做证据化分析时调用.
        典型触发: "提取风险因素" "看MD&A怎么说" "按章节整理关键表述".
        CONCEPT: 将披露markdown按标题章节切分, 根据section hints抽取各章节中的事实片段,
        返回“章节 -> 引文片段”的结构化结果, 适合构建基于披露的论证材料.
        DIFFERENTIATION: 本工具按章节组织文字证据; 与extract_filing_key_metrics不同(后者偏数字行),
        与get_filing_markdown不同(后者返回全文原文), 与build_filing_citations不同(后者偏轻量引用对象).
        next_recommended_tools: build_filing_citations, extract_filing_key_metrics, get_filing_markdown
        """
        default_sections = ["item 1a", "item 7", "item 8", "risk factors", "md&a"]
        hints = section_hints or default_sections
        max_quotes = max(1, min(int(max_quotes_per_section), 20))
        if ctx:
            await ctx.info(
                f"🔧 提取文档章节事实: {ticker} {doc_id}",
                extra={
                    "ticker": ticker,
                    "doc_id": doc_id,
                    "section_hints": hints,
                },
            )

        try:
            markdown_result = await filings_use_cases.get_filing_markdown(
                ticker=ticker,
                doc_id=doc_id,
            )
            markdown = (
                str(markdown_result.get("content") or "")
                if isinstance(markdown_result, dict)
                else ""
            )
            sections = _extract_section_facts(
                markdown,
                hints,
                max_quotes_per_section=max_quotes,
            )
            quote_count = sum(
                len(sec.get("facts", []))
                for sec in sections
                if isinstance(sec, dict)
            )
            headings = [
                str(sec.get("heading") or "").strip()
                for sec in sections[:3]
                if isinstance(sec, dict)
            ]
            summary = (
                f"{ticker} 章节事实提取完成: {len(sections)}个章节"
                f" | quotes={quote_count}"
                f" | doc_id={doc_id}"
                f" | sections={','.join([h for h in headings if h]) or 'N/A'}"
            )
            artifact = create_artifact_envelope(
                component_type="filing_section_facts",
                name=f"{ticker} Filing Section Facts",
                content={
                    "ticker": ticker,
                    "doc_id": doc_id,
                    "sections": sections,
                    "section_hints": hints,
                },
                description=summary,
                visible_to_llm=True,
                display_in_report=True,
            )
            return create_artifact_response(summary=summary, artifact=artifact)
        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, component_type="filing_section_facts", name=f"{ticker} Filing Section Facts"
            )
        except Exception as e:
            logger.error(f"Extract filing section facts failed: {e}")
            return {"error": str(e)}

    @mcp.tool(tags={"filings"})
    async def build_filing_citations(
        ticker: str,
        doc_id: str,
        metric_hints: list[str] = None,
        max_items: int = 15,
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """构建披露文件引用锚点(将指标行转为可引用对象).

        WHEN TO USE: 用户需要在研究报告或分析中引用披露文件中的具体数据点时调用.
        典型触发: "给这些数字加上出处引用" "构造引用锚点" "citations".
        CONCEPT: 从披露markdown中提取指标行, 并转为包含ref_id/ticker/doc_id/行号/原文的引用对象,
        方便在报告中建立“数据 -> 来源”的证据链.
        DIFFERENTIATION: 本工具输出的是引用对象(引用格式); 与extract_filing_key_metrics不同(后者输出原始指标行),
        与extract_filing_section_facts不同(后者按章节组织片段), 与get_filing_markdown不同(后者输出全文).
        next_recommended_tools: extract_filing_key_metrics, extract_filing_section_facts
        """
        max_items = max(5, min(int(max_items), 50))
        try:
            markdown_result = await filings_use_cases.get_filing_markdown(
                ticker=ticker,
                doc_id=doc_id,
            )
            markdown = (
                str(markdown_result.get("content") or "")
                if isinstance(markdown_result, dict)
                else ""
            )
            metric_items = _extract_metric_lines(
                markdown,
                metric_hints or ["revenue", "net income", "eps", "收入", "净利润", "毛利率"],
                max_items=max_items,
            )
            citations = []
            for item in metric_items[:max_items]:
                line_no = item.get("line_no")
                citations.append(
                    {
                        "ref_id": f"{doc_id}#L{line_no}",
                        "ticker": ticker,
                        "doc_id": doc_id,
                        "line_no": line_no,
                        "quote": item.get("text"),
                        "numbers": item.get("numbers", []),
                    }
                )
            first_ref = citations[0].get("ref_id") if citations else "N/A"
            summary = (
                f"{ticker} 引用锚点构建完成: {len(citations)}条"
                f" | doc_id={doc_id}"
                f" | first_ref={first_ref}"
            )
            artifact = create_artifact_envelope(
                component_type="filing_citations",
                name=f"{ticker} Filing Citations",
                content={
                    "ticker": ticker,
                    "doc_id": doc_id,
                    "citations": citations,
                },
                description=summary,
                visible_to_llm=True,
                display_in_report=True,
            )
            if ctx:
                await ctx.info(
                    f"✅ 文档引用锚点构建完成: {ticker}",
                    extra={"doc_id": doc_id, "count": len(citations)},
                )
            return create_artifact_response(summary=summary, artifact=artifact)
        except SymbolResolutionError as e:
            return create_symbol_error_response(
                e, component_type="filing_citations", name=f"{ticker} Filing Citations"
            )
        except Exception as e:
            logger.error(f"Build filing citations failed: {e}")
            return {"error": str(e)}
