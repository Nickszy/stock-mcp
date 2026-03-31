"""
数据质量测试脚本 v2
测试所有数据维度在所有数据源上的可用性和数据质量
"""
import httpx
import json
import time
import sys
from datetime import datetime

# Windows编码问题修复
sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://localhost:9898"

# 测试股票池 - 覆盖A股、美股、港股
TEST_STOCKS = {
    "A股": ["SSE:600519", "SZSE:000001", "SZSE:300750"],  # 茅台、平安、宁德
    "美股": ["NASDAQ:AAPL", "NASDAQ:MSFT", "NASDAQ:GOOGL"],  # 苹果、微软、谷歌
    "港股": ["HKEX:00700", "HKEX:09988", "HKEX:01810"],  # 腾讯、阿里、小米
}

# 数据源
DATA_SOURCES = ["tushare", "baostock", "akshare", "yahoo", "finnhub"]


def get_price(symbol: str, source: str = None) -> dict:
    """获取价格数据 - POST /api/v1/market/prices/batch"""
    payload = {"tickers": [symbol]}
    if source:
        payload["source"] = source
    try:
        resp = httpx.post(f"{BASE_URL}/api/v1/market/prices/batch", json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            return {"success": True, "data": data.get(symbol, {})}
        return {"success": False, "error": resp.text, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_financials(symbol: str) -> dict:
    """获取财务数据 - POST /api/v1/fundamental/financials"""
    try:
        resp = httpx.post(f"{BASE_URL}/api/v1/fundamental/financials", params={"symbol": symbol}, timeout=30)
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        return {"success": False, "error": resp.text, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_forecast(symbol: str) -> dict:
    """获取盈利预测 - POST /api/v1/fundamental/forecast"""
    try:
        resp = httpx.post(f"{BASE_URL}/api/v1/fundamental/forecast", params={"symbol": symbol}, timeout=30)
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        return {"success": False, "error": resp.text, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_ratios(symbol: str) -> dict:
    """获取财务比率 - POST /api/v1/fundamental/ratios"""
    try:
        resp = httpx.post(f"{BASE_URL}/api/v1/fundamental/ratios", params={"symbol": symbol}, timeout=30)
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        return {"success": False, "error": resp.text, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_news(symbol: str) -> dict:
    """获取新闻 - GET /api/v1/news/stock"""
    try:
        resp = httpx.get(f"{BASE_URL}/api/v1/news/stock", params={"symbol": symbol, "days_back": 7}, timeout=30)
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        return {"success": False, "error": resp.text, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_technical_indicators(symbol: str) -> dict:
    """获取技术指标 - POST /api/v1/market/indicators/calculate"""
    payload = {"symbol": symbol, "period": "30d", "interval": "1d"}
    try:
        resp = httpx.post(f"{BASE_URL}/api/v1/market/indicators/calculate", json=payload, timeout=30)
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        return {"success": False, "error": resp.text, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_support_resistance(symbol: str) -> dict:
    """获取支撑阻力位 - POST /api/v1/market/analysis/support-resistance"""
    payload = {"symbol": symbol, "period": "30d"}
    try:
        resp = httpx.post(f"{BASE_URL}/api/v1/market/analysis/support-resistance", json=payload, timeout=30)
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        return {"success": False, "error": resp.text, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_trading_signals(symbol: str) -> dict:
    """获取交易信号 - POST /api/v1/market/signals/trading"""
    payload = {"symbol": symbol, "period": "30d"}
    try:
        resp = httpx.post(f"{BASE_URL}/api/v1/market/signals/trading", json=payload, timeout=30)
        if resp.status_code == 200:
            return {"success": True, "data": resp.json()}
        return {"success": False, "error": resp.text, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_data_quality(data: dict, data_type: str) -> dict:
    """检查数据质量"""
    if not data:
        return {"has_data": False, "field_count": 0, "null_ratio": 1.0, "issues": ["数据为空"]}

    issues = []
    total_fields = 0
    null_fields = 0

    def count_fields(obj, prefix="", depth=0):
        nonlocal total_fields, null_fields
        if depth > 5:  # 防止无限递归
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if v is None or v == "" or v == [] or v == {}:
                    null_fields += 1
                    if len(issues) < 5:
                        issues.append(f"{prefix}{k} 为空")
                elif isinstance(v, (dict, list)) and depth < 4:
                    count_fields(v, f"{prefix}{k}.", depth + 1)
                total_fields += 1
        elif isinstance(obj, list):
            for i, item in enumerate(obj[:3]):  # 只检查前3个元素
                if isinstance(item, (dict, list)):
                    count_fields(item, f"{prefix}[{i}].", depth + 1)

    count_fields(data)

    null_ratio = null_fields / total_fields if total_fields > 0 else 1.0
    has_data = total_fields > 0 and null_ratio < 0.8

    return {
        "has_data": has_data,
        "field_count": total_fields,
        "null_count": null_fields,
        "null_ratio": round(null_ratio, 2),
        "issues": issues,
    }


# 数据类型到API函数的映射
DATA_TYPE_APIS = {
    "price": get_price,
    "financials": get_financials,
    "forecast": get_forecast,
    "ratios": get_ratios,
    "news": get_news,
    "technical_indicators": get_technical_indicators,
    "support_resistance": get_support_resistance,
    "trading_signals": get_trading_signals,
}


def main():
    print("=" * 80)
    print(f"数据质量测试报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    results = {}

    for market, symbols in TEST_STOCKS.items():
        print(f"\n## {market} 市场")
        print("-" * 60)
        results[market] = {}

        for symbol in symbols:
            print(f"\n### {symbol}")
            results[market][symbol] = {}

            for data_type, api_func in DATA_TYPE_APIS.items():
                print(f"\n#### {data_type}")
                type_results = {}

                # 对于price类型，测试不同数据源
                if data_type == "price":
                    for source in DATA_SOURCES:
                        result = api_func(symbol, source)
                        if result["success"]:
                            quality = check_data_quality(result["data"], data_type)
                            type_results[source] = {"quality": quality}
                            status = "✓" if quality["has_data"] else "✗"
                            print(f"  {source}: {status} | 字段: {quality['field_count']} | 空值率: {quality['null_ratio']}")
                        else:
                            error_msg = result.get("error", "")[:60]
                            type_results[source] = {"error": error_msg}
                            # 简化输出，只显示错误来源
                            if "error" in result:
                                print(f"  {source}: ✗ 错误")
                else:
                    # 其他数据类型只测试默认
                    result = api_func(symbol)
                    if result["success"]:
                        quality = check_data_quality(result["data"], data_type)
                        type_results["default"] = {"quality": quality}
                        status = "✓" if quality["has_data"] else "✗"
                        print(f"  结果: {status} | 字段: {quality['field_count']} | 空值率: {quality['null_ratio']}")
                    else:
                        error_msg = result.get("error", "")[:60]
                        type_results["default"] = {"error": error_msg}
                        print(f"  结果: ✗ 错误")

                results[market][symbol][data_type] = type_results
                time.sleep(0.05)  # 避免请求过快

    # 保存结果
    with open("data_quality_report.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 输出汇总报告
    print("\n" + "=" * 80)
    print("数据质量汇总报告")
    print("=" * 80)

    # 按数据类型汇总
    for data_type in DATA_TYPE_APIS:
        print(f"\n## {data_type}")
        total = 0
        success = 0

        for market in results:
            for symbol in results[market]:
                if data_type in results[market][symbol]:
                    total += 1
                    type_data = results[market][symbol][data_type]
                    for source, data in type_data.items():
                        if "quality" in data and data["quality"]["has_data"]:
                            success += 1
                            break  # 只要有一个数据源成功就算成功

        rate = f"{success}/{total}" if total > 0 else "0/0"
        pct = round(success / total * 100, 1) if total > 0 else 0
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        print(f"  成功率: {bar} {rate} ({pct}%)")

    # 按市场汇总
    print("\n## 按市场汇总")
    for market in results:
        total = 0
        success = 0
        for symbol in results[market]:
            for data_type in results[market][symbol]:
                total += 1
                for source, data in results[market][symbol][data_type].items():
                    if "quality" in data and data["quality"]["has_data"]:
                        success += 1
                        break
        rate = f"{success}/{total}"
        pct = round(success / total * 100, 1) if total > 0 else 0
        print(f"  {market}: {rate} ({pct}%)")

    print("\n报告已保存到 data_quality_report.json")


if __name__ == "__main__":
    main()
