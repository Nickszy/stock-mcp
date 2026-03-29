# src/server/domain/fact_markdown.py
"""Fact Markdown View Builder (COL-149).

Generates structured, fact-only Markdown from stock fact pack data.
Rules:
  - Fact-only output: numbers, dates, ratios, rankings
  - No analysis conclusions (no "growth slowing", "overvalued", etc.)
  - Unified number formatting, units, missing value representation
  - Section + table layout for token efficiency
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ------------------------------------------------------------------
# Number formatting helpers
# ------------------------------------------------------------------

def _fmt_num(v: Any, decimals: int = 2) -> str:
    """Format a number for Markdown display."""
    if v is None:
        return "-"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(n) >= 1e8:
        return f"{n / 1e8:.{decimals}f}亿"
    if abs(n) >= 1e4:
        return f"{n / 1e4:.{decimals}f}万"
    if abs(n) < 0.01 and n != 0:
        return f"{n:.6f}"
    return f"{n:.{decimals}f}"


def _fmt_pct(v: Any) -> str:
    """Format a percentage value."""
    if v is None:
        return "-"
    try:
        return f"{float(v):.2f}%"
    except (TypeError, ValueError):
        return str(v)


def _fmt_date(v: Any) -> str:
    """Format a date-like value."""
    if v is None:
        return "-"
    s = str(v)
    # Truncate timestamp to date
    if " " in s:
        return s.split(" ")[0]
    return s[:10]


# ------------------------------------------------------------------
# Table builder
# ------------------------------------------------------------------

def _table(headers: List[str], rows: List[List[str]]) -> str:
    """Build a Markdown table from headers and rows."""
    if not rows:
        return ""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _kv_table(data: Dict[str, Any], key_label: str = "字段", val_label: str = "值") -> str:
    """Build a two-column key-value Markdown table."""
    if not data:
        return "_暂无数据_"
    rows = []
    for k, v in data.items():
        rows.append([k, _auto_format(v)])
    return _table([key_label, val_label], rows)


def _auto_format(v: Any) -> str:
    """Auto-format a value based on its key context and type."""
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, (int, float)):
        return _fmt_num(v)
    if isinstance(v, (list, tuple)):
        if len(v) == 0:
            return "-"
        if isinstance(v[0], dict):
            return f"[{len(v)}条记录]"
        return ", ".join(str(x) for x in v[:5])
    if isinstance(v, dict):
        return f"{{...}}({len(v)}字段)"
    return str(v)


# ------------------------------------------------------------------
# Category renderers
# ------------------------------------------------------------------

def _render_security_master(data: Dict[str, Any]) -> str:
    """Render security master as a compact info table."""
    if not data:
        return ""
    return _kv_table(data, "字段", "值")


def _render_financial(data: Any) -> str:
    """Render financial facts (income statement / balance sheet key lines)."""
    if not data:
        return ""
    if isinstance(data, dict):
        # Check for nested structures like income/balance/cashflow
        sections = []
        for section_name, section_data in data.items():
            if isinstance(section_data, dict):
                rows = []
                for k, v in section_data.items():
                    if isinstance(v, dict):
                        # Nested dict — flatten one level
                        for sk, sv in v.items():
                            rows.append([f"{k}.{sk}", _auto_format(sv)])
                    else:
                        rows.append([k, _auto_format(v)])
                if rows:
                    sections.append(f"**{section_name}**\n" + _table(["指标", "值"], rows))
            elif isinstance(section_data, list) and section_data:
                # List of records (e.g., multi-period financials)
                if isinstance(section_data[0], dict):
                    headers = list(section_data[0].keys())[:6]
                    rows = []
                    for item in section_data[:4]:
                        rows.append([_auto_format(item.get(h)) for h in headers])
                    sections.append(f"**{section_name}**\n" + _table(headers, rows))
        return "\n\n".join(sections)
    return str(data)


def _render_market(data: Dict[str, Any]) -> str:
    """Render market facts (valuation + money flow)."""
    if not data:
        return ""
    sections = []
    for sub_name, sub_data in data.items():
        if not sub_data:
            continue
        if isinstance(sub_data, dict):
            # Format known valuation fields nicely
            rows = []
            for k, v in sub_data.items():
                if k in ("trade_date", "date", "日期"):
                    rows.append(["日期", _fmt_date(v)])
                elif "pe" in k.lower() or "pb" in k.lower() or "dv_ratio" in k.lower():
                    rows.append([k, _fmt_num(v)])
                elif "turnover" in k.lower() or "volume" in k.lower():
                    rows.append([k, _fmt_num(v)])
                elif "change" in k.lower() or "pct" in k.lower() or "amplitude" in k.lower():
                    rows.append([k, _fmt_pct(v)])
                elif "total_mv" in k.lower() or "circ_mv" in k.lower():
                    rows.append([k, _fmt_num(v)])
                else:
                    rows.append([k, _auto_format(v)])
            sections.append(f"**{sub_name}**\n" + _table(["指标", "值"], rows))
        elif isinstance(sub_data, list) and sub_data:
            sections.append(f"**{sub_name}**: [{len(sub_data)}条记录]")
    return "\n\n".join(sections)


def _render_governance(data: Dict[str, Any]) -> str:
    """Render governance facts (shareholders)."""
    if not data:
        return ""
    sections = []
    for sub_name, sub_data in data.items():
        if not sub_data:
            continue
        if isinstance(sub_data, list) and sub_data and isinstance(sub_data[0], dict):
            # Shareholder table
            headers = list(sub_data[0].keys())[:5]
            rows = []
            for item in sub_data[:10]:
                rows.append([_auto_format(item.get(h)) for h in headers])
            sections.append(f"**{sub_name}**\n" + _table(headers, rows))
        elif isinstance(sub_data, list):
            sections.append(f"**{sub_name}**: [{len(sub_data)}条]")
        else:
            sections.append(f"**{sub_name}**: {_auto_format(sub_data)}")
    return "\n\n".join(sections)


def _render_events(data: Dict[str, Any]) -> str:
    """Render event facts (dividends, repurchase, restricted release)."""
    if not data:
        return ""
    sections = []
    for sub_name, sub_data in data.items():
        if not sub_data:
            continue
        if isinstance(sub_data, dict):
            # Check if it has a list of records
            if "data" in sub_data and isinstance(sub_data["data"], list):
                records = sub_data["data"]
                if records and isinstance(records[0], dict):
                    headers = list(records[0].keys())[:5]
                    rows = []
                    for item in records[:5]:
                        rows.append([_auto_format(item.get(h)) for h in headers])
                    sections.append(f"**{sub_name}**\n" + _table(headers, rows))
                else:
                    sections.append(f"**{sub_name}**: [{len(records)}条]")
            else:
                sections.append(f"**{sub_name}**\n" + _kv_table(sub_data))
        elif isinstance(sub_data, list) and sub_data:
            if isinstance(sub_data[0], dict):
                headers = list(sub_data[0].keys())[:5]
                rows = []
                for item in sub_data[:5]:
                    rows.append([_auto_format(item.get(h)) for h in headers])
                sections.append(f"**{sub_name}**\n" + _table(headers, rows))
            else:
                sections.append(f"**{sub_name}**: [{len(sub_data)}条]")
    return "\n\n".join(sections)


def _render_business_structure(data: Any) -> str:
    """Render business structure facts (main business composition)."""
    if not data:
        return ""
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            records = data["data"]
            if records and isinstance(records[0], dict):
                headers = list(records[0].keys())[:6]
                rows = []
                for item in records[:10]:
                    rows.append([_auto_format(item.get(h)) for h in headers])
                return _table(headers, rows)
        return _kv_table(data)
    return str(data)


def _render_company_master(data: Any) -> str:
    """Render company master facts (basic company information)."""
    if not data or not isinstance(data, dict):
        return ""
    fields = [
        ("公司名称", "company_name"),
        ("简称", "short_name"),
        ("行业", "industry"),
        ("成立日期", "established_date"),
        ("上市日期", "ipo_date"),
        ("法人代表", "legal_representative"),
        ("董事长", "chairman"),
        ("总经理", "general_manager"),
        ("董秘", "secretary"),
        ("注册资本", "registered_capital"),
        ("员工总数", "employees"),
        ("办公地址", "office_address"),
        ("网址", "website"),
    ]
    rows = []
    for label, key in fields:
        val = data.get(key)
        if val:
            rows.append([label, str(val)])
    if not rows:
        return ""
    return _table(["字段", "值"], rows)


def _render_peers(data: Any) -> str:
    """Render peer comparison facts (industry peers)."""
    if not data or not isinstance(data, dict):
        return ""
    parts = []
    industry = data.get("industry", "")
    if industry:
        parts.append(f"**行业**: {industry}")
    peers = data.get("peers", [])
    if not peers:
        return "\n".join(parts) if parts else ""
    parts.append(f"**同业公司** ({data.get('count', len(peers))}家)")
    headers = ["代码", "名称", "PE(动态)", "PB", "总市值"]
    rows = []
    for p in peers[:10]:
        mcap = p.get("market_cap")
        mcap_str = _fmt_num(mcap) if mcap else "-"
        rows.append([
            p.get("code", ""),
            p.get("name", ""),
            _fmt_num(p.get("pe")) if p.get("pe") else "-",
            _fmt_num(p.get("pb")) if p.get("pb") else "-",
            mcap_str,
        ])
    parts.append(_table(headers, rows))
    return "\n\n".join(parts)


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------

_CATEGORY_RENDERERS = {
    "security_master": ("证券主档", _render_security_master),
    "company_master": ("公司主档", _render_company_master),
    "financial": ("财务事实", _render_financial),
    "market": ("市场事实", _render_market),
    "governance": ("治理与股权", _render_governance),
    "events": ("事件事实", _render_events),
    "business_structure": ("业务结构", _render_business_structure),
    "peers": ("同业对比", _render_peers),
}

# Categories that have data but no dedicated renderer: generic dict renderer
_GENERIC_CATEGORIES = {
    "company_master": "公司主档",
    "peers": "同业对比",
    "restricted_release": "限售解禁",
    "repurchase": "回购数据",
}


def build_stock_fact_markdown(fact_pack: Dict[str, Any]) -> str:
    """Build a fact-only Markdown view from a stock fact pack.

    Args:
        fact_pack: Output of AkshareAdapter.get_stock_fact_pack()

    Returns:
        Markdown string with sections and tables for each fact category.
    """
    entity = fact_pack.get("entity", {})
    facts = fact_pack.get("facts", {})
    coverage = fact_pack.get("coverage", {})
    missing = fact_pack.get("missing_fields", [])

    symbol = entity.get("symbol", "?")
    name = _get_security_name(facts)
    fetched = fact_pack.get("categories_fetched", 0)
    total = fact_pack.get("categories_total", 8)
    elapsed = fact_pack.get("elapsed_seconds", 0)

    parts: List[str] = []

    # Header
    header = f"# {name} ({symbol}) 事实数据"
    meta = f"覆盖: {fetched}/{total} | 耗时: {elapsed:.1f}s"
    parts.append(header)
    parts.append(meta)

    # Coverage summary
    if coverage:
        cov_items = []
        for cat, status in coverage.items():
            icon = {"complete": "✅", "partial": "⚠️", "missing": "❌"}.get(
                status.split(":")[0] if ":" in status else status, "⏳"
            )
            cov_items.append(f"{icon} {cat}: {status}")
        parts.append("## 覆盖状态\n" + "\n".join(cov_items))

    # Render each fact category
    for cat_key, (cat_title, renderer) in _CATEGORY_RENDERERS.items():
        cat_data = facts.get(cat_key)
        if cat_data:
            rendered = renderer(cat_data)
            if rendered:
                parts.append(f"## {cat_title}\n{rendered}")

    # Handle generic categories
    for cat_key, cat_title in _GENERIC_CATEGORIES.items():
        cat_data = facts.get(cat_key)
        if cat_data:
            parts.append(f"## {cat_title}")
            if isinstance(cat_data, dict):
                parts.append(_kv_table(cat_data))
            else:
                parts.append(_auto_format(cat_data))

    # Missing fields note
    if missing:
        parts.append(f"## 缺失类别\n" + ", ".join(missing))

    return "\n\n".join(parts)


def _get_security_name(facts: Dict[str, Any]) -> str:
    """Extract security name from fact data."""
    sm = facts.get("security_master", {})
    if isinstance(sm, dict):
        return sm.get("name", "")
    return ""


# ------------------------------------------------------------------
# Generic fact pack Markdown builder
# ------------------------------------------------------------------

def _build_fact_markdown(
    title: str,
    fact_pack: Dict[str, Any],
    category_titles: Dict[str, str],
) -> str:
    """Generic fact-only Markdown builder for any fact pack type."""
    entity = fact_pack.get("entity", {})
    facts = fact_pack.get("facts", {})
    coverage = fact_pack.get("coverage", {})
    missing = fact_pack.get("missing_fields", [])
    fetched = fact_pack.get("categories_fetched", 0)
    total = fact_pack.get("categories_total", 8)
    elapsed = fact_pack.get("elapsed_seconds", 0)

    symbol = entity.get("symbol") or entity.get("fund_code", "?")

    parts: List[str] = []
    parts.append(f"# {title} ({symbol}) 事实数据")
    parts.append(f"覆盖: {fetched}/{total} | 耗时: {elapsed:.1f}s")

    # Coverage summary
    if coverage:
        cov_items = []
        for cat, status in coverage.items():
            icon = {"complete": "✅", "partial": "⚠️", "missing": "❌"}.get(
                status.split(":")[0] if ":" in status else status, "⏳"
            )
            cov_items.append(f"{icon} {cat}: {status}")
        parts.append("## 覆盖状态\n" + "\n".join(cov_items))

    # Render each fact category
    for cat_key, cat_title in category_titles.items():
        cat_data = facts.get(cat_key)
        if not cat_data:
            continue
        if isinstance(cat_data, dict):
            # Check for nested sub-sections
            sub_sections = []
            for sub_name, sub_data in cat_data.items():
                if sub_data is None:
                    continue
                if isinstance(sub_data, list) and sub_data:
                    if isinstance(sub_data[0], dict):
                        headers = list(sub_data[0].keys())[:6]
                        rows = []
                        for item in sub_data[:10]:
                            rows.append([_auto_format(item.get(h)) for h in headers])
                        sub_sections.append(f"**{sub_name}**\n" + _table(headers, rows))
                    else:
                        sub_sections.append(f"**{sub_name}**: [{len(sub_data)}条]")
                elif isinstance(sub_data, dict):
                    rows = []
                    for k, v in sub_data.items():
                        rows.append([k, _auto_format(v)])
                    sub_sections.append(f"**{sub_name}**\n" + _table(["指标", "值"], rows))
                else:
                    sub_sections.append(f"**{sub_name}**: {_auto_format(sub_data)}")
            if sub_sections:
                parts.append(f"## {cat_title}\n" + "\n\n".join(sub_sections))
        elif isinstance(cat_data, list) and cat_data:
            if isinstance(cat_data[0], dict):
                headers = list(cat_data[0].keys())[:6]
                rows = []
                for item in cat_data[:10]:
                    rows.append([_auto_format(item.get(h)) for h in headers])
                parts.append(f"## {cat_title}\n" + _table(headers, rows))
            else:
                parts.append(f"## {cat_title}\n[{len(cat_data)}条记录]")
        else:
            parts.append(f"## {cat_title}\n" + _auto_format(cat_data))

    # Missing fields
    if missing:
        parts.append(f"## 缺失类别\n" + ", ".join(missing))

    return "\n\n".join(parts)


# ------------------------------------------------------------------
# Fund fact pack Markdown builder (COL-151)
# ------------------------------------------------------------------

_FUND_CATEGORY_TITLES = {
    "master": "基金主档",
    "nav": "净值与收益事实",
    "holdings": "持仓与穿透事实",
    "manager": "基金经理与治理事实",
    "manager_changes": "基金经理变更记录",
    "scale": "规模与份额事实",
    "allocation": "资产配置与风格事实",
    "fees": "费率与分红事实",
    "peer": "同类比较事实",
}


def build_fund_fact_markdown(fact_pack: Dict[str, Any]) -> str:
    """Build fact-only Markdown view from fund fact pack data.

    Args:
        fact_pack: Output of AkshareAdapter.get_fund_fact_pack()

    Returns:
        Markdown string with sections and tables for each fund fact category.
    """
    entity = fact_pack.get("entity", {})
    fund_code = entity.get("fund_code", "?")
    # Try to get fund name from master facts
    master = fact_pack.get("facts", {}).get("master", {})
    name = master.get("fund_name", "") if isinstance(master, dict) else ""

    return _build_fact_markdown(
        title=f"{name}" if name else fund_code,
        fact_pack=fact_pack,
        category_titles=_FUND_CATEGORY_TITLES,
    )


# ------------------------------------------------------------------
# Market fact pack Markdown builder (COL-153)
# ------------------------------------------------------------------

_MARKET_CATEGORY_TITLES = {
    "master": "标的估值指标",
    "snapshot": "技术指标快照",
    "kline": "K线与区间行情事实",
    "money_flow": "资金流与成交结构",
    "breadth": "市场广度与横截面",
    "index": "指数/板块行情事实",
    "derivative": "衍生行情与波动率",
    "relative": "相对强弱与可比标的",
    "north_bound": "北向资金",
    "margin": "融资融券",
}


def build_market_fact_markdown(fact_pack: Dict[str, Any]) -> str:
    """Build fact-only Markdown view from market fact pack data.

    Args:
        fact_pack: Output of AkshareAdapter.get_market_fact_pack()

    Returns:
        Markdown string with sections and tables for each market fact category.
    """
    return _build_fact_markdown(
        title="行情",
        fact_pack=fact_pack,
        category_titles=_MARKET_CATEGORY_TITLES,
    )


# ------------------------------------------------------------------
# US Stock fact pack Markdown builder (COL-175)
# ------------------------------------------------------------------

_US_STOCK_CATEGORY_TITLES = {
    "profile": "公司概况",
    "valuation": "估值指标",
    "financials": "财务数据",
    "ownership": "持仓与内部人",
    "analyst": "分析师与收入构成",
    "technical": "技术分析",
}


def build_us_stock_fact_markdown(fact_pack: Dict[str, Any]) -> str:
    """Build fact-only Markdown view from US stock fact pack data.

    Args:
        fact_pack: Output of YahooAdapter.get_us_stock_fact_pack()

    Returns:
        Markdown string with sections and tables for each US stock fact category.
    """
    entity = fact_pack.get("entity", {})
    ticker = entity.get("symbol", "?")
    profile = fact_pack.get("facts", {}).get("profile", {})
    name = profile.get("company_name", "") if isinstance(profile, dict) else ""

    return _build_fact_markdown(
        title=f"{name}" if name else ticker,
        fact_pack=fact_pack,
        category_titles=_US_STOCK_CATEGORY_TITLES,
    )


# ------------------------------------------------------------------
# ETF fact pack Markdown builder (COL-175)
# ------------------------------------------------------------------

_ETF_CATEGORY_TITLES = {
    "master": "ETF主档",
    "realtime": "实时行情",
    "performance": "历史表现",
    "flow": "资金流/申赎",
    "technical": "技术信号",
}


def build_etf_fact_markdown(fact_pack: Dict[str, Any]) -> str:
    """Build fact-only Markdown view from ETF fact pack data.

    Args:
        fact_pack: Output of AkshareAdapter.get_etf_fact_pack()

    Returns:
        Markdown string with sections and tables for each ETF fact category.
    """
    entity = fact_pack.get("entity", {})
    symbol = entity.get("symbol", "?")
    master = fact_pack.get("facts", {}).get("master", {})
    name = master.get("name", "") if isinstance(master, dict) else ""

    return _build_fact_markdown(
        title=f"ETF {name}" if name else f"ETF {symbol}",
        fact_pack=fact_pack,
        category_titles=_ETF_CATEGORY_TITLES,
    )


# ------------------------------------------------------------------
# Index fact pack Markdown builder (COL-175)
# ------------------------------------------------------------------

_INDEX_CATEGORY_TITLES = {
    "master": "指数主档",
    "valuation": "PE/PB估值",
    "performance": "行情表现",
    "constituents": "主要成分股",
    "technical": "技术信号",
}


def build_index_fact_markdown(fact_pack: Dict[str, Any]) -> str:
    """Build fact-only Markdown view from index fact pack data.

    Args:
        fact_pack: Output of AkshareAdapter.get_index_fact_pack()

    Returns:
        Markdown string with sections and tables for each index fact category.
    """
    entity = fact_pack.get("entity", {})
    symbol = entity.get("symbol", "?")
    master = fact_pack.get("facts", {}).get("master", {})
    name = master.get("name", "") if isinstance(master, dict) else ""

    return _build_fact_markdown(
        title=f"{name}" if name else f"指数 {symbol}",
        fact_pack=fact_pack,
        category_titles=_INDEX_CATEGORY_TITLES,
    )
