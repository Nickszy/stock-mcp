"""
数据质量测试脚本
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
    "A股": ["600519", "000001", "300750"],  # 茅台、平安、宁德
    "美股": ["AAPL", "MSFT", "GOOGL"],  # 苹果、微软、谷歌
    "港股": ["00700", "09988", "01810"],  # 腾讯、阿里、小米
}

# 数据维度
DATA_TYPES = [
    "price",
    "financials",
    "forecast",
    "ratios",
    "news",
    "event",
    "support_resistance",
    "technical_indicators",
    "trading_signals",
]

# 数据源
DATA_SOURCES = ["tushare", "baostock", "akshare", "yahoo", "finnhub"]


def call_api(data_type: str, symbol: str, source: str = None) -> dict:
    """调用API获取数据"""
    params = {"symbol": symbol}
    if source:
        params["source"] = source

    try:
        resp = httpx.get(f"{BASE_URL}/data/{data_type}", params=params, timeout=30)
        if resp.status_code == 200:
            return {"success": True, "data": resp.json(), "status": resp.status_code}
        else:
            return {"success": False, "error": resp.text, "status": resp.status_code}
    except Exception as e:
        return {"success": False, "error": str(e), "status": 0}


def check_data_quality(data: dict, data_type: str) -> dict:
    """检查数据质量"""
    if not data:
        return {"has_data": False, "field_count": 0, "null_ratio": 1.0, "issues": ["数据为空"]}

    issues = []
    total_fields = 0
    null_fields = 0

    def count_fields(obj, prefix=""):
        nonlocal total_fields, null_fields
        if isinstance(obj, dict):
            for k, v in obj.items():
                if v is None or v == "" or v == [] or v == {}:
                    null_fields += 1
                    issues.append(f"{prefix}{k} 为空")
                elif isinstance(v, (dict, list)):
                    count_fields(v, f"{prefix}{k}.")
                total_fields += 1
        elif isinstance(obj, list):
            for i, item in enumerate(obj[:5]):  # 只检查前5个元素
                count_fields(item, f"{prefix}[{i}].")

    count_fields(data)

    null_ratio = null_fields / total_fields if total_fields > 0 else 1.0
    has_data = total_fields > 0 and null_ratio < 0.9

    return {
        "has_data": has_data,
        "field_count": total_fields,
        "null_count": null_fields,
        "null_ratio": round(null_ratio, 2),
        "issues": issues[:10] if issues else [],  # 只保留前10个问题
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

            for data_type in DATA_TYPES:
                print(f"\n#### {data_type}")
                type_results = {}

                # 先测试不指定数据源（自动选择）
                result = call_api(data_type, symbol)
                if result["success"]:
                    quality = check_data_quality(result["data"], data_type)
                    type_results["auto"] = {
                        "source": result["data"].get("source", "unknown"),
                        "quality": quality,
                    }
                    print(f"  自动选择: {type_results['auto']['source']} | 数据: {'✓' if quality['has_data'] else '✗'} | 字段: {quality['field_count']} | 空值率: {quality['null_ratio']}")
                else:
                    type_results["auto"] = {"error": result["error"]}
                    print(f"  自动选择: ✗ {result['error'][:50]}")

                # 测试每个数据源
                for source in DATA_SOURCES:
                    result = call_api(data_type, symbol, source)
                    if result["success"]:
                        quality = check_data_quality(result["data"], data_type)
                        type_results[source] = {"quality": quality}
                        status = "✓" if quality["has_data"] else "✗"
                        print(f"  {source}: {status} | 字段: {quality['field_count']} | 空值率: {quality['null_ratio']}")
                    else:
                        error_msg = result["error"][:50] if result["error"] else f"HTTP {result['status']}"
                        type_results[source] = {"error": error_msg}
                        # 不打印每个错误，太多噪音

                results[market][symbol][data_type] = type_results
                time.sleep(0.1)  # 避免请求过快

    # 保存结果到文件
    with open("data_quality_report.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # 输出汇总
    print("\n" + "=" * 80)
    print("汇总报告")
    print("=" * 80)

    for market in results:
        print(f"\n## {market}")
        for data_type in DATA_TYPES:
            sources_ok = {"tushare": 0, "baostock": 0, "akshare": 0, "yahoo": 0, "finnhub": 0, "auto": 0}
            sources_total = {"tushare": 0, "baostock": 0, "akshare": 0, "yahoo": 0, "finnhub": 0, "auto": 0}

            for symbol in results[market]:
                if data_type in results[market][symbol]:
                    for source in sources_ok:
                        sources_total[source] += 1
                        if source in results[market][symbol][data_type]:
                            r = results[market][symbol][data_type][source]
                            if "quality" in r and r["quality"]["has_data"]:
                                sources_ok[source] += 1
                            elif source == "auto" and "source" in r:
                                # 自动选择成功也算
                                sources_ok[source] += 1

            summary = " | ".join([f"{s}:{sources_ok[s]}/{sources_total[s]}" for s in sources_ok if sources_total[s] > 0])
            print(f"  {data_type}: {summary}")

    print("\n报告已保存到 data_quality_report.json")


if __name__ == "__main__":
    main()
