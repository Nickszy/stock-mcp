# src/server/mcp/tools/output_format_utils.py
"""
Output formatting utilities for MCP tools.

Provides unified output formatting:
- markdown: Human-readable format with Chinese field labels (default)
- json: Structured data for programmatic consumption
"""

from typing import Any, Dict, List, Literal, Optional, Union


OutputFormat = Literal["markdown", "json"]


# ============================================================
# Chinese field label mappings
# ============================================================

COMMON_LABELS: Dict[str, str] = {
    "ts_code": "股票代码",
    "trade_date": "交易日期",
    "end_date": "报告期",
    "symbol": "代码",
    "name": "名称",
    "date": "日期",
}

FINANCIAL_LABELS: Dict[str, str] = {
    "revenue": "营业收入",
    "n_income_attr_p": "归母净利润",
    "net_income": "净利润",
    "total_revenue": "营业总收入",
    "operating_profit": "营业利润",
    "total_profit": "利润总额",
    "gross_profit": "毛利润",
    "ebit": "EBIT",
    "ebitda": "EBITDA",
    "eps": "每股收益",
    "bps": "每股净资产",
    "roe": "ROE",
    "roa": "ROA",
    "gross_margin": "毛利率",
    "net_margin": "净利率",
    "debt_ratio": "资产负债率",
    "current_ratio": "流动比率",
    "quick_ratio": "速动比率",
    "ocf": "经营现金流",
    "fcf": "自由现金流",
    "category": "年度",
    "line": "同比变化",
}

TECHNICAL_LABELS: Dict[str, str] = {
    "close": "收盘价",
    "open": "开盘价",
    "high": "最高价",
    "low": "最低价",
    "volume": "成交量",
    "amount": "成交额",
    "turnover_rate": "换手率",
    "pct_chg": "涨跌幅",
    "change": "涨跌额",
    "RSI": "RSI",
    "RSI_14": "RSI(14)",
    "MACD": "MACD",
    "MACD_signal": "MACD信号线",
    "MACD_hist": "MACD柱",
    "SMA_20": "MA20",
    "SMA_50": "MA50",
    "SMA_200": "MA200",
    "EMA_12": "EMA12",
    "EMA_26": "EMA26",
    "BB_upper": "布林上轨",
    "BB_lower": "布林下轨",
    "BB_middle": "布林中轨",
    "KDJ_K": "KDJ_K",
    "KDJ_D": "KDJ_D",
    "KDJ_J": "KDJ_J",
    "ATR": "ATR",
}

MONEY_FLOW_LABELS: Dict[str, str] = {
    "main_net_inflow": "主力净流入",
    "retail_net_inflow": "散户净流入",
    "large_net_inflow": "大单净流入",
    "xlarge_net_inflow": "超大单净流入",
    "medium_net_inflow": "中单净流入",
    "small_net_inflow": "小单净流入",
    "total_net_inflow": "总净流入",
    "main_ratio": "主力占比",
    "trend": "趋势",
    "amount_unit": "金额单位",
}

EARNINGS_LABELS: Dict[str, str] = {
    "actual_eps": "实际EPS",
    "estimated_eps": "预期EPS",
    "surprise": "惊喜值",
    "surprise_pct": "惊喜率%",
    "date": "财报日期",
    "quarter": "季度",
    "fiscal_period": "财年季度",
}

SECTOR_LABELS: Dict[str, str] = {
    "sector_name": "板块名称",
    "etf_ticker": "ETF代码",
    "total_change_pct": "区间涨跌幅",
    "weekly_change_pct": "周涨跌幅",
    "trend_summary": "趋势摘要",
    "price_momentum": "价格动量",
    "flow_signal": "资金信号",
    "valuation_level": "估值水平",
    "structure_score": "结构评分",
}

# Combined labels map
ALL_LABELS: Dict[str, str] = {
    **COMMON_LABELS,
    **FINANCIAL_LABELS,
    **TECHNICAL_LABELS,
    **MONEY_FLOW_LABELS,
    **EARNINGS_LABELS,
    **SECTOR_LABELS,
}


# ============================================================
# Formatting functions
# ============================================================


def get_label(field_name: str) -> str:
    """Get Chinese label for a field name."""
    return ALL_LABELS.get(field_name, field_name)


def format_number(value: Any, unit: str = "") -> str:
    """Format number with appropriate precision and unit."""
    if value is None:
        return "N/A"
    if not isinstance(value, (int, float)):
        return str(value)

    # Handle large numbers
    abs_val = abs(value)
    if abs_val >= 1e8:
        return f"{value / 1e8:.2f}亿{unit}"
    if abs_val >= 1e4:
        return f"{value / 1e4:.2f}万{unit}"

    # Handle percentages
    if unit == "%":
        return f"{value:.2f}%"

    # Default formatting
    if isinstance(value, float):
        return f"{value:.2f}{unit}"
    return f"{value}{unit}"


def format_percentage(value: Any) -> str:
    """Format value as percentage."""
    if value is None:
        return "N/A"
    if isinstance(value, (int, float)):
        # If value looks like it's already a ratio (e.g., 0.15 = 15%)
        if abs(value) < 1:
            return f"{value * 100:.2f}%"
        return f"{value:.2f}%"
    return str(value)


def _format_table_markdown(
    rows: List[Dict[str, Any]],
    title: str = "",
    column_order: Optional[List[str]] = None,
) -> str:
    """Format list of dicts as markdown table with Chinese labels."""
    if not rows:
        return f"**{title}**\n\n暂无数据\n" if title else "暂无数据\n"

    # Get all unique keys from rows
    all_keys = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen and key not in ("id",):
                all_keys.append(key)
                seen.add(key)

    # Use provided column order or default
    keys = column_order if column_order else all_keys
    keys = [k for k in keys if k in all_keys]

    # Build header with Chinese labels
    headers = [get_label(k) for k in keys]

    # Build table
    lines = []
    if title:
        lines.append(f"### {title}\n")

    # Header row
    lines.append("| " + " | ".join(headers) + " |")
    # Separator
    lines.append("| " + " | ".join(["---"] * len(keys)) + " |")

    # Data rows
    for row in rows:
        values = []
        for key in keys:
            val = row.get(key)
            if val is None:
                values.append("-")
            elif isinstance(val, float):
                # Smart formatting based on key name
                if "pct" in key.lower() or "ratio" in key.lower() or "surprise" in key.lower():
                    values.append(format_percentage(val))
                elif "amount" in key.lower() or "revenue" in key.lower() or "income" in key.lower():
                    values.append(format_number(val))
                else:
                    values.append(f"{val:.2f}")
            else:
                values.append(str(val))
        lines.append("| " + " | ".join(values) + " |")

    return "\n".join(lines) + "\n"


def _format_quarter_bars_markdown(
    data: List[Dict[str, Any]],
    title: str = "",
    value_unit: str = "亿元",
) -> str:
    """Format quarterly bar data (revenue/net income) as markdown."""
    if not data:
        return f"**{title}**\n\n暂无数据\n" if title else "暂无数据\n"

    lines = []
    if title:
        lines.append(f"### {title}\n")

    lines.append("| 年度 | Q1 | Q2 | Q3 | Q4 | 年度合计 | 同比 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")

    for item in data:
        year = item.get("category", "N/A")
        bars = item.get("bars", {})
        yoy = item.get("line")

        q1 = bars.get("Q1")
        q2 = bars.get("Q2")
        q3 = bars.get("Q3")
        q4 = bars.get("Q4")

        # Calculate total
        total = sum(v for v in [q1, q2, q3, q4] if isinstance(v, (int, float)))

        # Format values
        def fmt(v):
            if v is None:
                return "-"
            if not isinstance(v, (int, float)):
                return str(v)
            if value_unit == "亿元":
                return f"{v / 1e8:.2f}" if abs(v) >= 1e8 else f"{v:.2f}"
            return f"{v:.2f}"

        total_str = f"{total / 1e8:.2f}" if value_unit == "亿元" and total else "-"
        yoy_str = f"{yoy * 100:+.1f}%" if isinstance(yoy, (int, float)) else "-"

        lines.append(
            f"| {year} | {fmt(q1)} | {fmt(q2)} | {fmt(q3)} | {fmt(q4)} | {total_str} | {yoy_str} |"
        )

    return "\n".join(lines) + "\n"


def _format_money_flow_markdown(
    records: List[Dict[str, Any]],
    title: str = "",
    amount_unit: str = "unknown",
) -> str:
    """Format money flow records as markdown."""
    if not records:
        return f"**{title}**\n\n暂无数据\n" if title else "暂无数据\n"

    lines = []
    if title:
        lines.append(f"### {title}\n")
        lines.append(f"金额单位: {_unit_label(amount_unit)}\n")

    lines.append("| 交易日期 | 主力净流入 |")
    lines.append("| --- | --- |")

    for rec in records[-10:]:  # Show last 10 days
        date = rec.get("trade_date", "-")
        main_flow = rec.get("main_net_inflow")
        if main_flow is not None:
            flow_str = format_number(main_flow)
            # Add color indicator
            if main_flow > 0:
                flow_str = f"+{flow_str}"
        else:
            flow_str = "-"
        lines.append(f"| {date} | {flow_str} |")

    return "\n".join(lines) + "\n"


def _unit_label(unit: str) -> str:
    """Get Chinese label for unit."""
    return {
        "cny": "元",
        "10k_cny": "万元",
        "100m_cny": "亿元",
        "unknown": "原始单位",
    }.get(unit, unit or "原始单位")


# ============================================================
# Main formatting dispatcher
# ============================================================


def format_output(
    data: Any,
    component_type: str,
    output_format: OutputFormat = "markdown",
    title: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Format tool output based on output_format.

    Args:
        data: The data to format (dict, list of dicts, etc.)
        component_type: Type of component (e.g., "financial_chart", "money_flow")
        output_format: "markdown" for human-readable, "json" for structured
        title: Optional title for the output
        metadata: Optional metadata (e.g., amount_unit for money flow)

    Returns:
        Formatted string (markdown or JSON)
    """
    if output_format == "json":
        import json
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)

    # Markdown formatting based on component type
    if component_type == "financial_chart":
        # Handle quarterly bar data
        if isinstance(data, dict) and "data" in data:
            chart_data = data.get("data", [])
            chart_title = data.get("title", title)
            return _format_quarter_bars_markdown(chart_data, chart_title)
        if isinstance(data, list):
            return _format_quarter_bars_markdown(data, title)

    if component_type == "money_flow":
        records = data.get("records", []) if isinstance(data, dict) else data
        unit = metadata.get("amount_unit", "unknown") if metadata else "unknown"
        return _format_money_flow_markdown(records, title, unit)

    if component_type in ("table", "earnings_table"):
        if isinstance(data, dict):
            rows = data.get("rows", data.get("quarters", []))
            return _format_table_markdown(rows, title)
        if isinstance(data, list):
            return _format_table_markdown(data, title)

    if component_type == "technical_indicators":
        if isinstance(data, list):
            return _format_table_markdown(data, title)

    # Default: format as table if list of dicts
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return _format_table_markdown(data, title)

    # Fallback: JSON-like representation
    import json
    return f"```json\n{json.dumps(data, ensure_ascii=False, indent=2, default=str)}\n```\n"
