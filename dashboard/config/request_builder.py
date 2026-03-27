"""
请求构建器模块

根据数据维度配置构建 HTTP 请求。
"""

import json
import re
from typing import Dict, Any, Optional, Tuple
import httpx

from .config_loader import DataDimension, RequestType, get_config


def parse_template_value(value: str, context: Dict[str, Any]) -> Any:
    """
    解析模板值，支持默认值语法 {var:default}

    例如:
      "{ticker}" -> 使用 context["ticker"]
      "{days:20}" -> 使用 context.get("days", "20")
    """
    if not isinstance(value, str):
        return value

    # 匹配 {var} 或 {var:default}
    match = re.match(r"\{(\w+)(?::([^}]*))?\}", value)
    if match:
        var_name = match.group(1)
        default_value = match.group(2)

        if var_name in context and context[var_name] is not None:
            return context[var_name]
        elif default_value is not None:
            return default_value
        else:
            return None

    return value


def build_request(
    dimension: DataDimension,
    ticker: str,
    source: Optional[str] = None,
    **kwargs
) -> Tuple[str, str, Dict[str, Any], Dict[str, Any]]:
    """
    构建 HTTP 请求

    Args:
        dimension: 数据维度配置
        ticker: 股票代码 (如 "SSE:600519")
        source: 数据源 (可选)
        **kwargs: 其他参数 (period, days 等)

    Returns:
        (method, url, params, json_body)
    """
    # 提取 ticker 组件
    ticker_parts = ticker.split(":")
    ticker_raw = ticker_parts[-1] if len(ticker_parts) > 1 else ticker

    # 构建变量上下文
    context = {
        "ticker": ticker,
        "ticker_raw": ticker_raw,
        "source": source if source and source != "auto" else None,
        **kwargs
    }

    # 构建 URL (处理路径参数)
    url = dimension.api_endpoint
    if "{" in url:
        for key, value in context.items():
            placeholder = "{" + key + "}"
            if placeholder in url:
                url = url.replace(placeholder, str(value) if value else "")

    # 根据请求类型构建参数
    params = {}
    json_body = {}

    template = dimension.request_template

    if dimension.request_type == RequestType.JSON_BODY:
        # JSON body 请求
        for key, value in template.items():
            if isinstance(value, str):
                json_body[key] = parse_template_value(value, context)
            elif isinstance(value, list):
                json_body[key] = [parse_template_value(v, context) if isinstance(v, str) else v for v in value]
            else:
                json_body[key] = value

        # 移除 None 值
        json_body = {k: v for k, v in json_body.items() if v is not None}

    elif dimension.request_type == RequestType.QUERY_PARAMS:
        # Query params 请求
        for key, value in template.items():
            parsed = parse_template_value(value, context) if isinstance(value, str) else value
            if parsed is not None:
                params[key] = parsed

    elif dimension.request_type == RequestType.PATH_AND_QUERY:
        # 路径参数 + Query params
        if "query_params" in template:
            for key, value in template["query_params"].items():
                parsed = parse_template_value(value, context) if isinstance(value, str) else value
                if parsed is not None:
                    params[key] = parsed

    return dimension.http_method.value, url, params, json_body


async def fetch_data_by_config(
    client: httpx.AsyncClient,
    dimension_key: str,
    ticker: str,
    source: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    根据配置获取数据

    这是统一的 API 请求入口。
    """
    config_loader = get_config()
    dimension = config_loader.get_dimension(dimension_key)

    if not dimension:
        return {"error": f"未知数据维度: {dimension_key}"}

    api_base = config_loader.get_api_base()

    # 构建请求
    method, endpoint, params, json_body = build_request(
        dimension, ticker, source, **kwargs
    )

    url = f"{api_base}{endpoint}"

    try:
        if method == "POST":
            if json_body:
                response = await client.post(
                    url, json=json_body, timeout=dimension.timeout
                )
            else:
                response = await client.post(
                    url, params=params, timeout=dimension.timeout
                )
        elif method == "GET":
            response = await client.get(
                url, params=params, timeout=dimension.timeout
            )
        else:
            return {"error": f"不支持的 HTTP 方法: {method}"}

        if response.status_code == 200:
            data = response.json()

            # 应用响应路径提取
            if dimension.response_path:
                path = dimension.response_path
                if path.startswith("{") and path.endswith("}"):
                    key = path[1:-1]
                    if key == "ticker":
                        key = ticker
                    data = data.get(key, {"error": "无数据"})

            return data
        else:
            return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}

    except Exception as e:
        return {"error": str(e)}
