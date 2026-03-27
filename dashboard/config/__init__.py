"""
配置模块

提供数据维度配置加载和请求构建功能。
"""

from .config_loader import (
    ConfigLoader,
    DataDimension,
    Market,
    DataDimensionsConfig,
    HttpMethod,
    RequestType,
    get_config,
)
from .request_builder import (
    build_request,
    fetch_data_by_config,
    parse_template_value,
)

__all__ = [
    "ConfigLoader",
    "DataDimension",
    "Market",
    "DataDimensionsConfig",
    "HttpMethod",
    "RequestType",
    "get_config",
    "build_request",
    "fetch_data_by_config",
    "parse_template_value",
]
