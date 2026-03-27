"""
配置加载器模块

从 YAML 文件加载数据维度配置，提供便捷的访问接口。
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional
import yaml
from pydantic import BaseModel, Field
from enum import Enum


class HttpMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


class RequestType(str, Enum):
    JSON_BODY = "json_body"
    QUERY_PARAMS = "query_params"
    PATH_AND_QUERY = "path_and_query"


class DataDimension(BaseModel):
    """数据维度配置"""
    display_name: str
    description: str
    category: str
    api_endpoint: str
    http_method: HttpMethod
    request_type: RequestType
    request_template: Dict[str, Any]
    response_path: Optional[str] = None
    key_fields: List[str]
    supported_markets: List[str]
    timeout: int = 30


class Market(BaseModel):
    """市场配置"""
    tickers: List[str]
    sources: List[str]


class DataDimensionsConfig(BaseModel):
    """根配置模型"""
    version: str
    api_base: str
    markets: Dict[str, Market]
    data_dimensions: Dict[str, DataDimension]


class ConfigLoader:
    """配置加载器（单例模式）"""

    _instance: Optional['ConfigLoader'] = None
    _config: Optional[DataDimensionsConfig] = None

    def __new__(cls, config_path: Optional[Path] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: Optional[Path] = None):
        if config_path:
            self._config_path = config_path
        elif not hasattr(self, '_config_path'):
            self._config_path = Path(__file__).parent / "data_dimensions.yaml"

    def load(self, force_reload: bool = False) -> DataDimensionsConfig:
        """加载配置文件"""
        if self._config and not force_reload:
            return self._config

        with open(self._config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)

        self._config = DataDimensionsConfig(**raw_config)
        return self._config

    def get_dimension(self, dimension_key: str) -> Optional[DataDimension]:
        """获取指定数据维度"""
        config = self.load()
        return config.data_dimensions.get(dimension_key)

    def get_all_dimensions(self) -> Dict[str, DataDimension]:
        """获取所有数据维度"""
        config = self.load()
        return config.data_dimensions

    def get_market(self, market_name: str) -> Optional[Market]:
        """获取指定市场配置"""
        config = self.load()
        return config.markets.get(market_name)

    def get_all_markets(self) -> Dict[str, Market]:
        """获取所有市场配置"""
        config = self.load()
        return config.markets

    def get_dimensions_by_category(self, category: str) -> Dict[str, DataDimension]:
        """按类别获取数据维度"""
        config = self.load()
        return {
            k: v for k, v in config.data_dimensions.items()
            if v.category == category
        }

    def get_dimensions_for_market(self, market: str) -> Dict[str, DataDimension]:
        """获取支持指定市场的数据维度"""
        config = self.load()
        return {
            k: v for k, v in config.data_dimensions.items()
            if market in v.supported_markets
        }

    def get_api_base(self) -> str:
        """获取 API 基础地址（支持环境变量覆盖）"""
        # 优先使用环境变量
        env_api_base = os.getenv("STOCK_MCP_API_URL") or os.getenv("API_BASE_URL")
        if env_api_base:
            return env_api_base
        # 否则使用配置文件中的值
        config = self.load()
        return config.api_base


def get_config() -> ConfigLoader:
    """获取配置加载器单例"""
    return ConfigLoader()
