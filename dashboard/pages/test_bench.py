"""
测试台页面

提供交互式数据源测试功能
"""

import streamlit as st
import pandas as pd
import json
import time
from datetime import datetime
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.server.monitoring import MonitoringDB, RequestLog, RequestStatus


def show(db: MonitoringDB, project_root: Path):
    """显示测试台页面"""
    st.title("🔬 数据源测试台")
    st.markdown("交互式测试不同数据源，对比结果和质量")

    st.markdown("---")

    # ========== 第一部分：测试配置 ==========
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("📝 测试配置")

        # 数据类型选择
        data_type = st.selectbox(
            "数据类型",
            [
                "price",
                "financials",
                "forecast",
                "ratios",
                "news",
                "event",
                "support_resistance",
                "technical_indicators",
                "trading_signals",
            ],
            help="选择要测试的数据类型:\n"
                 "- price: 实时行情价格\n"
                 "- financials: 财务报表数据\n"
                 "- forecast: 业绩预测\n"
                 "- ratios: 财务比率\n"
                 "- news: 市场新闻\n"
                 "- event: 公司公告/事件\n"
                 "- support_resistance: 支撑阻力分析\n"
                 "- technical_indicators: 技术指标\n"
                 "- trading_signals: 交易信号",
        )

        # 股票代码输入
        instrument_id = st.text_input(
            "标的代码",
            value="SSE:600519",
            help="格式: EXCHANGE:SYMBOL (例如 SSE:600519, NASDAQ:AAPL)",
        )

        # 数据源选择
        st.markdown("**选择数据源（多选）**")
        available_sources = {
            "price": ["tushare", "akshare", "baostock", "yahoo", "finnhub"],
            "financials": ["tushare", "akshare", "yahoo"],
            "forecast": ["tushare", "akshare"],
            "ratios": ["tushare", "akshare"],
            "news": ["akshare", "finnhub"],
            "event": ["tushare", "akshare"],
            "support_resistance": ["tushare", "akshare"],
            "technical_indicators": ["tushare", "akshare"],
            "trading_signals": ["tushare", "akshare"],
        }

        sources_for_type = available_sources.get(data_type, ["tushare", "akshare"])

        # 添加"自动选择"选项
        all_options = ["🔄 auto（自动优先级）"] + sources_for_type
        selected_with_auto = st.multiselect(
            "数据源",
            all_options,
            default=["🔄 auto（自动优先级）"],  # 默认选择自动
            label_visibility="collapsed",
        )

        # 解析选择结果
        # has_auto: 是否选择了 auto（不传 source，让后端自动选择优先级最高的）
        # selected_sources: 用户手动选择的数据源列表（不含 auto）
        has_auto = any("auto" in s for s in selected_with_auto)
        selected_sources = [s for s in selected_with_auto if "auto" not in s]

        # 高级选项
        with st.expander("⚙️ 高级选项"):
            show_raw_response = st.checkbox("显示原始响应", value=True)
            save_to_db = st.checkbox("保存测试记录", value=True)
            timeout_seconds = st.slider("超时时间（秒）", 5, 60, 30)
            output_format = st.radio(
                "输出格式",
                ["json", "markdown"],
                horizontal=True,
                help="选择结果展示格式",
            )

    with col2:
        st.subheader("📊 快速选择")

        # 快速选择预设
        preset = st.selectbox(
            "测试预设",
            [
                "自定义",
                "A股龙头股（茅台）",
                "美股科技股（苹果）",
                "港股（腾讯）",
                "加密货币（比特币）",
            ],
        )

        if preset == "A股龙头股（茅台）":
            instrument_id = st.text_input("标的代码", value="SSE:600519", key="preset_a")
            data_type = st.selectbox("数据类型", ["price", "financials"], key="preset_a_type")
        elif preset == "美股科技股（苹果）":
            instrument_id = st.text_input("标的代码", value="NASDAQ:AAPL", key="preset_us")
            data_type = st.selectbox("数据类型", ["price", "financials"], key="preset_us_type")
        elif preset == "港股（腾讯）":
            instrument_id = st.text_input("标的代码", value="HKEX:00700", key="preset_hk")
            data_type = st.selectbox("数据类型", ["price"], key="preset_hk_type")
        elif preset == "加密货币（比特币）":
            instrument_id = st.text_input("标的代码", value="BINANCE:BTCUSDT", key="preset_crypto")
            data_type = st.selectbox("数据类型", ["price"], key="preset_crypto_type")

    st.markdown("---")

    # ========== 第二部分：开始测试 ==========
    col_start, col_status = st.columns([1, 4])

    with col_start:
        start_test = st.button("🚀 开始测试", type="primary", use_container_width=True)

    with col_status:
        if start_test:
            total_tests = (1 if has_auto else 0) + len(selected_sources)
            if total_tests == 0:
                st.warning("请至少选择一个数据源")
            else:
                sources_desc = []
                if has_auto:
                    sources_desc.append("🔄 auto")
                if selected_sources:
                    sources_desc.extend(selected_sources)
                st.info(f"准备测试 {total_tests} 项: {', '.join(sources_desc)}")

    # ========== 第三部分：测试结果 ==========
    if start_test and (has_auto or selected_sources):
        st.markdown("---")
        st.subheader("📊 测试结果")

        # 创建进度条
        progress_bar = st.progress(0)
        status_text = st.empty()

        # 存储结果
        results = []
        total_tests = (1 if has_auto else 0) + len(selected_sources)
        current_test = 0

        # 1. 如果选了 auto，先测试 auto（不传 source，让后端按优先级选择）
        if has_auto:
            current_test += 1
            status_text.text(f"🔄 测试 auto（让后端自动选择最优数据源）... ({current_test}/{total_tests})")

            result = test_data_source(
                db=db,
                source=None,  # 不传 source，让后端自动选择
                data_type=data_type,
                instrument_id=instrument_id,
                save_to_db=save_to_db,
                timeout_seconds=timeout_seconds,
                project_root=project_root,
            )

            # 标记这是 auto 选择的结果，并记录实际使用的数据源
            actual_source = result.get("data", {}).get("source") if result.get("data") else None
            result["is_auto"] = True
            result["auto_selected_source"] = actual_source  # 记录 auto 实际选的数据源
            result["source"] = f"auto→{actual_source}" if actual_source else "auto"
            results.append(result)
            progress_bar.progress(current_test / total_tests)

        # 2. 测试用户手动选择的数据源
        for source in selected_sources:
            current_test += 1
            status_text.text(f"正在测试 {source}... ({current_test}/{total_tests})")

            result = test_data_source(
                db=db,
                source=source,
                data_type=data_type,
                instrument_id=instrument_id,
                save_to_db=save_to_db,
                timeout_seconds=timeout_seconds,
                project_root=project_root,
            )

            result["is_auto"] = False
            results.append(result)
            progress_bar.progress(current_test / total_tests)

        status_text.text("测试完成！")
        time.sleep(0.5)
        progress_bar.empty()
        status_text.empty()

        # 显示结果对比
        display_results_comparison(results, show_raw_response, output_format)


def enrich_price_data(data: dict) -> dict:
    """补充价格数据的空值（基于已有数据计算）"""
    if not data or not isinstance(data, dict):
        return data

    enriched = data.copy()

    # 如果有 close_price 但没有 price，使用 close_price
    if enriched.get("close_price") and not enriched.get("price"):
        enriched["price"] = enriched["close_price"]

    # 如果有 high_price, low_price, open_price 但没有相关字段，可以计算
    if enriched.get("high_price") and enriched.get("low_price"):
        # 计算振幅
        if not enriched.get("amplitude"):
            high = enriched["high_price"]
            low = enriched["low_price"]
            close = enriched.get("close_price", enriched.get("price", 0))
            if close > 0:
                enriched["amplitude"] = (high - low) / close * 100

    # 如果有 price 和 open_price，可以计算 change
    if enriched.get("price") and enriched.get("open_price") and not enriched.get("change"):
        enriched["change"] = enriched["price"] - enriched["open_price"]

    # 如果有 change 和 open_price，可以计算 change_percent
    if enriched.get("change") and enriched.get("open_price") and not enriched.get("change_percent"):
        if enriched["open_price"] > 0:
            enriched["change_percent"] = (enriched["change"] / enriched["open_price"]) * 100

    return enriched


def filter_empty_fields(results: list) -> list:
    """过滤掉所有数据源都为空的字段"""
    if not results:
        return results

    # 收集所有可能的字段
    all_fields = set()
    for result in results:
        if result.get("data") and isinstance(result["data"], dict):
            all_fields.update(result["data"].keys())

    # 找出所有数据源都为空的字段
    empty_fields = set()
    for field in all_fields:
        all_empty = True
        for result in results:
            if result.get("data") and isinstance(result["data"], dict):
                value = result["data"].get(field)
                if value is not None and value != "" and value != "null":
                    all_empty = False
                    break
        if all_empty:
            empty_fields.add(field)

    # 从所有结果中删除这些字段
    filtered_results = []
    for result in results:
        filtered_result = result.copy()
        if filtered_result.get("data") and isinstance(filtered_result["data"], dict):
            filtered_data = {k: v for k, v in filtered_result["data"].items() if k not in empty_fields}
            filtered_result["data"] = filtered_data
        filtered_results.append(filtered_result)

    return filtered_results


def test_data_source(
    db: MonitoringDB,
    source: str | None,  # None 表示自动选择
    data_type: str,
    instrument_id: str,
    save_to_db: bool,
    timeout_seconds: int,
    project_root: Path,
) -> dict:
    """
    测试单个数据源 - 调用真实 API

    Args:
        source: 数据源名称，None 表示让后端自动选择最优数据源

    Returns:
        {
            "source": str,
            "status": str,
            "latency_ms": float,
            "data": dict,
            "error": str,
            "raw_response": str,
        }
    """
    import time
    import httpx

    start_time = time.time()
    display_source = source or "auto"

    try:
        # 调用真实 API
        api_url = "http://stock-mcp-api:9898"

        if data_type == "price":
            # 调用价格接口
            endpoint = f"{api_url}/api/v1/market/prices/batch"
            # 构建 payload，source 为 None 时不传递
            payload = {"tickers": [instrument_id]}
            if source:
                payload["source"] = source

            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(endpoint, json=payload)
                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    result_data = response.json()

                    # 提取该 ticker 的数据（API 直接返回 {ticker: data} 格式）
                    ticker_data = result_data.get(instrument_id, {})

                    if ticker_data and isinstance(ticker_data, dict) and "price" in ticker_data:
                        # 补充空值
                        enriched_data = enrich_price_data(ticker_data)

                        # 获取实际使用的数据源
                        actual_source = enriched_data.get("source", display_source)

                        result = {
                            "source": actual_source,
                            "status": RequestStatus.SUCCESS.value,
                            "latency_ms": latency_ms,
                            "data": enriched_data,
                            "error": None,
                            "raw_response": json.dumps(enriched_data, indent=2, ensure_ascii=False),
                        }
                    else:
                        result = {
                            "source": display_source,
                            "status": RequestStatus.FAILED.value,
                            "latency_ms": latency_ms,
                            "data": None,
                            "error": "无数据返回",
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                else:
                    result = {
                        "source": display_source,
                        "status": RequestStatus.FAILED.value,
                        "latency_ms": latency_ms,
                        "data": None,
                        "error": f"API 错误: {response.status_code}",
                        "raw_response": response.text,
                    }
        elif data_type == "financials":
            # 调用财务数据接口
            endpoint = f"{api_url}/api/v1/fundamental/financials"
            params = {"symbol": instrument_id, "source": source}

            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(endpoint, params=params)
                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    result_data = response.json()

                    if result_data and isinstance(result_data, dict):
                        # API 返回的 income_statement 等是 list（多期财报），取最新一期
                        income_list = result_data.get("income_statement", [])
                        indicators_list = result_data.get("financial_indicators", [])
                        market_list = result_data.get("market_metrics", [])
                        balance_list = result_data.get("balance_sheet", [])
                        cashflow_list = result_data.get("cash_flow", [])

                        # 取最新一期（第一个元素）
                        income = income_list[0] if income_list and isinstance(income_list, list) else {}
                        indicators = indicators_list[0] if indicators_list and isinstance(indicators_list, list) else {}
                        market = market_list[0] if market_list and isinstance(market_list, list) else {}

                        # 检查是否有有效数据（至少有一个非空字段）
                        has_valid_data = any([
                            income, indicators, market,
                            balance_list and balance_list[0] if balance_list else None,
                            cashflow_list and cashflow_list[0] if cashflow_list else None,
                        ])

                        if not has_valid_data:
                            result = {
                                "source": display_source,
                                "status": RequestStatus.FAILED.value,
                                "latency_ms": latency_ms,
                                "data": None,
                                "error": "数据源无此标的的财务数据",
                                "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                            }
                        else:
                            financials = {
                                "symbol": instrument_id,
                                "revenue": income.get("revenue"),
                                "net_income": income.get("n_income_attr_p") or income.get("net_income"),
                                "eps": indicators.get("eps"),
                                "pe_ratio": market.get("pe_ratio"),
                                "roe": indicators.get("roe"),
                                "period": income.get("end_date"),
                                "source": result_data.get("source") or source,
                            }

                            result = {
                                "source": financials.get("source") or display_source,
                                "status": RequestStatus.SUCCESS.value,
                                "latency_ms": latency_ms,
                                "data": financials,
                                "error": None,
                                "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                            }
                    else:
                        result = {
                            "source": source,
                            "status": RequestStatus.FAILED.value,
                            "latency_ms": latency_ms,
                            "data": None,
                            "error": "无财务数据返回",
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                else:
                    result = {
                        "source": source,
                        "status": RequestStatus.FAILED.value,
                        "latency_ms": latency_ms,
                        "data": None,
                        "error": f"API 错误: {response.status_code}",
                        "raw_response": response.text,
                    }
        elif data_type == "news":
            # 调用新闻接口
            endpoint = f"{api_url}/api/v1/news/market"
            params = {"limit": 5}

            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(endpoint, params=params)
                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    result_data = response.json()

                    if result_data and isinstance(result_data, list):
                        news_data = {
                            "symbol": instrument_id,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "count": len(result_data),
                            "headlines": [item.get("title") for item in result_data[:5]],
                            "source": source,
                        }

                        result = {
                            "source": source,
                            "status": RequestStatus.SUCCESS.value,
                            "latency_ms": latency_ms,
                            "data": news_data,
                            "error": None,
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                    else:
                        result = {
                            "source": source,
                            "status": RequestStatus.FAILED.value,
                            "latency_ms": latency_ms,
                            "data": None,
                            "error": "无新闻数据返回",
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                else:
                    result = {
                        "source": source,
                        "status": RequestStatus.FAILED.value,
                        "latency_ms": latency_ms,
                        "data": None,
                        "error": f"API 错误: {response.status_code}",
                        "raw_response": response.text,
                    }
        elif data_type == "event":
            # 调用事件/公告接口 - 根据市场类型选择不同端点
            exchange = instrument_id.split(":")[0] if ":" in instrument_id else "SSE"

            if exchange in ["NASDAQ", "NYSE"]:
                # 美股：使用 SEC 事件公告
                endpoint = f"{api_url}/api/v1/filings/sec/event"
                params = {"ticker": instrument_id.split(":")[-1], "limit": 5}
            else:
                # A股：使用 A股公告
                endpoint = f"{api_url}/api/v1/filings/ashare"
                params = {"symbol": instrument_id.split(":")[-1], "limit": 5}

            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.get(endpoint, params=params)
                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    result_data = response.json()

                    if result_data:
                        # 适配不同的返回格式
                        events_list = result_data if isinstance(result_data, list) else [result_data]
                        events_data = {
                            "symbol": instrument_id,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "count": len(events_list),
                            "events": [
                                {
                                    "title": item.get("title") or item.get("form", ""),
                                    "date": item.get("filing_date") or item.get("report_date", ""),
                                    "type": item.get("form_type") or item.get("form", ""),
                                }
                                for item in events_list[:5]
                            ],
                            "source": source,
                        }

                        result = {
                            "source": source,
                            "status": RequestStatus.SUCCESS.value,
                            "latency_ms": latency_ms,
                            "data": events_data,
                            "error": None,
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                    else:
                        result = {
                            "source": source,
                            "status": RequestStatus.FAILED.value,
                            "latency_ms": latency_ms,
                            "data": None,
                            "error": "无事件数据返回",
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False) if result_data else "",
                        }
                else:
                    result = {
                        "source": source,
                        "status": RequestStatus.FAILED.value,
                        "latency_ms": latency_ms,
                        "data": None,
                        "error": f"API 错误: {response.status_code}",
                        "raw_response": response.text,
                    }
        elif data_type == "forecast":
            # 业绩预测数据
            endpoint = f"{api_url}/api/v1/fundamental/forecast"
            params = {"symbol": instrument_id, "source": source}

            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(endpoint, params=params)
                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    result_data = response.json()

                    if result_data and isinstance(result_data, dict):
                        forecast_data = {
                            "symbol": instrument_id,
                            "period": result_data.get("period"),
                            "forecast_type": result_data.get("forecast_type"),
                            "revenue_forecast": result_data.get("revenue_forecast"),
                            "eps_forecast": result_data.get("eps_forecast"),
                            "source": source,
                        }

                        result = {
                            "source": source,
                            "status": RequestStatus.SUCCESS.value,
                            "latency_ms": latency_ms,
                            "data": forecast_data,
                            "error": None,
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                    else:
                        result = {
                            "source": source,
                            "status": RequestStatus.FAILED.value,
                            "latency_ms": latency_ms,
                            "data": None,
                            "error": "无业绩预测数据返回",
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False) if result_data else "",
                        }
                else:
                    result = {
                        "source": source,
                        "status": RequestStatus.FAILED.value,
                        "latency_ms": latency_ms,
                        "data": None,
                        "error": f"API 错误: {response.status_code}",
                        "raw_response": response.text,
                    }
        elif data_type == "ratios":
            # 财务比率数据
            endpoint = f"{api_url}/api/v1/fundamental/ratios"
            params = {"symbol": instrument_id, "source": source}

            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(endpoint, params=params)
                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    result_data = response.json()

                    if result_data and isinstance(result_data, dict):
                        ratios_data = {
                            "symbol": instrument_id,
                            "pe_ratio": result_data.get("pe_ratio"),
                            "pb_ratio": result_data.get("pb_ratio"),
                            "roe": result_data.get("roe"),
                            "debt_ratio": result_data.get("debt_ratio"),
                            "current_ratio": result_data.get("current_ratio"),
                            "source": source,
                        }

                        result = {
                            "source": source,
                            "status": RequestStatus.SUCCESS.value,
                            "latency_ms": latency_ms,
                            "data": ratios_data,
                            "error": None,
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                    else:
                        result = {
                            "source": source,
                            "status": RequestStatus.FAILED.value,
                            "latency_ms": latency_ms,
                            "data": None,
                            "error": "无财务比率数据返回",
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False) if result_data else "",
                        }
                else:
                    result = {
                        "source": source,
                        "status": RequestStatus.FAILED.value,
                        "latency_ms": latency_ms,
                        "data": None,
                        "error": f"API 错误: {response.status_code}",
                        "raw_response": response.text,
                    }
        elif data_type == "support_resistance":
            # 支撑阻力分析
            endpoint = f"{api_url}/api/v1/market/analysis/support-resistance"
            params = {"symbol": instrument_id}
            payload = {"symbol": instrument_id}

            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(endpoint, json=payload)
                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    result_data = response.json()

                    if result_data and isinstance(result_data, dict):
                        sr_data = {
                            "symbol": instrument_id,
                            "support_levels": result_data.get("support_levels", []),
                            "resistance_levels": result_data.get("resistance_levels", []),
                            "current_price": result_data.get("current_price"),
                            "source": source,
                        }

                        result = {
                            "source": source,
                            "status": RequestStatus.SUCCESS.value,
                            "latency_ms": latency_ms,
                            "data": sr_data,
                            "error": None,
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                    else:
                        result = {
                            "source": source,
                            "status": RequestStatus.FAILED.value,
                            "latency_ms": latency_ms,
                            "data": None,
                            "error": "无支撑阻力数据返回",
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False) if result_data else "",
                        }
                else:
                    result = {
                        "source": source,
                        "status": RequestStatus.FAILED.value,
                        "latency_ms": latency_ms,
                        "data": None,
                        "error": f"API 错误: {response.status_code}",
                        "raw_response": response.text,
                    }
        elif data_type == "technical_indicators":
            # 技术指标
            endpoint = f"{api_url}/api/v1/market/indicators/calculate"
            payload = {
                "symbol": instrument_id,
                "indicators": ["ma", "rsi", "macd"],
            }

            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(endpoint, json=payload)
                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    result_data = response.json()

                    if result_data and isinstance(result_data, dict):
                        ti_data = {
                            "symbol": instrument_id,
                            "indicators": result_data.get("indicators", {}),
                            "signal": result_data.get("signal"),
                            "source": source,
                        }

                        result = {
                            "source": source,
                            "status": RequestStatus.SUCCESS.value,
                            "latency_ms": latency_ms,
                            "data": ti_data,
                            "error": None,
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                    else:
                        result = {
                            "source": source,
                            "status": RequestStatus.FAILED.value,
                            "latency_ms": latency_ms,
                            "data": None,
                            "error": "无技术指标数据返回",
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False) if result_data else "",
                        }
                else:
                    result = {
                        "source": source,
                        "status": RequestStatus.FAILED.value,
                        "latency_ms": latency_ms,
                        "data": None,
                        "error": f"API 错误: {response.status_code}",
                        "raw_response": response.text,
                    }
        elif data_type == "trading_signals":
            # 交易信号
            endpoint = f"{api_url}/api/v1/market/signals/trading"
            payload = {"symbol": instrument_id}

            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(endpoint, json=payload)
                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    result_data = response.json()

                    if result_data and isinstance(result_data, dict):
                        signal_data = {
                            "symbol": instrument_id,
                            "signal": result_data.get("signal"),
                            "confidence": result_data.get("confidence"),
                            "price_target": result_data.get("price_target"),
                            "stop_loss": result_data.get("stop_loss"),
                            "source": source,
                        }

                        result = {
                            "source": source,
                            "status": RequestStatus.SUCCESS.value,
                            "latency_ms": latency_ms,
                            "data": signal_data,
                            "error": None,
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                    else:
                        result = {
                            "source": source,
                            "status": RequestStatus.FAILED.value,
                            "latency_ms": latency_ms,
                            "data": None,
                            "error": "无交易信号数据返回",
                            "raw_response": json.dumps(result_data, indent=2, ensure_ascii=False) if result_data else "",
                        }
                else:
                    result = {
                        "source": source,
                        "status": RequestStatus.FAILED.value,
                        "latency_ms": latency_ms,
                        "data": None,
                        "error": f"API 错误: {response.status_code}",
                        "raw_response": response.text,
                    }
        elif data_type == "macro":
            # 宏观数据 - 目前没有对应的 REST API 端点
            # 这些数据通过 MCP tools 提供: get_inflation_data, get_pmi_data, get_gdp_data 等
            result = {
                "source": source,
                "status": RequestStatus.FAILED.value,
                "latency_ms": 0,
                "data": None,
                "error": "宏观数据暂未提供 REST API 接口，请使用 MCP tools:\n"
                         "- get_inflation_data (通胀数据)\n"
                         "- get_pmi_data (PMI 数据)\n"
                         "- get_gdp_data (GDP 数据)\n"
                         "- get_us_inflation_employment (美国通胀就业)",
                "raw_response": "",
            }
        else:
            # 未知数据类型
            result = {
                "source": source,
                "status": RequestStatus.FAILED.value,
                "latency_ms": 0,
                "data": None,
                "error": f"不支持的数据类型: {data_type}",
                "raw_response": "{}",
            }

        # 保存到数据库
        if save_to_db:
            # 获取实际使用的数据源（用于数据库保存）
            actual_source = result.get("data", {}).get("source") if isinstance(result.get("data"), dict) else None
            db_source = actual_source or source or "auto"

            log = RequestLog(
                timestamp=datetime.now(),
                data_type=data_type,
                instrument_id=instrument_id,
                source=db_source,
                status=result["status"],
                latency_ms=result["latency_ms"],
                error_message=result["error"],
                fields_count=len(result["data"]) if result["data"] else 0,
                has_data=result["data"] is not None,
                raw_response=result["raw_response"],
                parsed_result=json.dumps(result["data"], ensure_ascii=False)
                if result["data"]
                else None,
            )
            db.log_request(log)

        return result

    except Exception as e:
        return {
            "source": source,
            "status": RequestStatus.FAILED.value,
            "latency_ms": (time.time() - start_time) * 1000,
            "data": None,
            "error": str(e),
            "raw_response": f'{{"error": "{str(e)}"}}',
        }


def generate_mock_data(data_type: str, instrument_id: str) -> dict:
    """生成模拟数据"""
    import random
    from datetime import datetime

    current_date = datetime.now().strftime("%Y-%m-%d")

    if data_type == "price":
        return {
            "symbol": instrument_id,
            "date": current_date,
            "price": round(random.uniform(100, 2000), 2),
            "change": round(random.uniform(-5, 5), 2),
            "change_percent": round(random.uniform(-3, 3), 2),
            "volume": random.randint(1000000, 10000000),
            "high": round(random.uniform(100, 2000), 2),
            "low": round(random.uniform(100, 2000), 2),
            "open": round(random.uniform(100, 2000), 2),
        }
    elif data_type == "financials":
        return {
            "symbol": instrument_id,
            "date": current_date,
            "revenue": random.randint(1000000000, 100000000000),
            "net_income": random.randint(100000000, 50000000000),
            "eps": round(random.uniform(1, 20), 2),
            "pe_ratio": round(random.uniform(10, 50), 2),
            "roe": round(random.uniform(0.05, 0.30), 4),
        }
    else:
        return {"data": "mock data", "type": data_type, "date": current_date}


def display_results_comparison(results: list, show_raw_response: bool, output_format: str = "json"):
    """显示结果对比 - 优先展示数据源差异分析"""

    # 过滤空字段
    results = filter_empty_fields(results)

    # 成功率汇总
    success_count = sum(1 for r in results if r["status"] == "success")
    total_count = len(results)

    # ========== 1. 优先展示：数据源差异分析 ==========
    # 合并所有成功的数据源结果
    merged_data = {}
    for r in results:
        if r["status"] == "success" and r["data"]:
            merged_data[r["source"]] = r["data"]

    if len(merged_data) >= 2:
        st.markdown("### 🔍 数据源差异分析")

        # 收集所有字段和对应值
        all_fields = set()
        source_field_values = {}  # {source: {field: value}}

        for source, data in merged_data.items():
            if isinstance(data, dict):
                source_field_values[source] = data
                all_fields.update(data.keys())

        # 按字段排序
        sorted_fields = sorted(all_fields)
        sources = list(source_field_values.keys())

        # 构建对比数据
        comparison_rows = []
        consistency_stats = {"一致": 0, "差异": 0, "部分缺失": 0, "完全缺失": 0}

        for field in sorted_fields:
            row_data = {"字段": field}
            values_by_source = []

            for source in sources:
                value = source_field_values[source].get(field)
                values_by_source.append(value)

                if value is None:
                    row_data[source] = "❌ null"
                elif isinstance(value, float):
                    row_data[source] = f"{value:,.2f}"  # 改为2位小数
                elif isinstance(value, int):
                    row_data[source] = f"{value:,}"
                else:
                    row_data[source] = str(value)[:20] if len(str(value)) > 20 else str(value)

            # 计算该字段的一致性
            non_null_values = [v for v in values_by_source if v is not None]
            if len(non_null_values) == 0:
                row_data["状态"] = "⚠️ 部分缺失"
                consistency_stats["部分缺失"] += 1
            else:
                # 检查数值是否一致（允许 0.1% 的误差）
                is_consistent = True
                first_val = non_null_values[0]
                for v in non_null_values[1:]:
                    if isinstance(first_val, (int, float)) and isinstance(v, (int, float)):
                        if first_val != 0 and abs((v - first_val) / first_val) > 0.001:  # 0.1% 误差
                            is_consistent = False
                    elif v != first_val:
                        is_consistent = False

                if is_consistent:
                    row_data["状态"] = "✅ 一致"
                    consistency_stats["一致"] += 1
                else:
                    row_data["状态"] = "⚠️ 差异"
                    consistency_stats["差异"] += 1

                # 计算最大差异
                if isinstance(first_val, (int, float)):
                    numeric_values = [v for v in non_null_values if isinstance(v, (int, float))]
                    if len(numeric_values) >= 2:
                        max_val = max(numeric_values)
                        min_val = min(numeric_values)
                        if min_val != 0:
                            max_diff_pct = abs((max_val - min_val) / min_val) * 100
                            row_data["最大差异%"] = f"{max_diff_pct:.2f}%"

            comparison_rows.append(row_data)

        # 显示统计信息（放在表格上面）
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("✅ 一致", consistency_stats["一致"])
        with col2:
            st.metric("⚠️ 差异", consistency_stats["差异"])
        with col3:
            st.metric("❌ 缺失", consistency_stats["部分缺失"])
        with col4:
            total = sum(consistency_stats.values())
            consistency_pct = (consistency_stats["一致"] / total * 100) if total > 0 else 0
            st.metric("一致性", f"{consistency_pct:.1f}%")
        with col5:
            avg_latency = sum(r["latency_ms"] for r in results) / len(results) if results else 0
            st.metric("平均延迟", f"{avg_latency:.0f}ms")

        # 显示对比表格
        df_comparison = pd.DataFrame(comparison_rows)
        st.dataframe(
            df_comparison,
            use_container_width=True,
            hide_index=True,
        )

        # 差异详情
        diff_fields = [r for r in comparison_rows if "差异" in r["状态"]]
        if diff_fields:
            with st.expander("📋 差异字段详情", expanded=False):
                for r in diff_fields:
                    st.markdown(f"**{r['字段']}**")
                    cols = st.columns(len(sources))
                    for i, source in enumerate(sources):
                        with cols[i]:
                            st.code(str(r.get(source, "-")))

        st.markdown("---")

    # ========== 2. 简化结果概览 ==========
    st.markdown("### 📊 数据源概览")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("成功率", f"{success_count}/{total_count}")
    with col2:
        if results:
            best_source = min(results, key=lambda x: x["latency_ms"])
            st.metric("最快数据源", best_source["source"])
    with col3:
        if merged_data:
            st.metric("字段数", len(list(merged_data.values())[0]) if merged_data else 0)

    # 对比表格
    comparison_data = [
        {
            "数据源": r["source"],
            "状态": "✅ 成功" if r["status"] == "success" else "❌ 失败",
            "延迟": f"{r['latency_ms']:.0f}ms",
            "字段数": len(r["data"]) if r["data"] else 0,
            "错误": r["error"] or "-",
        }
        for r in results
    ]
    st.dataframe(comparison_data, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ========== 3. 详细结果（折叠） ==========
    st.markdown("### 📋 详细结果")

    for result in results:
        with st.expander(
            f"{'✅' if result['status'] == 'success' else '❌'} {result['source']} - {result['latency_ms']:.0f}ms",
            expanded=False,  # 默认折叠
        ):
            col_data, col_raw = st.columns([1, 1])

            with col_data:
                st.markdown("**解析结果**")
                if result["data"]:
                    # 根据输出格式显示
                    if output_format == "json":
                        st.json(result["data"])
                    else:
                        # Markdown 格式
                        md_content = "```json\n" + json.dumps(result["data"], indent=2, ensure_ascii=False) + "\n```"
                        st.markdown(md_content)
                else:
                    st.error(result["error"])

            with col_raw:
                if show_raw_response:
                    st.markdown("**原始响应**")
                    st.code(result["raw_response"], language="json")

    # ========== 4. 合并结果（可复制） ==========
    if merged_data:
        st.markdown("---")
        st.markdown("### 📋 合并结果（可复制）")

        if output_format == "json":
            merged_str = json.dumps(merged_data, indent=2, ensure_ascii=False)
            st.code(merged_str, language="json")
        else:
            # Markdown 表格格式
            md_lines = ["| 数据源 | " + " | ".join(merged_data.keys()) + " |"]
            md_lines.append("|--------|" + "|".join(["--------"] * len(merged_data)) + "|")

            # 获取所有可能的字段
            all_fields = set()
            for data in merged_data.values():
                all_fields.update(data.keys())

            # 生成表格行
            for field in sorted(all_fields):
                row = [field]
                for source in merged_data.keys():
                    value = merged_data[source].get(field, "-")
                    if value is None:
                        value = "null"
                    elif isinstance(value, (int, float)):
                        value = f"{value:,.2f}" if isinstance(value, float) else f"{value:,}"
                    row.append(str(value))
                md_lines.append("| " + " | ".join(row) + " |")

            merged_str = "\n".join(md_lines)
            st.markdown(merged_str)

        st.info("💡 上方内容可直接复制")
    else:
        st.warning("没有成功的数据源，无法合并结果")
