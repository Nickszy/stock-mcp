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


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------

_CATEGORY_RENDERERS = {
    "security_master": ("证券主档", _render_security_master),
    "financial": ("财务事实", _render_financial),
    "market": ("市场事实", _render_market),
    "governance": ("治理与股权", _render_governance),
    "events": ("事件事实", _render_events),
    "business_structure": ("业务结构", _render_business_structure),
}

# Categories that have data but no dedicated renderer: generic dict renderer
_GENERIC_CATEGORIES = {
    "company_master": "公司主档",
    "peers": "同业对比",
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
