"""
Dashboard 配置

从环境变量读取配置，支持 Docker 和本地运行。
"""

import os
from pathlib import Path


# API 基础地址 - 优先从环境变量读取
API_BASE_URL = os.getenv(
    "STOCK_MCP_API_URL",
    os.getenv("API_BASE_URL", "http://stock-mcp-api:9898")
)

# Redis 配置
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_DB = int(os.getenv("REDIS_DB", "0"))

# Dashboard 配置
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8501"))
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"

# 配置文件路径
CONFIG_DIR = Path(__file__).parent
DATA_DIMENSIONS_CONFIG = CONFIG_DIR / "data_dimensions.yaml"


def get_api_base_url() -> str:
    """获取 API 基础地址"""
    return API_BASE_URL


def get_redis_config() -> dict:
    """获取 Redis 配置"""
    return {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "password": REDIS_PASSWORD,
        "db": REDIS_DB,
    }
