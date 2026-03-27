"""
数据质量报告页面

测试各数据源的数据质量，生成对比报告。
"""

import streamlit as st
import pandas as pd
import asyncio
import httpx
import random
from datetime import datetime
from typing import Dict, List, Any, Optional
from decimal import Decimal
from collections import defaultdict
import sys
from pathlib import Path

# 添加配置模块路径
config_path = Path(__file__).parent.parent / "config"
if str(config_path) not in sys.path:
    sys.path.insert(0, str(config_path))

# 尝试从配置文件加载，失败则使用默认配置
try:
    from config_loader import get_config
    _config = get_config()

    # 从配置文件加载市场
    MARKETS = {}
    for name, market in _config.get_all_markets().items():
        MARKETS[name] = {
            "tickers": market.tickers,
            "sources": market.sources,
        }

    # 从配置文件加载数据维度
    DATA_TYPES = {}
    for key, dim in _config.get_all_dimensions().items():
        DATA_TYPES[key] = {
            "name": dim.display_name,
            "api_endpoint": dim.api_endpoint,
            "method": dim.http_method.value,
            "key_fields": dim.key_fields,
            "request_type": dim.request_type.value,
        }

    API_BASE = _config.get_api_base()
    USE_CONFIG = True
except Exception as e:
    # 回退到默认配置
    USE_CONFIG = False
    API_BASE = "http://stock-mcp-api:9898"

    MARKETS = {
        "A股": {
            "tickers": ["SSE:600519", "SZSE:000858", "SSE:600036", "SZSE:000001", "SSE:601318", "SZSE:000002"],
            "sources": ["auto", "tushare", "baostock"],
        },
        "美股": {
            "tickers": ["NASDAQ:AAPL", "NASDAQ:MSFT", "NYSE:JPM", "NYSE:BAC", "NASDAQ:GOOGL", "NYSE:BRK.B"],
            "sources": ["auto", "yahoo", "finnhub"],
        },
        "港股": {
            "tickers": ["HKEX:00700", "HKEX:00941", "HKEX:09988", "HKEX:01810", "HKEX:02318", "HKEX:09868"],
            "sources": ["auto", "yahoo"],
        },
    }

    DATA_TYPES = {
        "price": {
            "name": "价格数据",
            "api_endpoint": "/api/v1/market/prices/batch",
            "method": "POST",
            "key_fields": ["price", "open_price", "high_price", "low_price", "close_price", "volume", "change", "change_percent"],
            "request_type": "json_body",
        },
        "financials": {
            "name": "财务报表",
            "api_endpoint": "/api/v1/fundamental/financials",
            "method": "POST",
            "key_fields": ["revenue", "net_income", "total_assets", "total_liabilities", "equity"],
            "request_type": "query_params",
        },
        "ratios": {
            "name": "财务比率",
            "api_endpoint": "/api/v1/fundamental/ratios",
            "method": "POST",
            "key_fields": ["pe_ratio", "pb_ratio", "roe", "roa", "debt_ratio", "current_ratio"],
            "request_type": "query_params",
        },
        "forecast": {
            "name": "盈利预测",
            "api_endpoint": "/api/v1/fundamental/forecast",
            "method": "POST",
            "key_fields": ["eps_forecast", "revenue_forecast", "growth_rate"],
            "request_type": "query_params",
        },
    }


def get_random_ticker(market: str) -> str:
    """获取随机股票代码"""
    tickers = MARKETS[market]["tickers"]
    return random.choice(tickers)


async def fetch_data(
    client: httpx.AsyncClient,
    data_type: str,
    ticker: str,
    source: str
) -> Dict[str, Any]:
    """获取数据"""
    config = DATA_TYPES.get(data_type)
    if not config:
        return {"error": f"未知数据类型: {data_type}"}

    # auto 模式不指定 source
    actual_source = None if source == "auto" else source

    try:
        if config["method"] == "POST":
            if data_type == "price":
                # 价格数据使用 JSON body
                payload = {"tickers": [ticker]}
                if actual_source:
                    payload["source"] = actual_source
                response = await client.post(
                    f"{API_BASE}{config['api_endpoint']}",
                    json=payload,
                    timeout=30.0
                )
            else:
                # 其他数据类型（财务数据）使用 query params
                params = {"symbol": ticker}
                if actual_source:
                    params["source"] = actual_source
                response = await client.post(
                    f"{API_BASE}{config['api_endpoint']}",
                    params=params,
                    timeout=30.0
                )
        else:
            params = {"symbol": ticker}
            if actual_source:
                params["source"] = actual_source
            response = await client.get(
                f"{API_BASE}{config['api_endpoint']}",
                params=params,
                timeout=30.0
            )

        if response.status_code == 200:
            data = response.json()
            if data_type == "price":
                return data.get(ticker, {"error": "无数据"})
            return data
        else:
            return {"error": f"HTTP {response.status_code}"}

    except Exception as e:
        return {"error": str(e)}


async def run_comparison(
    tickers: List[str],
    sources: List[str],
    data_type: str
) -> Dict[str, Any]:
    """运行对比测试"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        results = {}

        for ticker in tickers:
            ticker_results = {}
            tasks = {}

            for source in sources:
                tasks[source] = fetch_data(client, data_type, ticker, source)

            responses = await asyncio.gather(*tasks.values())

            for source, data in zip(tasks.keys(), responses):
                ticker_results[source] = data

            results[ticker] = ticker_results

        return results


def analyze_differences(results: Dict[str, Dict[str, Any]], key_fields: List[str]) -> Dict[str, Any]:
    """分析差异"""
    analysis = {
        "has_data": {},
        "differences": {},
        "null_fields": {},
        "field_values": {},
    }

    sources = list(results.keys())

    # 检查哪些数据源有数据
    for source, data in results.items():
        if data is None:
            analysis["has_data"][source] = False
        elif "error" in data:
            analysis["has_data"][source] = False
        elif isinstance(data, dict) and not data:
            analysis["has_data"][source] = False
        else:
            analysis["has_data"][source] = True
            # 保存字段值
            analysis["field_values"][source] = data

    # 收集所有有数据的数据源的字段值
    valid_sources = [s for s, has in analysis["has_data"].items() if has]

    # 统计每个字段的值
    for field in key_fields:
        values = {}
        for source in valid_sources:
            data = results.get(source, {})
            if isinstance(data, dict):
                val = data.get(field)
                if val is not None:
                    values[source] = val
        analysis["field_values"][field] = values

    # 只在多个数据源都有数据时比较差异（排除 auto）
    compare_sources = [s for s in valid_sources if s != "auto"]
    if len(compare_sources) < 2:
        return analysis

    # 比较字段差异
    for field in key_fields:
        values = {}
        for source in compare_sources:
            data = results.get(source, {})
            if isinstance(data, dict):
                val = data.get(field)
                if val is not None:
                    values[source] = val

        if len(values) >= 2:
            vals = [float(v) if isinstance(v, (int, float, Decimal)) else 0 for v in values.values()]
            max_val = max(vals)
            min_val = min(vals)

            if max_val > 0 and (max_val - min_val) / max_val > 0.001:  # 差异超过 0.1%
                analysis["differences"][field] = {
                    "values": values,
                    "max": max_val,
                    "min": min_val,
                    "diff_percent": (max_val - min_val) / max_val * 100 if max_val > 0 else 0,
                }

    # 统计空字段
    for source in valid_sources:
        data = results.get(source, {})
        if isinstance(data, dict):
            nulls = [k for k, v in data.items() if v is None or v == ""]
            if nulls:
                analysis["null_fields"][source] = nulls

    return analysis


def generate_source_comparison_table(
    comparison_results: Dict[str, Dict[str, Any]],
    data_type: str,
    market: str
) -> str:
    """生成数据源对比分析表格"""
    config = DATA_TYPES.get(data_type, {})
    key_fields = config.get("key_fields", [])

    # 统计各数据源的表现
    source_stats = defaultdict(lambda: {
        "success": 0,
        "total": 0,
        "null_fields": defaultdict(int),
        "differences": [],
    })

    all_sources = set()

    for ticker, source_results in comparison_results.items():
        analysis = analyze_differences(source_results, key_fields)

        for source, has_data in analysis["has_data"].items():
            all_sources.add(source)
            source_stats[source]["total"] += 1
            if has_data:
                source_stats[source]["success"] += 1
                # 统计空字段
                data = source_results.get(source, {})
                if isinstance(data, dict):
                    for field in key_fields:
                        if field not in data or data[field] is None:
                            source_stats[source]["null_fields"][field] += 1

        # 记录差异
        for field, diff in analysis["differences"].items():
            for source in diff["values"].keys():
                source_stats[source]["differences"].append({
                    "ticker": ticker,
                    "field": field,
                    "diff_percent": diff["diff_percent"],
                })

    # 生成表格
    lines = [
        "## 数据源差异分析",
        "",
        "### 数据源成功率",
        "",
        "| 数据源 | 成功率 | 有数据 | 总测试 | 状态 |",
        "|--------|--------|--------|--------|------|",
    ]

    # 按成功率排序
    sorted_sources = sorted(
        source_stats.items(),
        key=lambda x: (x[1]["success"] / x[1]["total"] if x[1]["total"] > 0 else 0, -x[1]["total"]),
        reverse=True
    )

    for source, stats in sorted_sources:
        total = stats["total"]
        success = stats["success"]
        rate = success / total * 100 if total > 0 else 0

        if rate >= 90:
            status = "⭐⭐⭐⭐⭐"
        elif rate >= 70:
            status = "⭐⭐⭐⭐"
        elif rate >= 50:
            status = "⭐⭐⭐"
        elif rate > 0:
            status = "⭐⭐"
        else:
            status = "❌"

        lines.append(f"| {source} | {rate:.0f}% | {success} | {total} | {status} |")

    lines.append("")

    # 关键字段缺失统计
    lines.append("### 关键字段缺失统计")
    lines.append("")
    lines.append("| 数据源 | 缺失字段 |")
    lines.append("|--------|----------|")

    for source, stats in sorted_sources:
        if stats["null_fields"]:
            null_info = ", ".join([f"{k}({v})" for k, v in stats["null_fields"].items()])
        else:
            null_info = "无"
        lines.append(f"| {source} | {null_info} |")

    lines.append("")

    # 差异汇总
    has_diffs = any(stats["differences"] for _, stats in sorted_sources)
    if has_diffs:
        lines.append("### 数据差异汇总")
        lines.append("")
        lines.append("| 数据源 | 差异数 | 最大差异率 | 差异字段 |")
        lines.append("|--------|--------|------------|----------|")

        for source, stats in sorted_sources:
            diffs = stats["differences"]
            if diffs:
                max_diff = max(d["diff_percent"] for d in diffs)
                fields = set(d["field"] for d in diffs)
                lines.append(f"| {source} | {len(diffs)} | {max_diff:.2f}% | {', '.join(fields)} |")

        lines.append("")

    # 推荐优先级
    lines.append("### 推荐数据源优先级")
    lines.append("")
    lines.append("```python")
    lines.append(f"SOURCE_PRIORITY = {{")
    lines.append(f'    "{market}": [')

    # 只推荐成功率 > 50% 的数据源，auto 除外
    recommended = [
        source for source, stats in sorted_sources
        if stats["total"] > 0 and stats["success"] / stats["total"] > 0.5
        and source != "auto"
    ]
    for source in recommended:
        lines.append(f'        "{source}",')
    lines.append(f"    ]")
    lines.append(f"}}")
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def generate_report(
    comparison_results: Dict[str, Dict[str, Any]],
    data_type: str,
    market: str,
    tickers: List[str] = None,
    sources: List[str] = None
) -> str:
    """生成 Markdown 报告"""
    config = DATA_TYPES.get(data_type, {})
    key_fields = config.get("key_fields", [])

    report_lines = [
        f"# 数据质量报告",
        f"",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"",
        f"## 测试参数",
        f"",
        f"- **市场**: {market}",
        f"- **数据维度**: {config.get('name', data_type)} ({data_type})",
        f"- **测试股票**: {', '.join(tickers) if tickers else 'N/A'}",
        f"- **数据源**: {', '.join(sources) if sources else 'N/A'}",
        f"",
        "---",
        "",
    ]

    # 添加数据源差异分析表格
    source_comparison = generate_source_comparison_table(comparison_results, data_type, market)
    report_lines.append(source_comparison)

    total_tests = 0
    success_tests = 0
    all_differences = []

    report_lines.append("## 详细测试结果")
    report_lines.append("")

    for ticker, source_results in comparison_results.items():
        report_lines.append(f"## {ticker}")
        report_lines.append("")

        analysis = analyze_differences(source_results, key_fields)

        # 数据源状态
        report_lines.append("| 数据源 | 状态 | 关键字段 | 空字段 |")
        report_lines.append("|--------|------|----------|--------|")

        for source, has_data in analysis["has_data"].items():
            total_tests += 1
            if has_data:
                success_tests += 1
                status = "✅"
                data = source_results.get(source, {})
                if isinstance(data, dict):
                    filled = len([k for k in key_fields if k in data and data[k] is not None])
                    fields_info = f"{filled}/{len(key_fields)}"
                    nulls = analysis["null_fields"].get(source, [])
                    nulls_info = ", ".join(nulls[:3]) + ("..." if len(nulls) > 3 else "")
                else:
                    fields_info = "-"
                    nulls_info = "-"
            else:
                status = "❌"
                fields_info = "-"
                data = source_results.get(source)
                if data is None:
                    nulls_info = "无数据"
                elif isinstance(data, dict):
                    nulls_info = data.get("error", "无数据")
                else:
                    nulls_info = str(data)

            report_lines.append(f"| {source} | {status} | {fields_info} | {nulls_info or '-'} |")

        report_lines.append("")

        # 数据对比表格
        report_lines.append("### 数据对比")
        report_lines.append("")

        # 获取有数据的数据源
        valid_sources = [s for s, has in analysis["has_data"].items() if has]

        if valid_sources:
            # 表头
            header = "| 字段 | " + " | ".join(valid_sources) + " |"
            separator = "|------|" + "|".join(["------" for _ in valid_sources]) + "|"
            report_lines.append(header)
            report_lines.append(separator)

            # 每个字段一行
            for field in key_fields:
                values = []
                for source in valid_sources:
                    data = source_results.get(source, {})
                    if isinstance(data, dict):
                        val = data.get(field)
                        if val is None:
                            values.append("-")
                        elif isinstance(val, float):
                            values.append(f"{val:,.2f}")
                        else:
                            values.append(str(val))
                    else:
                        values.append("-")
                report_lines.append(f"| {field} | " + " | ".join(values) + " |")

        # 差异分析
        if analysis["differences"]:
            report_lines.append("### 发现差异")
            report_lines.append("")
            report_lines.append("| 字段 | 数值 | 差异率 |")
            report_lines.append("|------|------|--------|")

            for field, diff in analysis["differences"].items():
                values_str = ", ".join([f"{k}:{v}" for k, v in diff["values"].items()])
                report_lines.append(f"| {field} | {values_str} | {diff['diff_percent']:.2f}% |")
                all_differences.append((ticker, field, diff["diff_percent"]))

            report_lines.append("")

        report_lines.append("---")
        report_lines.append("")

    # 总结
    report_lines.append("## 总结")
    report_lines.append("")
    report_lines.append(f"- **总测试数**: {total_tests}")
    report_lines.append(f"- **成功数**: {success_tests}")
    report_lines.append(f"- **成功率**: {success_tests/total_tests*100:.1f}%" if total_tests > 0 else "- **成功率**: N/A")

    if all_differences:
        report_lines.append(f"- **发现差异**: {len(all_differences)} 处")
        report_lines.append("")
        report_lines.append("### 差异详情")
        for ticker, field, pct in sorted(all_differences, key=lambda x: -x[2]):
            report_lines.append(f"- {ticker} - {field}: {pct:.2f}%")

    return "\n".join(report_lines)


def show(db, project_root):
    """显示数据质量报告页面"""

    st.title("📋 数据质量报告")
    st.markdown("测试各数据源的数据质量，生成对比报告")

    st.markdown("---")

    # ========== 快速测试区域（放在最上面）==========
    st.markdown("### ⚡ 快速测试")
    st.markdown("快速输入股票代码进行测试")

    quick_col1, quick_col2, quick_col3, quick_col4 = st.columns([2, 2, 2, 1])

    with quick_col1:
        quick_market = st.selectbox("市场", list(MARKETS.keys()), key="quick_market")

    with quick_col2:
        quick_type = st.selectbox(
            "数据维度",
            list(DATA_TYPES.keys()),
            format_func=lambda x: DATA_TYPES[x]["name"],
            key="quick_type"
        )

    with quick_col3:
        # 初始化随机股票代码
        if "quick_ticker_input" not in st.session_state:
            st.session_state["quick_ticker_input"] = get_random_ticker(quick_market)

        quick_ticker = st.text_input("股票代码", key="quick_ticker_input")

    with quick_col4:
        st.markdown("<br>", unsafe_allow_html=True)

        def randomize_ticker():
            st.session_state["quick_ticker_input"] = get_random_ticker(
                st.session_state.get("quick_market", "A股")
            )

        st.button("🎲 随机", use_container_width=True, on_click=randomize_ticker)

    # 数据源选择
    quick_sources = st.multiselect(
        "选择数据源（可多选）",
        MARKETS[quick_market]["sources"],
        default=MARKETS[quick_market]["sources"],
        key="quick_sources"
    )

    if st.button("🚀 开始测试", type="primary", use_container_width=True):
        if not quick_ticker:
            st.warning("请输入股票代码")
        elif not quick_sources:
            st.warning("请选择至少一个数据源")
        else:
            with st.spinner(f"正在测试 {quick_ticker}..."):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    results = loop.run_until_complete(
                        run_comparison([quick_ticker], quick_sources, quick_type)
                    )
                finally:
                    loop.close()

                report = generate_report(
                    results, quick_type, quick_market,
                    tickers=[quick_ticker],
                    sources=quick_sources
                )

                # 保存报告到 session state
                st.session_state["current_report"] = report
                st.session_state["report_generated"] = True

    st.markdown("---")

    # ========== 报告展示区域 ==========
    if "current_report" in st.session_state and st.session_state.get("report_generated"):
        report = st.session_state["current_report"]

        # 展示报告（使用 code 有复制按钮）
        st.code(report, language="markdown")
        st.markdown("---")

    # ========== 高级配置区域 ==========
    with st.expander("🔧 高级配置（批量测试）"):
        st.markdown("### 批量测试配置")

        adv_col1, adv_col2 = st.columns(2)

        with adv_col1:
            adv_market = st.selectbox("选择市场", list(MARKETS.keys()), key="adv_market")
            adv_type = st.selectbox(
                "选择数据维度",
                list(DATA_TYPES.keys()),
                format_func=lambda x: DATA_TYPES[x]["name"],
                key="adv_type"
            )

        with adv_col2:
            # 自定义股票代码
            custom_tickers = st.text_area(
                "自定义股票代码（每行一个）",
                placeholder="SSE:600519\nSZSE:000858\n...",
                key="custom_tickers"
            )

        # 数据源选择
        adv_sources = st.multiselect(
            "选择数据源",
            MARKETS[adv_market]["sources"],
            default=MARKETS[adv_market]["sources"],
            key="adv_sources"
        )

        # 股票选择
        default_tickers = MARKETS[adv_market]["tickers"]
        selected_tickers = st.multiselect(
            "或选择预设股票",
            default_tickers,
            default=default_tickers[:2],
            key="adv_tickers"
        )

        if st.button("🚀 批量测试", use_container_width=True):
            # 确定要测试的股票
            if custom_tickers.strip():
                tickers = [t.strip() for t in custom_tickers.strip().split("\n") if t.strip()]
            else:
                tickers = selected_tickers

            if not tickers:
                st.warning("请选择或输入股票代码")
            elif not adv_sources:
                st.warning("请选择至少一个数据源")
            else:
                with st.spinner(f"正在测试 {len(tickers)} 只股票..."):
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        results = loop.run_until_complete(
                            run_comparison(tickers, adv_sources, adv_type)
                        )
                    finally:
                        loop.close()

                    report = generate_report(
                        results, adv_type, adv_market,
                        tickers=tickers,
                        sources=adv_sources
                    )
                    st.session_state["current_report"] = report
                    st.session_state["report_generated"] = True
                    st.rerun()
